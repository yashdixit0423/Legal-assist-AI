"""Turning India Code's HTML fragments into storable section text.

The portal's ``section_page_note`` is a small HTML fragment: indentation spans,
``<br>`` line breaks, ``<i>`` emphasis, and ``<sup>N</sup>`` footnote markers.
The original fragment is kept as ``text_raw`` so a parsing fix can be replayed
without re-fetching (spec §04); ``text_verbatim`` is the readable text.

Footnote markers are preserved inline as ``[N]`` rather than dropped. They are
part of how a printed statute reads, and they are what ties a clause to the
amendment that produced it.

Uses the standard library rather than lxml: these are short fragments, and the
API path has no PDF to parse, so the heavy extraction dependencies stay out of
this module.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.services.kb.adapters.indiacode_api import RawSection

BLOCK_TAGS = {"p", "div", "br", "tr", "li"}

# India Code keeps repealed provisions as items in their own right, so the
# numbering stays continuous. Two signals mark them, both observed across the
# six Acts: the marginal note is literally "Repealed." (sometimes "Repealed.."),
# and the body is the old marginal note in square brackets followed by the
# repealing provision.
#
# Both signals vary in punctuation across Acts, and the variants matter: the
# Contract Act writes the note as "Repealed." while the Transfer of Property Act
# writes "[Repealed.]." and puts a footnote marker before the bracketed old
# note — "[1][Decree of foreclosure suit.] Rep. by the Code of Civil Procedure".
OMITTED_NOTES = {"repealed", "omitted"}
LEADING_MARKERS = re.compile(r"^(?:\s*\[\d{1,2}\])+\s*")
OMITTED_BODY = re.compile(r"^\[[^\]]*\]\s*(?:Rep\.|Repealed|Omitted)\b", re.IGNORECASE)


class _Fragment(HTMLParser):
    """Flatten an HTML fragment to text, keeping footnote markers as [N]."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._in_sup = False

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag == "sup":
            self._in_sup = True
            self._parts.append("[")
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "sup":
            self._in_sup = False
            self._parts.append("]")
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(fragment: str) -> str:
    """Flatten one HTML fragment to normalised plain text."""
    if not fragment:
        return ""
    parser = _Fragment()
    parser.feed(fragment)
    parser.close()
    text = html.unescape(parser.text)
    text = text.replace("\xa0", " ")
    # Collapse runs of spaces and tabs, but keep paragraph structure.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # An empty footnote marker is an artefact of an empty <sup></sup>.
    text = text.replace("[]", "")
    return text.strip()


@dataclass(frozen=True)
class Footnote:
    """One footnote, as printed beneath the section."""

    marker: str
    text: str


FOOTNOTE_SPLIT = re.compile(r"(?m)^\s*\[?(\d{1,2})\]?\s*\.\s*")


def parse_footnotes(fragment: str) -> list[Footnote]:
    """Split the footnote block into numbered notes."""
    text = html_to_text(fragment)
    if not text:
        return []
    pieces = FOOTNOTE_SPLIT.split(text)
    if len(pieces) < 3:
        return [Footnote(marker="", text=text)]
    notes: list[Footnote] = []
    # split() yields [preamble, marker, body, marker, body, ...]
    for marker, body in zip(pieces[1::2], pieces[2::2], strict=False):
        cleaned = body.strip()
        if cleaned:
            notes.append(Footnote(marker=marker, text=cleaned))
    return notes


AMENDMENT_HINT = re.compile(
    r"\b(?:Ins\.|Subs\.|Rep\.|Omitted|Substituted|Inserted|w\.e\.f\.|"
    r"vide\b|Act\s+\d+\s+of\s+\d{4})",
    re.IGNORECASE,
)


def amendment_note(footnotes: list[Footnote]) -> str | None:
    """Join the footnotes that describe amendments, in order."""
    relevant = [note.text for note in footnotes if AMENDMENT_HINT.search(note.text)]
    return "\n".join(relevant) if relevant else None


@dataclass(frozen=True)
class ParsedSection:
    """A section ready to be written to ``statute_sections``."""

    section_no: str
    marginal_note: str | None
    text_verbatim: str
    text_raw: str
    footnotes: list[Footnote]
    amendment_note: str | None
    is_omitted: bool
    order_idx: int


def looks_omitted(marginal_note: str, text: str) -> bool:
    """True when this item is a repealed provision rather than live law."""
    note = marginal_note.strip().strip("[].").strip().lower()
    if note in OMITTED_NOTES:
        return True
    return bool(OMITTED_BODY.match(LEADING_MARKERS.sub("", text)))


def parse_section(raw: RawSection, *, order_idx: int) -> ParsedSection:
    """Convert one portal item into a storable section."""
    body = html_to_text(raw.body_html)
    marginal = html_to_text(raw.title) or None
    footnotes = parse_footnotes(raw.footnote_html)
    return ParsedSection(
        section_no=raw.section_number.strip().rstrip("."),
        marginal_note=marginal,
        text_verbatim=body,
        text_raw=raw.body_html,
        footnotes=footnotes,
        amendment_note=amendment_note(footnotes),
        is_omitted=raw.is_repealed or looks_omitted(marginal or "", body),
        order_idx=order_idx,
    )


# --- sub-section structure, used by the Stage 3 chunker --------------------

SUBSECTION = re.compile(r"(?m)(?=^\s*\(\s*(\d{1,2}[A-Za-z]?)\s*\))")
PROVISO = re.compile(r"(?m)(?=\bProvided\b)")
LABELLED = re.compile(r"(?m)(?=^\s*(?:Explanation|Illustrations?|Exception)\b)")


@dataclass(frozen=True)
class Segment:
    """A sub-section, proviso, Explanation or Illustration within a section."""

    label: str
    text: str


def segment_section(text: str) -> list[Segment]:
    """Split a section on its own internal boundaries, in document order.

    Used when a section is too long to embed whole: the chunker splits here and
    carries the parent heading onto each piece, so a proviso is never read
    without the provision it qualifies.
    """
    if not text.strip():
        return []
    boundaries = {0}
    for pattern in (SUBSECTION, LABELLED, PROVISO):
        boundaries.update(match.start() for match in pattern.finditer(text))
    ordered = sorted(boundaries)
    segments: list[Segment] = []
    for start, end in zip(ordered, [*ordered[1:], len(text)], strict=False):
        piece = text[start:end].strip()
        if not piece:
            continue
        segments.append(Segment(label=_label_for(piece), text=piece))
    return segments


def _label_for(piece: str) -> str:
    match = re.match(r"\s*\(\s*(\d{1,2}[A-Za-z]?)\s*\)", piece)
    if match:
        return f"({match.group(1)})"
    for word in ("Explanation", "Illustrations", "Illustration", "Exception", "Provided"):
        if piece.lstrip().startswith(word):
            return word
    return "body"
