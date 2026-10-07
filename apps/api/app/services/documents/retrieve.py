"""Turning a stored document into prompt context — docs/adr/0005.

Indexing reuses the corpus chunker's limits and ``passage:`` prefix and the
corpus embedding model, and selection reuses the corpus cross-encoder, so a
document passage and a statute passage are scored on the same scale. Nothing
here is a second retrieval system; it is the same one pointed at different
text.

Every function here is synchronous and CPU-bound. Callers run them off the
event loop.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.answer.pack import estimate_tokens
from app.services.documents.extract import Extracted, LocatorKind
from app.services.documents.store import DocumentChunk, StoredDocument
from app.services.kb.chunk import chunk_section
from app.services.kb.embedding import embed_passages, embed_query, token_counter

logger = get_logger(__name__)

# Whole documents up to this size go into the prompt intact — the only honest
# way to answer "summarise this". Larger ones contribute their best passages.
DOCUMENT_BUDGET_TOKENS = 6000
# How many passages a larger document contributes, at most.
DOCUMENT_TOP_N = 8
# Cosine pre-selection before the cross-encoder, mirroring RRF → rerank.
DOCUMENT_CANDIDATES = 24
EXCERPT_CHARS = 600
# Shorter paragraphs are joined to the next one (headings, numbering lines).
MIN_PARAGRAPH_CHARS = 40


def _note(locator_kind: LocatorKind, locator: int) -> str:
    return f"page {locator}" if locator_kind == "page" else f"paragraph {locator}"


# --- indexing ---------------------------------------------------------------


def build_chunks(
    settings: Settings, filename: str, extracted: Extracted
) -> list[tuple[int, str, str]]:
    """``(locator, text, embed_input)`` for every passage, in document order.

    PDF pages are chunked one page at a time, so a passage never straddles a
    page and its citation is exact. DOCX/TXT paragraphs are one passage each,
    for the same reason; only an oversized paragraph is split, and its pieces
    keep its number.
    """
    count = token_counter(settings)
    ceiling = settings.MAX_CHUNK_TOKENS
    out: list[tuple[int, str, str]] = []

    def emit(locator: int, text: str) -> None:
        for chunk in chunk_section(
            short_title=filename,
            marginal_note=_note(extracted.locator_kind, locator),
            text=text,
            count_tokens=count,
            max_tokens=ceiling,
        ):
            out.append((locator, chunk.text, chunk.embed_input))

    if extracted.locator_kind == "page":
        for segment in extracted.segments:
            emit(segment.locator, segment.text)
        return out

    # One passage per paragraph, so "¶ 3" really is paragraph 3. A very short
    # paragraph (a heading such as "RENTAL AGREEMENT") is carried into the
    # next one rather than standing alone as a passage with nothing in it.
    carried: tuple[int, str] | None = None
    for segment in extracted.segments:
        locator, text = segment.locator, segment.text
        if carried is not None:
            locator, text = carried[0], f"{carried[1]}\n{text}"
            carried = None
        if len(text) < MIN_PARAGRAPH_CHARS and segment is not extracted.segments[-1]:
            carried = (locator, text)
            continue
        emit(locator, text)
    return out


def embed_chunks(settings: Settings, chunks: list[tuple[int, str, str]]) -> list[DocumentChunk]:
    vectors = embed_passages(settings, [embed_input for _, _, embed_input in chunks])
    return [
        DocumentChunk(locator=locator, text=text, vector=np.asarray(vector, dtype=np.float32))
        for (locator, text, _), vector in zip(chunks, vectors, strict=True)
    ]


# --- selection --------------------------------------------------------------

# A document must not be able to close its own element or forge a statute
# block. Any tag-like opening of either name is defused before rendering.
_TAG_LIKE = re.compile(r"<\s*(/?)\s*(block|document)\b", re.IGNORECASE)


def neutralise(text: str) -> str:
    return _TAG_LIKE.sub(lambda m: f"‹{m.group(1)}{m.group(2)}", text)


def _attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


@dataclass(frozen=True)
class DocumentBlock:
    """One document passage exactly as the model sees it."""

    citation_id: str
    document_id: str
    filename: str
    locator_kind: LocatorKind
    locator: int
    text: str
    score: float | None = None
    order: int = 0

    def render(self) -> str:
        position = (
            f'page="{self.locator}"'
            if self.locator_kind == "page"
            else f'paragraph="{self.locator}"'
        )
        return (
            f'<document id="{self.citation_id}" source="{_attr(self.filename)}" {position}>\n'
            f"{neutralise(self.text)}\n"
            f"</document>"
        )

    @property
    def excerpt(self) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= EXCERPT_CHARS else f"{text[: EXCERPT_CHARS - 1]}…"


def citation_id(index: int, locator_kind: LocatorKind, locator: int) -> str:
    """``D1-p4`` or ``D2-para12``. ``index`` is the document's 1-based position."""
    return f"D{index}-{'p' if locator_kind == 'page' else 'para'}{locator}"


def _units(index: int, document: StoredDocument) -> list[DocumentBlock]:
    """Passages merged per locator: one block per page or paragraph group."""
    merged: dict[int, list[str]] = {}
    for chunk in document.chunks:
        merged.setdefault(chunk.locator, []).append(chunk.text)
    return [
        DocumentBlock(
            citation_id=citation_id(index, document.locator_kind, locator),
            document_id=document.id,
            filename=document.filename,
            locator_kind=document.locator_kind,
            locator=locator,
            text="\n".join(texts),
            order=position,
        )
        for position, (locator, texts) in enumerate(sorted(merged.items()))
    ]


def _cross_encode(settings: Settings, question: str, texts: Sequence[str]) -> list[float]:
    from torch.nn import Sigmoid

    from app.services.retrieval.rerank import get_reranker

    scores = get_reranker(settings).predict(
        [(question, text) for text in texts],
        batch_size=settings.EMBED_BATCH_SIZE,
        activation_fct=Sigmoid(),
        show_progress_bar=False,
    )
    return [float(score) for score in scores]


def select_blocks(
    settings: Settings, question: str, documents: list[StoredDocument]
) -> list[DocumentBlock]:
    """The passages of each attached document that go into the prompt."""
    blocks: list[DocumentBlock] = []
    query: np.ndarray | None = None
    for index, document in enumerate(documents, start=1):
        units = _units(index, document)
        if sum(estimate_tokens(unit.render()) for unit in units) <= DOCUMENT_BUDGET_TOKENS:
            blocks.extend(units)
            continue

        if query is None:
            query = np.asarray(embed_query(settings, question), dtype=np.float32)
        best: dict[int, float] = {}
        for chunk in document.chunks:
            similarity = float(chunk.vector @ query)
            best[chunk.locator] = max(best.get(chunk.locator, -1.0), similarity)
        shortlist = sorted(units, key=lambda u: -best.get(u.locator, -1.0))
        shortlist = shortlist[:DOCUMENT_CANDIDATES]
        scores = _cross_encode(settings, question, [unit.text for unit in shortlist])
        ranked = sorted(zip(shortlist, scores, strict=True), key=lambda pair: -pair[1])

        # The opening passage is always included: it is where a document says
        # what it is and who the parties are.
        chosen = {units[0].locator: units[0]}
        for unit, _score in ranked:
            if len(chosen) >= DOCUMENT_TOP_N:
                break
            chosen.setdefault(unit.locator, unit)
        score_of = {unit.locator: score for unit, score in ranked}
        blocks.extend(
            replace(unit, score=score_of.get(unit.locator))
            for unit in sorted(chosen.values(), key=lambda u: u.order)
        )
    logger.info("document_context_selected", documents=len(documents), blocks=len(blocks))
    return blocks


def render_documents(blocks: list[DocumentBlock]) -> str:
    return "\n\n".join(block.render() for block in blocks)


__all__ = [
    "DocumentBlock",
    "build_chunks",
    "citation_id",
    "embed_chunks",
    "neutralise",
    "render_documents",
    "select_blocks",
]
