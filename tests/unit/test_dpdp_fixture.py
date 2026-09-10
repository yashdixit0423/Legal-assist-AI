"""Golden fixture: the DPDP Act, 2023, parsed section for section.

The fixture is the parser's contract. It is checked against the committed API
payload, so it runs offline and a regression in the parser fails here rather
than in a citation.

Verification performed by hand when the fixture was created (2026-09-11): all 44
sections present and continuous with no gaps; every marginal note checked against
the Act's own table of contents; the verbatim text of s.4 (grounds for
processing) and s.33 (penalties) read in full against the statute. The remaining
sections are pinned by SHA-256 rather than individually re-read.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.kb import parse as parser
from app.services.kb.adapters import indiacode_api
from app.services.kb.section_numbers import section_no_sort
from app.services.kb.verify import verify_sections

FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "fixtures"
PAYLOAD = FIXTURES / "dpdp-act-2023.payload.json"
GOLDEN = FIXTURES / "dpdp-act-2023.golden.json"


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parsed() -> list[parser.ParsedSection]:
    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    _act, sections = indiacode_api.parse_payload(payload)
    return [parser.parse_section(raw, order_idx=index) for index, raw in enumerate(sections)]


def test_act_metadata(golden):
    payload = json.loads(PAYLOAD.read_text(encoding="utf-8"))
    act, _ = indiacode_api.parse_payload(payload)
    assert act.act_number == golden["act"]["act_number"] == "22"
    assert act.year == 2023
    assert str(act.enacted_on) == "2023-08-11"
    assert act.ministry == golden["act"]["ministry"]


def test_all_forty_four_sections_present_and_continuous(parsed):
    numbers = [section.section_no for section in parsed]
    assert numbers == [str(n) for n in range(1, 45)]


def test_sections_are_in_citation_order(parsed):
    keys = [section_no_sort(section.section_no) for section in parsed]
    assert keys == sorted(keys)


def test_every_section_matches_the_fixture(parsed, golden):
    assert len(parsed) == golden["section_count"]
    for actual, expected in zip(parsed, golden["sections"], strict=True):
        assert actual.section_no == expected["section_no"]
        assert actual.marginal_note == expected["marginal_note"]
        assert actual.is_omitted == expected["is_omitted"]
        assert actual.order_idx == expected["order_idx"]
        digest = hashlib.sha256(actual.text_verbatim.encode()).hexdigest()
        assert (
            digest == expected["text_sha256"]
        ), f"s.{actual.section_no} text changed:\n{actual.text_verbatim[:300]}"


def test_hand_read_sections_are_verbatim(parsed):
    """The two sections read in full against the statute when the fixture was made."""
    sections = {section.section_no: section for section in parsed}

    grounds = sections["4"]
    assert grounds.marginal_note == "Grounds for processing personal data."
    assert grounds.text_verbatim.startswith(
        "(1) A person may process the personal data of a Data Principal only in "
        "accordance with the provisions of this Act and for a lawful purpose,"
    )
    assert "(a) for which the Data Principal has given her consent; or" in grounds.text_verbatim
    assert "(b) for certain legitimate uses." in grounds.text_verbatim
    assert '"lawful purpose" means any purpose which is not expressly forbidden by law' in (
        grounds.text_verbatim
    )

    penalties = sections["33"]
    assert penalties.marginal_note == "Penalties."
    assert "impose such monetary penalty specified in the Schedule" in penalties.text_verbatim
    assert "(a) the nature, gravity and duration of the breach;" in penalties.text_verbatim


def test_subsection_structure_survives_for_the_chunker(parsed):
    """Stage 3 splits long sections here, so the boundaries must be findable."""
    consent = next(s for s in parsed if s.section_no == "6")
    segments = parser.segment_section(consent.text_verbatim)
    labels = [segment.label for segment in segments]
    assert labels[0] == "(1)"
    assert len([label for label in labels if label.startswith("(")]) >= 5


def test_the_act_passes_the_guardrails(parsed):
    report = verify_sections("dpdp-act-2023", parsed)
    assert report.ok
    assert report.errors == []
    assert report.warnings == []
