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

# A bracketed group, and the section references inside it.
#
# The first version of this matched only ``\[S(\d+)\]`` — an id with the closing
# bracket immediately after the digits. A live run showed why that is not
# enough: gpt-4.1-mini wrote ``[S19(c)]`` to point at a clause, and
# ``[S18(1)(d), S1107]`` to cite two provisions at once. Neither form matched,
# so ``[S19(c)]`` was **not seen as a citation at all** and only the trailing
# id of the compound form was checked. A fabricated ``[S9999(c)]`` would have
# passed validation in silence — which is the precise failure this module
# exists to make impossible.
#
# So: find every bracketed group, then every ``S<digits>`` inside it. A model
# is free to write a sub-clause pointer or several ids in one bracket; what it
# is not free to do is have any of them go unchecked.
BRACKETED = re.compile(r"\[([^\[\]]*)\]")
SECTION_REF = re.compile(r"\bS(\d{1,12})\b")

# Kept for the streaming guard, which needs to know when a citation has been
# *closed* — an unterminated "[S10" is the start of a valid id as often as an
# invalid one.
CITATION = re.compile(r"\[[^\[\]]*\bS(\d{1,12})\b[^\[\]]*\]")

# User-document passages (docs/adr/0005): ``D<n>-p<page>`` for a PDF page,
# ``D<n>-para<k>`` for a DOCX/TXT paragraph. Same bracket rule as sections.
DOCUMENT_REF = re.compile(r"\bD(\d{1,2})-(p|para)(\d{1,6})\b")


@dataclass(frozen=True)
class CitationCheck:
    """The verdict on one generated answer."""

    cited: frozenset[int]
    allowed: frozenset[int]
    invalid: frozenset[int]
    ok: bool
    reason: str | None = None
    cited_documents: frozenset[str] = frozenset()
    invalid_documents: frozenset[str] = frozenset()

    @property
    def violation(self) -> bool:
        """True when the answer cited something that was not in the prompt."""
        return bool(self.invalid or self.invalid_documents)


def extract_citations(answer: str) -> frozenset[int]:
    """Every section id the answer cites, in any bracketed form.

    ``[S1046]``, ``[S19(c)]`` and ``[S18(1)(d), S1107]`` all count. India
    Code's own footnote markers — ``[2]``, ``[State Government]`` — contain no
    ``S<digits>`` and are ignored, which is why the scheme uses a letter prefix
    in the first place.

    A bare ``S1046`` with no brackets is deliberately *not* counted: the prompt
    asks for brackets, and an answer that uses only bare forms then reads as
    uncited and is regenerated. That fails closed.
    """
    cited: set[int] = set()
    for group in BRACKETED.finditer(answer):
        cited.update(int(ref.group(1)) for ref in SECTION_REF.finditer(group.group(1)))
    return frozenset(cited)


def extract_document_citations(answer: str) -> frozenset[str]:
    """Every document passage id the answer cites, normalised to ``D1-p4``."""
    cited: set[str] = set()
    for group in BRACKETED.finditer(answer):
        cited.update(
            f"D{int(ref.group(1))}-{ref.group(2)}{int(ref.group(3))}"
            for ref in DOCUMENT_REF.finditer(group.group(1))
        )
    return frozenset(cited)


def validate_citations(
    answer: str,
    allowed_section_ids: frozenset[int] | set[int],
    allowed_document_ids: frozenset[str] | None = None,
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
    # ``None`` means no documents were in play (Ask, or Chat without
    # attachments): document ids are then not looked for at all, exactly as
    # before documents existed. An empty set means "documents were in play and
    # none may be cited", which is a different rule.
    docs_cited: frozenset[str] = frozenset()
    docs_invalid: frozenset[str] = frozenset()
    if allowed_document_ids is not None:
        docs_cited = extract_document_citations(answer)
        docs_invalid = docs_cited - allowed_document_ids
    if invalid:
        return CitationCheck(
            cited=cited,
            allowed=allowed,
            invalid=invalid,
            ok=False,
            reason="cited_sections_not_in_context",
            cited_documents=docs_cited,
            invalid_documents=docs_invalid,
        )
    if docs_invalid:
        return CitationCheck(
            cited=cited,
            allowed=allowed,
            invalid=invalid,
            ok=False,
            reason="cited_documents_not_in_context",
            cited_documents=docs_cited,
            invalid_documents=docs_invalid,
        )
    if not cited and not docs_cited:
        return CitationCheck(
            cited=cited,
            allowed=allowed,
            invalid=invalid,
            ok=False,
            reason="no_citations",
            cited_documents=docs_cited,
            invalid_documents=docs_invalid,
        )
    return CitationCheck(
        cited=cited,
        allowed=allowed,
        invalid=invalid,
        ok=True,
        cited_documents=docs_cited,
        invalid_documents=docs_invalid,
    )
