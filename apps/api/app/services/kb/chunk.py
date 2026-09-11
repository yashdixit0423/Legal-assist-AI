"""Turning a section into the units that get embedded.

One chunk per section wherever the section fits. Longer sections are split on
their own internal boundaries — sub-sections, provisos, Explanations,
Illustrations — and every split carries the parent section heading, so a
proviso is never retrieved without the provision it qualifies.

Two rules here are load-bearing and are what the tests in
``tests/unit/test_chunker.py`` exist to protect:

1. **The ``passage:`` prefix is applied here**, at index time, in the form the
   brief specifies: ``passage: <act short title> — <marginal note>. <text>``.
   Questions get ``query:`` at query time instead. An e5 model given the wrong
   prefix returns worse neighbours and no error.
2. **No chunk exceeds the ceiling**, counted with the model's own tokenizer
   including the special tokens, over the *whole* embedded string — prefix
   included. A word count would be wrong by a third on legal English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import PASSAGE_PREFIX
from app.services.kb.embedding import TokenCounter
from app.services.kb.parse import segment_section

# Sentence-ish boundaries, used only when a single sub-section is itself over
# the ceiling. The Stamp Act's duty schedules and the Registration Act's list
# of registrable documents are single provisions of 20-30k characters: they
# have no sub-section structure to split on, so something has to give, and a
# break at a full stop or semicolon loses less than a break mid-clause.
SENTENCE_BREAK = re.compile(r"(?<=[.;:])\s+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit, ready to be written to ``kb_chunks``."""

    chunk_idx: int
    heading_prefix: str
    text: str
    token_count: int

    @property
    def embed_input(self) -> str:
        """Exactly the string that gets embedded."""
        return f"{self.heading_prefix}{self.text}"


def build_heading_prefix(short_title: str, marginal_note: str | None) -> str:
    """``passage: <act short title> — <marginal note>. ``

    Identical for every chunk of a section, which is what makes the splits
    readable in isolation. The trailing space separates it from the text
    without the caller having to remember to add one.
    """
    note = (marginal_note or "").strip().rstrip(".")
    if note:
        return f"{PASSAGE_PREFIX}{short_title.strip()} — {note}. "
    return f"{PASSAGE_PREFIX}{short_title.strip()}. "


def chunk_section(
    *,
    short_title: str,
    marginal_note: str | None,
    text: str,
    count_tokens: TokenCounter,
    max_tokens: int,
) -> list[Chunk]:
    """Split one section into chunks that each fit under ``max_tokens``."""
    prefix = build_heading_prefix(short_title, marginal_note)
    body = text.strip()
    if not body:
        return []

    if count_tokens(f"{prefix}{body}") <= max_tokens:
        return [
            Chunk(
                chunk_idx=0,
                heading_prefix=prefix,
                text=body,
                token_count=count_tokens(f"{prefix}{body}"),
            )
        ]

    pieces = [segment.text for segment in segment_section(body)] or [body]
    packed = _pack(pieces, prefix=prefix, max_tokens=max_tokens, count=count_tokens, joiner="\n")
    return [
        Chunk(
            chunk_idx=index,
            heading_prefix=prefix,
            text=piece,
            token_count=count_tokens(f"{prefix}{piece}"),
        )
        for index, piece in enumerate(packed)
    ]


def _pack(
    pieces: list[str], *, prefix: str, max_tokens: int, count: TokenCounter, joiner: str
) -> list[str]:
    """Greedily join adjacent pieces, splitting any piece that is too big alone.

    Joining matters: a section of fifteen one-line sub-sections would otherwise
    become fifteen chunks with almost no context in each, and the reranker
    would have to choose between them on nothing.
    """
    out: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{joiner}{piece}".strip() if current else piece.strip()
        if not candidate:
            continue
        if count(f"{prefix}{candidate}") <= max_tokens:
            current = candidate
            continue
        if current:
            out.append(current)
            current = ""
        if count(f"{prefix}{piece}") <= max_tokens:
            current = piece.strip()
            continue
        parts = _split_oversized(piece.strip(), prefix=prefix, max_tokens=max_tokens, count=count)
        out.extend(parts[:-1])
        current = parts[-1]
    if current:
        out.append(current)
    return out


def _split_oversized(piece: str, *, prefix: str, max_tokens: int, count: TokenCounter) -> list[str]:
    """Break one over-long piece at sentence boundaries, then at whitespace."""
    sentences = [s for s in SENTENCE_BREAK.split(piece) if s.strip()]
    if len(sentences) > 1:
        return _pack(sentences, prefix=prefix, max_tokens=max_tokens, count=count, joiner=" ")

    words = piece.split()
    if len(words) <= 1:
        # A single "word" over the ceiling is not real legal text; keep it
        # rather than lose the provision, and let the model truncate it.
        return [piece]
    return _pack(words, prefix=prefix, max_tokens=max_tokens, count=count, joiner=" ")
