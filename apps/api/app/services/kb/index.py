"""Making the corpus searchable: links, chunks, tsvectors, embeddings.

Three passes, each idempotent and each resumable, because the embedding pass
takes minutes on CPU and a laptop lid closes:

* :func:`build_links` — regex cross-references into ``statute_links``;
* :func:`build_chunks` — chunk rows plus their English ``tsvector``;
* :func:`embed_chunks` — vectors for every chunk that has none yet.

The HNSW index is dropped before a bulk embed and rebuilt once at the end.
Maintaining it row by row through 1,500 inserts costs far more than building it
in one pass, and a half-built graph is worse than no graph.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Delete, Select, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import IngestRun, KbChunk, Statute, StatuteLink, StatuteSection
from app.services.kb.chunk import chunk_section
from app.services.kb.crossref import SectionRow, extract_links, normalise_act_title
from app.services.kb.crossref import normalise_section_no as _norm_no
from app.services.kb.embedding import embed_passages, token_counter

logger = get_logger(__name__)

VECTOR_INDEX = "ix_kb_chunks_embedding_hnsw"
PORTAL = "indiacode"

# Omitted provisions are excluded from the index. India Code keeps repealed
# sections as items so the numbering stays continuous, and their bodies are
# either the single word "Repealed." or law that no longer applies. Retrieving
# repealed law and citing it as the answer is the worst failure this product
# has, so they are not chunked. They remain in ``statute_sections``, so a
# reader that wants to show the gap still can.
INDEXABLE = StatuteSection.is_omitted.is_(False)


@dataclass
class LinkReport:
    """What one cross-reference pass found."""

    sections_scanned: int = 0
    links_written: int = 0
    unresolved: list[dict[str, str]] = field(default_factory=list)

    @property
    def unresolved_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.unresolved:
            counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        return counts


@dataclass
class ChunkReport:
    """What one chunking pass produced."""

    sections_chunked: int = 0
    chunks_written: int = 0
    max_tokens_seen: int = 0
    split_sections: int = 0


@dataclass
class EmbedReport:
    """What one embedding pass did."""

    pending_at_start: int = 0
    embedded: int = 0
    index_rebuilt: bool = False


@dataclass
class IndexStats:
    """Everything ``legaledge-kb stats`` and ``/v1/health`` report."""

    statutes: int
    sections: int
    sections_in_force: int
    chunks: int
    chunks_embedded: int
    links: int
    vector_index_ready: bool
    max_chunk_tokens: int | None


# --- pass 1: cross-references ---------------------------------------------


def build_links(session: Session, *, slug: str | None = None) -> LinkReport:
    """Extract and store internal cross-references. Safe to re-run."""
    statute_ids_by_title = {
        normalise_act_title(title): sid
        for sid, title in session.execute(select(Statute.id, Statute.short_title)).all()
    }
    sections_by_statute: dict[int, dict[str, int]] = {}
    for sid, statute_id, section_no in session.execute(
        select(StatuteSection.id, StatuteSection.statute_id, StatuteSection.section_no)
    ).all():
        sections_by_statute.setdefault(statute_id, {})[_norm_no(section_no)] = sid

    rows = session.execute(
        _scope(
            select(
                StatuteSection.id,
                StatuteSection.statute_id,
                StatuteSection.section_no,
                StatuteSection.text_verbatim,
            ).where(INDEXABLE),
            slug,
        )
    ).all()

    report = LinkReport()
    payload: list[dict[str, object]] = []
    for sid, statute_id, section_no, body in rows:
        report.sections_scanned += 1
        links, unresolved = extract_links(
            SectionRow(id=sid, statute_id=statute_id, section_no=section_no, text=body),
            sections_by_statute=sections_by_statute,
            statute_ids_by_title=statute_ids_by_title,
        )
        payload.extend(
            {
                "from_section_id": link.from_section_id,
                "to_section_id": link.to_section_id,
                "relation": link.relation,
                "raw_text": link.raw_text,
            }
            for link in links
        )
        report.unresolved.extend(
            {
                "kind": item.kind,
                "detail": item.detail,
                "raw_text": item.raw_text,
                "section_id": str(item.from_section_id),
            }
            for item in unresolved
        )

    if payload:
        for start in range(0, len(payload), 1000):
            stmt = insert(StatuteLink).values(payload[start : start + 1000])
            session.execute(stmt.on_conflict_do_nothing(constraint="uq_statute_links_edge"))
    session.flush()
    report.links_written = len(payload)
    _record_run(
        session,
        command="link",
        slug=slug,
        sections=report.sections_scanned,
        warnings=[
            {"kind": kind, "detail": f"{count} unresolved references"}
            for kind, count in sorted(report.unresolved_by_kind.items())
        ],
    )
    session.commit()
    logger.info(
        "links_built",
        sections=report.sections_scanned,
        links=report.links_written,
        unresolved=len(report.unresolved),
    )
    return report


# --- pass 2: chunks and tsvectors ------------------------------------------


def build_chunks(
    settings: Settings, session: Session, *, slug: str | None = None, refresh: bool = False
) -> ChunkReport:
    """Chunk every indexable section that has no chunks yet.

    ``refresh`` deletes and rebuilds instead, which is what a chunker change
    requires — and which necessarily discards the embeddings, since the string
    that was embedded no longer exists.
    """
    count_tokens = token_counter(settings)
    max_tokens = settings.MAX_CHUNK_TOKENS

    if refresh:
        session.execute(_scope_delete(delete(KbChunk), slug))
        session.flush()

    already = {row[0] for row in session.execute(select(KbChunk.section_id).distinct()).all()}
    rows = session.execute(
        _scope(
            select(
                StatuteSection.id,
                StatuteSection.statute_id,
                StatuteSection.marginal_note,
                StatuteSection.text_verbatim,
                Statute.short_title,
            )
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(INDEXABLE)
            .order_by(StatuteSection.statute_id, StatuteSection.section_no_sort),
            slug,
        )
    ).all()

    report = ChunkReport()
    payload: list[dict[str, object]] = []
    for section_id, statute_id, marginal_note, body, short_title in rows:
        if section_id in already:
            continue
        chunks = chunk_section(
            short_title=short_title,
            marginal_note=marginal_note,
            text=body,
            count_tokens=count_tokens,
            max_tokens=max_tokens,
        )
        if not chunks:
            continue
        report.sections_chunked += 1
        report.split_sections += 1 if len(chunks) > 1 else 0
        for chunk in chunks:
            report.max_tokens_seen = max(report.max_tokens_seen, chunk.token_count)
            payload.append(
                {
                    "section_id": section_id,
                    "statute_id": statute_id,
                    "chunk_idx": chunk.chunk_idx,
                    "heading_prefix": chunk.heading_prefix,
                    "text": chunk.text,
                    "token_count": chunk.token_count,
                }
            )

    for start in range(0, len(payload), 500):
        stmt = insert(KbChunk).values(payload[start : start + 500])
        session.execute(stmt.on_conflict_do_nothing(constraint="uq_kb_chunks_section_idx"))
    report.chunks_written = len(payload)
    session.flush()
    _populate_tsv(session)
    _record_run(session, command="chunk", slug=slug, sections=report.sections_chunked)
    session.commit()
    logger.info(
        "chunks_built",
        sections=report.sections_chunked,
        chunks=report.chunks_written,
        max_tokens=report.max_tokens_seen,
    )
    return report


def _populate_tsv(session: Session) -> None:
    """Fill the English tsvector for any chunk that has none.

    The heading is indexed along with the body, minus the ``passage:`` marker,
    which is an instruction to the embedding model and not a word anyone will
    ever search for. Hindi is deferred: PostgreSQL 16 ships no ``hindi``
    configuration and ``simple`` would index Devanagari without stemming.
    """
    session.execute(
        text(
            "UPDATE kb_chunks SET tsv = to_tsvector('english', "
            "regexp_replace(heading_prefix, '^passage: ', '') || ' ' || text) "
            "WHERE tsv IS NULL"
        )
    )


# --- pass 3: embeddings -----------------------------------------------------


def embed_chunks(
    settings: Settings, session: Session, *, batch_size: int | None = None
) -> EmbedReport:
    """Embed every chunk that has no vector, then rebuild the HNSW index once.

    Resumable by construction: the work queue is ``embedding IS NULL``, so an
    interrupted run picks up where it stopped and a completed run is a no-op.
    """
    pending = session.execute(
        select(func.count()).select_from(KbChunk).where(KbChunk.embedding.is_(None))
    ).scalar_one()
    report = EmbedReport(pending_at_start=pending)
    if pending == 0:
        if not vector_index_exists(session):
            _create_vector_index(session)
            session.commit()
            report.index_rebuilt = True
        return report

    _drop_vector_index(session)
    session.commit()

    size = batch_size or settings.EMBED_BATCH_SIZE
    while True:
        batch = session.execute(
            select(KbChunk.id, KbChunk.heading_prefix, KbChunk.text)
            .where(KbChunk.embedding.is_(None))
            .order_by(KbChunk.id)
            .limit(size)
        ).all()
        if not batch:
            break
        vectors = embed_passages(settings, [f"{prefix}{body}" for _, prefix, body in batch])
        session.execute(
            text("UPDATE kb_chunks SET embedding = :vec WHERE id = :id").bindparams(),
            [
                {"id": row[0], "vec": str(vector)}
                for row, vector in zip(batch, vectors, strict=True)
            ],
        )
        session.commit()
        report.embedded += len(batch)
        logger.info("embed_progress", done=report.embedded, of=pending)

    _create_vector_index(session)
    _record_run(session, command="embed", slug=None, sections=report.embedded)
    session.commit()
    report.index_rebuilt = True
    return report


def vector_index_exists(session: Session) -> bool:
    """True when the HNSW index is present (it is dropped during a bulk embed)."""
    found = session.execute(
        text("SELECT to_regclass(:name)"), {"name": f"public.{VECTOR_INDEX}"}
    ).scalar_one()
    return found is not None


def _drop_vector_index(session: Session) -> None:
    session.execute(text(f"DROP INDEX IF EXISTS {VECTOR_INDEX}"))
    logger.info("vector_index_dropped", index=VECTOR_INDEX)


def _create_vector_index(session: Session) -> None:
    session.execute(
        text(
            f"CREATE INDEX IF NOT EXISTS {VECTOR_INDEX} ON kb_chunks "
            "USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )
    )
    logger.info("vector_index_built", index=VECTOR_INDEX)


# --- reporting --------------------------------------------------------------


def index_stats(session: Session) -> IndexStats:
    """One query set behind both the CLI and ``/v1/health``."""
    statutes, sections, in_force, chunks, embedded, links, max_tokens = session.execute(
        select(
            select(func.count()).select_from(Statute).scalar_subquery(),
            select(func.count()).select_from(StatuteSection).scalar_subquery(),
            select(func.count()).select_from(StatuteSection).where(INDEXABLE).scalar_subquery(),
            select(func.count()).select_from(KbChunk).scalar_subquery(),
            select(func.count())
            .select_from(KbChunk)
            .where(KbChunk.embedding.is_not(None))
            .scalar_subquery(),
            select(func.count()).select_from(StatuteLink).scalar_subquery(),
            select(func.max(KbChunk.token_count)).scalar_subquery(),
        )
    ).one()
    return IndexStats(
        statutes=statutes,
        sections=sections,
        sections_in_force=in_force,
        chunks=chunks,
        chunks_embedded=embedded,
        links=links,
        vector_index_ready=vector_index_exists(session),
        max_chunk_tokens=max_tokens,
    )


# --- helpers ----------------------------------------------------------------


def _scope(stmt: Select[Any], slug: str | None) -> Select[Any]:
    """Restrict a section-level query to one Act."""
    if slug is None:
        return stmt
    return stmt.where(StatuteSection.statute_id.in_(select(Statute.id).where(Statute.slug == slug)))


def _scope_delete(stmt: Delete, slug: str | None) -> Delete:
    """Restrict a chunk deletion to one Act."""
    if slug is None:
        return stmt
    return stmt.where(KbChunk.statute_id.in_(select(Statute.id).where(Statute.slug == slug)))


def _record_run(
    session: Session,
    *,
    command: str,
    slug: str | None,
    sections: int,
    warnings: list[dict[str, str]] | None = None,
) -> None:
    session.add(
        IngestRun(
            source_portal=PORTAL,
            statute_slug=slug,
            command=command,
            finished_at=dt.datetime.now(tz=dt.UTC),
            sections_written=sections,
            warnings=warnings or [],
            errors=[],
            status="succeeded",
        )
    )
    session.flush()
