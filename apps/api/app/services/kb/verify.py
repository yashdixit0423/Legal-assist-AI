"""Parser guardrails (spec §04).

Everything downstream inherits the segmentation, so a parser that silently
merges section 14 into section 13 produces a citation pointing at the wrong law.
These checks fail the ingest rather than write bad rows.

A gap in the numbering is not automatically a bug — the Contract Act genuinely
has nothing between 75 and 124, because the Sale of Goods provisions were
repealed in 1930 — so gaps are reported as warnings and only an *implausible*
run of them is an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.errors import IngestVerificationError
from app.services.kb.parse import ParsedSection
from app.services.kb.section_numbers import SectionNumberError, section_no_sort

MIN_PLAUSIBLE_CHARS = 40
MAX_PLAUSIBLE_CHARS = 12_000
# A single repeal block can be long; two hundred missing numbers is a parse failure.
MAX_GAP = 200


@dataclass
class VerificationReport:
    """The per-run warning report. ``errors`` being non-empty fails the run."""

    slug: str
    sections: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def warn(self, kind: str, detail: str) -> None:
        self.warnings.append({"kind": kind, "detail": detail})

    def fail(self, kind: str, detail: str) -> None:
        self.errors.append({"kind": kind, "detail": detail})

    def raise_if_failed(self) -> None:
        if self.errors:
            summary = "; ".join(f"{e['kind']}: {e['detail']}" for e in self.errors[:5])
            msg = f"{self.slug}: {len(self.errors)} verification error(s) — {summary}"
            raise IngestVerificationError(msg)


def _numeric_prefix(section_no: str) -> int | None:
    digits = ""
    for char in section_no:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits) if digits else None


def verify_sections(
    slug: str, sections: list[ParsedSection], *, expected: int | None = None
) -> VerificationReport:
    """Check continuity, plausibility and metadata coverage."""
    report = VerificationReport(slug=slug, sections=len(sections))

    if not sections:
        report.fail("empty", "no sections parsed")
        return report

    # Every number must reduce to a sort key, or ordering is undefined.
    for section in sections:
        try:
            section_no_sort(section.section_no)
        except SectionNumberError as exc:
            report.fail("unsortable_section_no", f"{section.section_no!r}: {exc}")

    numbers = [section.section_no for section in sections]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        report.fail("duplicate_section_no", ", ".join(duplicates))

    # Continuity of the numeric prefixes.
    seen = sorted({n for n in (_numeric_prefix(x) for x in numbers) if n is not None})
    if seen and seen[0] != 1:
        report.warn("no_section_1", f"lowest section number is {seen[0]}")
    for previous, current in zip(seen, seen[1:], strict=False):
        gap = current - previous - 1
        if gap <= 0:
            continue
        detail = f"nothing between {previous} and {current} ({gap} numbers)"
        if gap > MAX_GAP:
            report.fail("implausible_gap", detail)
        else:
            report.warn("section_gap", detail)

    # Plausibility of the text itself.
    for section in sections:
        length = len(section.text_verbatim)
        if section.is_omitted:
            continue
        if length < MIN_PLAUSIBLE_CHARS:
            report.warn("short_section", f"s.{section.section_no} is {length} chars")
        elif length > MAX_PLAUSIBLE_CHARS:
            report.warn("long_section", f"s.{section.section_no} is {length} chars")
        if not section.text_verbatim.strip():
            report.fail("empty_section", f"s.{section.section_no} has no text")

    # A missing marginal note is odd in an Act where every other section has one.
    with_note = sum(1 for s in sections if s.marginal_note)
    if with_note and with_note < len(sections):
        missing = [s.section_no for s in sections if not s.marginal_note]
        report.warn(
            "missing_marginal_note",
            f"{len(missing)} of {len(sections)} sections: {', '.join(missing[:10])}",
        )

    # Independent count from the manifest's oracle.
    if expected is not None:
        in_force = sum(1 for s in sections if not s.is_omitted)
        drift = abs(in_force - expected)
        if drift:
            detail = f"parsed {in_force} in-force sections, oracle expects {expected}"
            tolerance = max(5, expected // 20)
            if drift <= tolerance:
                report.warn("section_count_drift", detail)
            else:
                report.fail("section_count_drift", detail)

    return report
