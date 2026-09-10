"""Legal citation ordering — the part of Stage 1 that can point a citation at
the wrong provision if it is wrong.

These tests cover the algorithm. The ordering is *also* asserted inside
PostgreSQL in tests/integration/test_section_ordering.py, because the sort that
matters is the one the database performs under its own collation.
"""

from __future__ import annotations

import pytest

from app.services.kb.section_numbers import (
    ALPHA_WIDTH,
    MAX_NUMERIC,
    SectionNumberError,
    section_no_sort,
)

# The order a lawyer reads them in. Every adjacent pair is a separate assertion.
LEGAL_ORDER = [
    "1",
    "2",
    "2A",
    "2AA",
    "2B",
    "3",
    "4",
    "9",
    "10",
    "11",
    "13",
    "13A",
    "14",
    "14A",
    "14B",
    "20",
    "21",
    "21A",
    "21B",
    "22",
    "45",
    "45Z",
    "45ZA",
    "45ZF",
    "46",
    "99",
    "100",
    "101",
    "299",
    "371",
    "372A",
    "470",
]


def test_full_legal_sequence_sorts_correctly():
    assert sorted(LEGAL_ORDER, key=section_no_sort) == LEGAL_ORDER


@pytest.mark.parametrize(
    ("lower", "higher"),
    list(zip(LEGAL_ORDER, LEGAL_ORDER[1:], strict=False)),
)
def test_each_adjacent_pair_orders(lower, higher):
    assert section_no_sort(lower) < section_no_sort(higher)


def test_nine_sorts_before_ten():
    """The reason this column exists at all: as text, '10' < '9'."""
    assert "10" < "9"
    assert section_no_sort("9") < section_no_sort("10")


@pytest.mark.parametrize(
    ("earlier", "later"),
    [("2A", "3"), ("14B", "15"), ("21A", "22"), ("2A", "21"), ("2AA", "3")],
)
def test_inserted_provisions_fall_between_their_neighbours(earlier, later):
    assert section_no_sort(earlier) < section_no_sort(later)


@pytest.mark.parametrize("rendering", ["21A", "21-A", "21 A", "21.A", "21a", "  21-a  "])
def test_renderings_of_the_same_provision_share_a_key(rendering):
    """Portals render inserted sections inconsistently; they are one provision."""
    assert section_no_sort(rendering) == section_no_sort("21A")


def test_key_is_deterministic():
    assert section_no_sort("45ZF") == section_no_sort("45ZF")


def test_key_is_fixed_width_per_segment():
    assert section_no_sort("9") == "000009|"
    assert section_no_sort("2A") == "000002|A   |"
    assert section_no_sort("45ZF") == "000045|ZF  |"


@pytest.mark.parametrize("bad", ["", "   ", "—", "()", "…"])
def test_unusable_numbers_raise(bad):
    with pytest.raises(SectionNumberError):
        section_no_sort(bad)


def test_numeric_overflow_raises_rather_than_truncating():
    with pytest.raises(SectionNumberError, match="exceeds"):
        section_no_sort(str(MAX_NUMERIC + 1))


def test_long_alphabetic_run_raises_rather_than_truncating():
    """Truncating 'ABCDE' to 'ABCD' would silently collide with a real section."""
    with pytest.raises(SectionNumberError, match="longer than"):
        section_no_sort("45" + "A" * (ALPHA_WIDTH + 1))


def test_key_fits_the_column():
    """statute_sections.section_no_sort is varchar(64)."""
    longest = section_no_sort(f"{MAX_NUMERIC}{'Z' * ALPHA_WIDTH}{MAX_NUMERIC}")
    assert len(longest) <= 64
