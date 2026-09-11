"""The citation validator — spec §05 step 8.

A fabricated section number is the most damaging error a legal product can
make, and it is the one hallucination class that can be caught deterministically:
we know exactly which sections went into the prompt, so anything else the model
cites is provably invented.

Citation ids are written ``[S<section_id>]``. The bracket-plus-letter form is
deliberate. India Code's text carries footnote markers as bare ``[1]``,
``[2][State Government]`` and so on, and those markers are inside the corpus
blocks we hand the model — a bare-integer citation scheme would be
indistinguishable from them, and the validator would spend its life arguing
with the statute's own footnotes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CITATION = re.compile(r"\[S(\d{1,12})\]")


@dataclass(frozen=True)
class CitationCheck:
    """The verdict on one generated answer."""

    cited: frozenset[int]
    allowed: frozenset[int]
    invalid: frozenset[int]
    ok: bool
    reason: str | None = None

    @property
    def violation(self) -> bool:
        """True when the answer cited something that was not in the prompt."""
        return bool(self.invalid)


def extract_citations(answer: str) -> frozenset[int]:
    """Every section id the answer cites, in ``[S123]`` form."""
    return frozenset(int(match.group(1)) for match in CITATION.finditer(answer))


def validate_citations(
    answer: str, allowed_section_ids: frozenset[int] | set[int]
) -> CitationCheck:
    """Check an answer's citations against the sections actually packed.

    Two ways to fail, and both are failures:

    * citing a section that was not in the prompt — fabrication;
    * citing nothing at all — an assertion about the law with no provision
      behind it, which is exactly the output this product exists not to give.
    """
    allowed = frozenset(allowed_section_ids)
    cited = extract_citations(answer)
    invalid = cited - allowed
    if invalid:
        return CitationCheck(
            cited=cited,
            allowed=allowed,
            invalid=invalid,
            ok=False,
            reason="cited_sections_not_in_context",
        )
    if not cited:
        return CitationCheck(
            cited=cited, allowed=allowed, invalid=invalid, ok=False, reason="no_citations"
        )
    return CitationCheck(cited=cited, allowed=allowed, invalid=invalid, ok=True)
