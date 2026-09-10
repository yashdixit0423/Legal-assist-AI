"""Sortable keys for legal section numbers.

``ORDER BY section_no`` is wrong for statutes: as text, "10" sorts before "9",
and Indian Acts are full of inserted provisions numbered 2A, 14B, 21-A and 45ZF
that have to fall between their neighbours rather than at the end.

:func:`section_no_sort` turns a rendered section number into a fixed-width key
whose **byte order** is the correct legal order. The column that stores it is
declared ``COLLATE "C"`` so PostgreSQL compares it byte-wise and the ordering
cannot depend on the server locale, where padding and punctuation may be
ignorable at the primary level.

Worked examples::

    "9"     -> "000009|"
    "10"    -> "000010|"
    "2A"    -> "000002|A   |"
    "21-A"  -> "000021|A   |"      (separators are not significant)
    "45ZF"  -> "000045|ZF  |"

so 2, 2A, 3, 9, 10, 21, 21A, 45ZF order exactly as a lawyer would read them.
"""

from __future__ import annotations

import re

# Widths are fixed so that comparison is positional. A separator byte below
# both digits and letters keeps segment boundaries unambiguous.
NUMERIC_WIDTH = 6
ALPHA_WIDTH = 4
SEPARATOR = "|"
_PAD = " "

MAX_NUMERIC = 10**NUMERIC_WIDTH - 1

# Digit runs and letter runs; every other character is a separator with no
# ordering significance ("21-A", "21 A" and "21A" are the same provision).
_TOKEN = re.compile(r"(\d+)|([A-Za-z]+)")


class SectionNumberError(ValueError):
    """A section number that cannot be reduced to a sortable key.

    Raised rather than truncated: a wrong sort key puts a citation next to the
    wrong provision, which is the worst failure this product can have.
    """


def section_no_sort(section_no: str) -> str:
    """Return the byte-sortable key for a rendered section number.

    Args:
        section_no: the number as printed in the Act — "9", "2A", "21-A".

    Returns:
        A fixed-width key. Equal keys mean the same provision written two ways.

    Raises:
        SectionNumberError: on an empty number, a number with no digits or
            letters at all, a numeric run above ``MAX_NUMERIC``, or an alphabetic
            run longer than ``ALPHA_WIDTH``.
    """
    if not section_no or not section_no.strip():
        msg = "section number is empty"
        raise SectionNumberError(msg)

    segments: list[str] = []
    for numeric, alpha in _TOKEN.findall(section_no):
        if numeric:
            value = int(numeric)
            if value > MAX_NUMERIC:
                msg = f"numeric run {value} in {section_no!r} exceeds {MAX_NUMERIC}"
                raise SectionNumberError(msg)
            segments.append(f"{value:0{NUMERIC_WIDTH}d}")
        else:
            if len(alpha) > ALPHA_WIDTH:
                msg = (
                    f"alphabetic run {alpha!r} in {section_no!r} is longer than "
                    f"{ALPHA_WIDTH} characters"
                )
                raise SectionNumberError(msg)
            segments.append(alpha.upper().ljust(ALPHA_WIDTH, _PAD))

    if not segments:
        msg = f"section number {section_no!r} contains no digits or letters"
        raise SectionNumberError(msg)

    # The trailing separator terminates every segment, so a shorter key is a
    # proper prefix of any key that extends it and therefore sorts first:
    # "2" ("000002|") comes before "2A" ("000002|A   |").
    return "".join(f"{segment}{SEPARATOR}" for segment in segments)
