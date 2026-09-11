"""Internal cross-references, extracted by regex and resolved to section ids.

Deterministic, no LLM. A statute cites itself constantly — "subject to the
provisions of section 23", "notwithstanding anything in sub-section (2) of
section 14" — and those edges are what let a later stage pull in the proviso
that guts the rule the retriever actually matched.

Two things are deliberate:

* **References that do not resolve are recorded, never dropped.** A reference
  to a Chapter cannot be resolved today because ``statute_parts`` is empty, and
  a reference into an Act outside our six cannot be resolved at all. Both are
  returned as :class:`Unresolved` and end up in the ``ingest_runs`` row, so the
  number is visible rather than inferred from a suspiciously small edge count.
* **Ranges are expanded, but bounded.** "sections 3 to 9" is seven real edges;
  "sections 3 to 300" is a drafting flourish about an Act as a whole, and
  expanding it would bury the graph in noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "section 23", "sections 23, 24 and 25", "ss. 3 to 9", "section 2A".
# The trailing "of the <Act>, <year>" group is what distinguishes an internal
# reference from a reference into another statute.
_NUMBER = r"\d{1,3}(?:-?[A-Z]{1,2})?"
SECTION_REF = re.compile(
    r"\b(?:sections?|ss?\.)\s*"
    rf"(?P<numbers>{_NUMBER}(?:\s*(?:,|and|or|to|&)\s*{_NUMBER})*)"
    r"(?P<of_act>\s+of\s+the\s+(?P<act>[A-Z][A-Za-z'()\- ]{3,70},?\s*"
    r"(?P<year>1[89]\d{2}|20\d{2})))?",
    re.IGNORECASE,
)
RANGE_JOIN = re.compile(r"\s*to\s*", re.IGNORECASE)
PART_REF = re.compile(r"\b(?P<kind>Chapter|Part)\s+(?P<number>[IVXLC]{1,6}|\d{1,2})\b")

# Beyond this a range is rhetoric about the Act, not a list of provisions.
MAX_RANGE = 30


@dataclass(frozen=True)
class Link:
    """A resolved edge, ready to be upserted into ``statute_links``."""

    from_section_id: int
    to_section_id: int
    relation: str
    raw_text: str


@dataclass(frozen=True)
class Unresolved:
    """A reference we found and could not turn into a section id."""

    from_section_id: int
    kind: str
    raw_text: str
    detail: str


@dataclass(frozen=True)
class SectionRow:
    """The minimum a section contributes to extraction."""

    id: int
    statute_id: int
    section_no: str
    text: str


def normalise_act_title(title: str) -> str:
    """Fold an Act title to a comparable key: lowercase, no commas, no 'the'."""
    folded = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    folded = re.sub(r"\bthe\b", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def normalise_section_no(number: str) -> str:
    """``21-A``, ``21 A`` and ``21A`` are the same provision."""
    return re.sub(r"[^0-9a-z]", "", number.lower())


def extract_links(
    section: SectionRow,
    *,
    sections_by_statute: dict[int, dict[str, int]],
    statute_ids_by_title: dict[str, int],
) -> tuple[list[Link], list[Unresolved]]:
    """Find every reference in one section's text and try to resolve it.

    ``sections_by_statute`` maps statute id to normalised section number to
    section id; ``statute_ids_by_title`` maps a normalised Act title to its id.
    Both are built once for the whole run — this function does no I/O.
    """
    links: dict[tuple[int, str], Link] = {}
    unresolved: list[Unresolved] = []

    for match in SECTION_REF.finditer(section.text):
        raw = match.group(0).strip()
        target_statute = section.statute_id
        if match.group("act"):
            key = normalise_act_title(match.group("act"))
            found = _lookup_act(key, statute_ids_by_title)
            if found is None:
                unresolved.append(
                    Unresolved(
                        from_section_id=section.id,
                        kind="act_not_in_corpus",
                        raw_text=raw[:200],
                        detail=match.group("act").strip(),
                    )
                )
                continue
            target_statute = found

        known = sections_by_statute.get(target_statute, {})
        for number in _expand(match.group("numbers")):
            target_id = known.get(normalise_section_no(number))
            if target_id is None:
                unresolved.append(
                    Unresolved(
                        from_section_id=section.id,
                        kind="section_not_found",
                        raw_text=raw[:200],
                        detail=f"section {number}",
                    )
                )
                continue
            if target_id == section.id:
                continue  # self-reference; the schema forbids the edge anyway
            links[(target_id, "refers_to")] = Link(
                from_section_id=section.id,
                to_section_id=target_id,
                relation="refers_to",
                raw_text=raw[:200],
            )

    for match in PART_REF.finditer(section.text):
        unresolved.append(
            Unresolved(
                from_section_id=section.id,
                kind="no_part_hierarchy",
                raw_text=match.group(0),
                detail=f"{match.group('kind')} {match.group('number')}",
            )
        )

    return list(links.values()), unresolved


def _lookup_act(key: str, statute_ids_by_title: dict[str, int]) -> int | None:
    """Exact title match first, then the longest title contained in the phrase.

    The phrase captured from the text is often longer than the short title
    ("provisions of the Indian Contract Act, 1872 relating to"), so a
    containment fallback resolves what an equality test would not.
    """
    if key in statute_ids_by_title:
        return statute_ids_by_title[key]
    candidates = [title for title in statute_ids_by_title if title and title in key]
    if not candidates:
        return None
    return statute_ids_by_title[max(candidates, key=len)]


def _expand(numbers: str) -> list[str]:
    """Turn a matched number list into individual section numbers."""
    out: list[str] = []
    for part in re.split(r"\s*(?:,|and|or|&)\s*", numbers, flags=re.IGNORECASE):
        piece = part.strip()
        if not piece:
            continue
        bounds = RANGE_JOIN.split(piece)
        if len(bounds) == 2 and all(b.strip().isdigit() for b in bounds):
            low, high = int(bounds[0]), int(bounds[1])
            if 0 < high - low < MAX_RANGE:
                out.extend(str(n) for n in range(low, high + 1))
            else:
                out.extend([bounds[0].strip(), bounds[1].strip()])
            continue
        out.extend(b.strip() for b in bounds if b.strip())
    return out
