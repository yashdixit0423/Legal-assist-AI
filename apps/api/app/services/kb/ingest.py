"""Fetch and parse orchestration.

Two entry points, both callable from the CLI or a test:

* :func:`fetch_act` talks to the portal and archives what it gets;
* :func:`parse_act` reads the archive, verifies it and writes the rows.

Both are idempotent. Re-fetching an unchanged Act reuses the archive; re-parsing
upserts by ``(statute_id, section_no)`` so nothing is duplicated.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import IngestRun, Statute, StatuteSection
from app.services.kb import parse as parser
from app.services.kb.adapters import indiacode_api
from app.services.kb.fetch import PoliteClient, archive_json, read_archive
from app.services.kb.manifest import ActEntry
from app.services.kb.section_numbers import section_no_sort
from app.services.kb.verify import VerificationReport, verify_sections

logger = get_logger(__name__)

ARCHIVE_NAME = "indiacode.json"
PORTAL = "indiacode"


@dataclass
class FetchResult:
    slug: str
    sha256: str
    path: str
    items: int
    from_cache: bool
    run_id: int | None


@dataclass
class ParseResult:
    slug: str
    sections_written: int
    report: VerificationReport
    run_id: int | None


def _start_run(session: Session, *, slug: str, command: str) -> IngestRun:
    run = IngestRun(
        source_portal=PORTAL, statute_slug=slug, command=command, status="running"
    )
    session.add(run)
    session.flush()
    return run


def _finish_run(
    session: Session,
    run: IngestRun,
    *,
    status: str,
    docs: int = 0,
    sections: int = 0,
    warnings: list[dict[str, str]] | None = None,
    errors: list[dict[str, str]] | None = None,
) -> None:
    run.status = status
    run.finished_at = dt.datetime.now(tz=dt.UTC)
    run.docs_fetched = docs
    run.sections_written = sections
    run.warnings = warnings or []
    run.errors = errors or []
    session.flush()


def fetch_act(
    settings: Settings,
    entry: ActEntry,
    *,
    session: Session | None = None,
    refresh: bool = False,
) -> FetchResult:
    """Archive one Act's API payload, recording the run when a session is given."""
    run = _start_run(session, slug=entry.slug, command="fetch") if session else None
    try:
        with PoliteClient(settings, base_url=indiacode_api.BASE_URL) as client:
            payload = indiacode_api.fetch_act_payload(
                client, act_id=entry.act_id, handle=entry.handle
            )
            robots_warnings = [
                {"kind": "robots", "detail": w} for w in client.stats.warnings
            ]
        archived = archive_json(
            settings,
            slug=entry.slug,
            name=ARCHIVE_NAME,
            payload=payload,
            refresh=refresh,
        )
    except Exception as exc:
        if session and run:
            _finish_run(
                session,
                run,
                status="failed",
                errors=[{"kind": type(exc).__name__, "detail": str(exc)[:400]}],
            )
            session.commit()
        raise

    if session and run:
        _finish_run(
            session, run, status="succeeded", docs=1, warnings=robots_warnings
        )
        session.commit()

    return FetchResult(
        slug=entry.slug,
        sha256=archived.sha256,
        path=str(archived.path),
        items=len(payload["items"]),
        from_cache=archived.from_cache,
        run_id=run.id if run else None,
    )


def _upsert_statute(
    session: Session, entry: ActEntry, act: indiacode_api.RawAct, *, sha256: str
) -> Statute:
    today = dt.datetime.now(tz=dt.UTC).date()
    values = {
        "slug": entry.slug,
        "short_title": entry.short_title,
        "long_title": act.title or entry.short_title,
        "act_number": act.act_number or entry.act_number,
        "year": act.year or entry.year,
        "enacted_on": act.enacted_on,
        "jurisdiction": entry.jurisdiction,
        "level": entry.level,
        "ministry": act.ministry or entry.ministry,
        "source_portal": PORTAL,
        "source_url": entry.source_url,
        "source_sha256": sha256,
        "as_of_date": today,
        "is_repealed": act.is_repealed,
    }
    stmt = (
        insert(Statute)
        .values(**values)
        .on_conflict_do_update(index_elements=[Statute.slug], set_=values)
        .returning(Statute.id)
    )
    statute_id = session.execute(stmt).scalar_one()
    statute = session.get(Statute, statute_id)
    assert statute is not None  # noqa: S101 — just returned by the upsert
    return statute


def parse_act(
    settings: Settings,
    entry: ActEntry,
    session: Session,
    *,
    strict: bool = True,
) -> ParseResult:
    """Parse an archived Act into the database, verifying before it writes."""
    run = _start_run(session, slug=entry.slug, command="parse")
    try:
        payload = read_archive(settings, slug=entry.slug, name=ARCHIVE_NAME)
        act, raw_sections = indiacode_api.parse_payload(payload)
        parsed = [
            parser.parse_section(raw, order_idx=index)
            for index, raw in enumerate(raw_sections)
        ]
        report = verify_sections(
            entry.slug, parsed, expected=entry.expected_sections
        )
        if strict:
            report.raise_if_failed()

        from app.services.kb.fetch import sha256_bytes

        sha = sha256_bytes(
            (settings.CORPUS_ARCHIVE_DIR / entry.slug / ARCHIVE_NAME).read_bytes()
        )
        statute = _upsert_statute(session, entry, act, sha256=sha)

        as_of = statute.as_of_date
        for section in parsed:
            values = {
                "statute_id": statute.id,
                "section_no": section.section_no,
                "section_no_sort": section_no_sort(section.section_no),
                "marginal_note": section.marginal_note,
                "text_verbatim": section.text_verbatim,
                "text_raw": section.text_raw,
                "footnotes": [
                    {"marker": note.marker, "text": note.text}
                    for note in section.footnotes
                ],
                "amendment_note": section.amendment_note,
                "commenced_on": act.commenced_on,
                "as_of_date": as_of,
                "is_omitted": section.is_omitted,
                "order_idx": section.order_idx,
            }
            session.execute(
                insert(StatuteSection)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_statute_sections_no",
                    set_={k: v for k, v in values.items() if k != "statute_id"},
                )
            )

        statute.section_count = sum(1 for s in parsed if not s.is_omitted)
        _finish_run(
            session,
            run,
            status="succeeded" if report.ok else "partial",
            docs=1,
            sections=len(parsed),
            warnings=report.warnings,
            errors=report.errors,
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        run = _start_run(session, slug=entry.slug, command="parse")
        _finish_run(
            session,
            run,
            status="failed",
            errors=[{"kind": type(exc).__name__, "detail": str(exc)[:400]}],
        )
        session.commit()
        raise

    logger.info("parsed_act", slug=entry.slug, sections=len(parsed))
    return ParseResult(
        slug=entry.slug,
        sections_written=len(parsed),
        report=report,
        run_id=run.id,
    )


def statute_section_numbers(session: Session, slug: str) -> list[str]:
    """Section numbers for one Act in citation order (used by the fixture test)."""
    return list(
        session.execute(
            select(StatuteSection.section_no)
            .join(Statute)
            .where(Statute.slug == slug)
            .order_by(StatuteSection.section_no_sort)
        ).scalars()
    )
