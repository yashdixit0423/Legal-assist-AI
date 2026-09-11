"""The citation validator — the second of the four things that get a real suite.

Spec §05 calls step 8 "the most important twenty lines in this phase". A
fabricated section number is the most damaging error this product can make and
the only hallucination class detectable deterministically: we know exactly
which sections went into the prompt.
"""

from __future__ import annotations

from app.services.answer.citations import extract_citations, validate_citations

ALLOWED = frozenset({1046, 537, 102})


def test_an_answer_citing_only_packed_sections_passes():
    check = validate_citations(
        "A lease determines by efflux of time [S1046]. An agreement in restraint "
        "of trade is void to that extent [S537].",
        ALLOWED,
    )
    assert check.ok
    assert not check.violation
    assert check.cited == frozenset({1046, 537})
    assert check.reason is None


def test_a_fabricated_section_id_is_caught():
    check = validate_citations("The Act says otherwise [S9999].", ALLOWED)
    assert not check.ok
    assert check.violation
    assert check.invalid == frozenset({9999})
    assert check.reason == "cited_sections_not_in_context"


def test_one_valid_and_one_fabricated_still_fails():
    """A partially grounded answer is not a grounded answer."""
    check = validate_citations("First [S1046]. Second [S4242].", ALLOWED)
    assert not check.ok
    assert check.invalid == frozenset({4242})


def test_an_answer_with_no_citations_at_all_fails():
    """An assertion about the law with no provision behind it is the exact
    output this product exists not to produce."""
    check = validate_citations("Yes, a non-compete after employment is void.", ALLOWED)
    assert not check.ok
    assert not check.violation
    assert check.reason == "no_citations"
    assert check.cited == frozenset()


def test_footnote_markers_in_statute_text_are_not_mistaken_for_citations():
    """India Code renders footnotes as bare [1], [2][State Government]. Those
    markers are inside the blocks we hand the model and will be quoted back in
    answers; a bare-integer citation scheme would fight the statute's own
    footnotes forever."""
    check = validate_citations(
        "The [2][State Government] may, by order [1], exempt a class of documents "
        "from registration [S1046].",
        ALLOWED,
    )
    assert check.ok
    assert check.cited == frozenset({1046})


def test_citations_are_extracted_wherever_they_appear():
    text = "[S1] opening, mid [S22] sentence, and trailing [S333]"
    assert extract_citations(text) == frozenset({1, 22, 333})


def test_a_lowercase_or_unbracketed_form_is_not_a_citation():
    """Lowercase ``s`` and bare ids are not recognised, so an answer using only
    those reads as uncited and is regenerated rather than accepted."""
    check = validate_citations("See [s1046] and S1046.", ALLOWED)
    assert not check.ok
    assert check.reason == "no_citations"


def test_whitespace_inside_the_brackets_is_tolerated():
    """A model that writes "[ S1046 ]" meant to cite, and the id must be
    checked rather than ignored."""
    assert validate_citations("See [ S1046 ].", ALLOWED).ok


def test_the_same_citation_repeated_counts_once():
    check = validate_citations("One [S537]. Two [S537]. Three [S537].", ALLOWED)
    assert check.ok
    assert check.cited == frozenset({537})


def test_an_empty_allowed_set_rejects_everything():
    """Defensive: a prompt with no blocks must never be treated as permissive."""
    check = validate_citations("Grounded, honestly [S1046].", frozenset())
    assert not check.ok
    assert check.invalid == frozenset({1046})


def test_the_check_reports_what_was_allowed_for_the_retry_message():
    check = validate_citations("[S9999]", ALLOWED)
    assert check.allowed == ALLOWED


# --- forms a real model actually produces -----------------------------------
#
# Every case below was found by running gpt-4.1-mini against the live corpus.
# The first version of the validator matched only [S123] with the bracket
# immediately after the digits, so it silently ignored two of these three
# forms. An ignored citation is worse than a rejected one: a fabricated
# [S9999(c)] passed validation and was reported as a clean answer.


def test_a_sub_clause_pointer_is_still_a_citation():
    """Observed live: "may be registered optionally [S19(c)]"."""
    check = validate_citations("Optional registration applies [S19(c)].", frozenset({19}))
    assert check.ok
    assert check.cited == frozenset({19})


def test_a_fabricated_sub_clause_pointer_is_caught():
    """The regression that matters. This used to pass as a clean answer."""
    check = validate_citations("The Act provides [S9999(c)].", ALLOWED)
    assert not check.ok
    assert check.violation
    assert check.invalid == frozenset({9999})


def test_several_ids_in_one_bracket_are_all_checked():
    """Observed live: "must be registered compulsorily [S18(1)(d), S1107]"."""
    check = validate_citations("Compulsory registration [S18(1)(d), S1107].", frozenset({18, 1107}))
    assert check.ok
    assert check.cited == frozenset({18, 1107})


def test_one_bad_id_among_several_in_a_bracket_still_fails():
    """The failure the compound form used to hide: only the trailing id was
    being checked, so a bad leading id went through."""
    check = validate_citations("See [S9999, S1107].", frozenset({1107}))
    assert not check.ok
    assert check.invalid == frozenset({9999})


def test_statute_footnotes_and_bracketed_prose_are_not_citations():
    """India Code renders footnotes as [1] and [2][State Government]; the
    letter prefix is what keeps them out of the citation space."""
    assert extract_citations("[1] and [2][State Government] and [Schedule 1]") == frozenset()


def test_a_bare_id_without_brackets_is_not_counted():
    """Fails closed: an answer using only bare forms reads as uncited and is
    regenerated, rather than being accepted on an unchecked reference."""
    check = validate_citations("As held in S1046 the lease determines.", frozenset({1046}))
    assert not check.ok
    assert check.reason == "no_citations"
