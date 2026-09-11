"""The chunker, which is one of the four things that get a real suite.

Everything here protects a failure that produces no error and no exception —
just quietly worse retrieval, found weeks later:

* a missing or misspelt ``passage:`` prefix (e5 models are asymmetric);
* a chunk over the model's 512-token input, which is truncated in silence;
* a sub-section split that loses the heading, so a proviso is retrieved with
  nothing to say which provision it qualifies.
"""

from __future__ import annotations

import pytest

from app.core.config import PASSAGE_PREFIX, QUERY_PREFIX
from app.services.kb.chunk import build_heading_prefix, chunk_section

CEILING = 450


def words(count: int, word: str = "consideration") -> str:
    return " ".join([word] * count)


def fake_counter(text: str) -> int:
    """A deterministic stand-in: one token per whitespace-separated word.

    Used for the structural assertions, where the point is the splitting
    behaviour rather than the exact tokenisation. The real tokenizer is used
    separately, below, for the assertion that actually guards the model.
    """
    return len(text.split())


# --- the passage: prefix ----------------------------------------------------


def test_heading_prefix_is_the_form_the_brief_specifies():
    prefix = build_heading_prefix(
        "Indian Contract Act, 1872", "Agreement in restraint of trade void."
    )
    assert prefix == ("passage: Indian Contract Act, 1872 — Agreement in restraint of trade void. ")


def test_every_chunk_carries_the_passage_prefix():
    chunks = chunk_section(
        short_title="Registration Act, 1908",
        marginal_note="Documents of which registration is compulsory",
        text="\n".join(f"({n}) {words(60)}" for n in range(1, 12)),
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) > 1, "this fixture is meant to split"
    for chunk in chunks:
        assert chunk.heading_prefix.startswith(PASSAGE_PREFIX)
        assert chunk.embed_input.startswith(PASSAGE_PREFIX)
        assert not chunk.text.startswith(PASSAGE_PREFIX), "the prefix must not be doubled"


def test_a_section_with_no_marginal_note_still_gets_the_prefix():
    prefix = build_heading_prefix("Indian Stamp Act, 1899", None)
    assert prefix.startswith(PASSAGE_PREFIX)
    assert prefix == "passage: Indian Stamp Act, 1899. "


def test_passage_and_query_prefixes_are_distinct_and_not_interchangeable():
    """The whole point of an asymmetric model; a swap costs recall, not errors."""
    assert PASSAGE_PREFIX != QUERY_PREFIX
    assert PASSAGE_PREFIX == "passage: "
    assert QUERY_PREFIX == "query: "


def test_embed_passages_refuses_a_string_without_the_prefix(settings_env):
    """The guard exists because the caller building the string is not the
    caller embedding it, and a refactor could drop the prefix silently."""
    from app.core.config import get_settings
    from app.services.kb.embedding import embed_passages

    with pytest.raises(ValueError, match="passage:"):
        embed_passages(get_settings(), ["a section with no prefix at all"])


# --- the token ceiling ------------------------------------------------------


def test_no_chunk_exceeds_the_ceiling_when_sub_sections_are_long():
    chunks = chunk_section(
        short_title="Indian Stamp Act, 1899",
        marginal_note="Duties by whom payable",
        text="\n".join(f"({n}) {words(300)}" for n in range(1, 6)),
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert chunks
    assert all(chunk.token_count <= CEILING for chunk in chunks)


def test_a_single_oversized_sub_section_is_split_rather_than_truncated():
    """The Stamp Act's duty schedules are one provision of 20-30k characters
    with no sub-section structure. Nothing may be dropped."""
    body = ". ".join(words(80) for _ in range(30)) + "."
    chunks = chunk_section(
        short_title="Indian Stamp Act, 1899",
        marginal_note="Instruments chargeable with duty",
        text=body,
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) > 1
    assert all(chunk.token_count <= CEILING for chunk in chunks)
    rejoined = " ".join(chunk.text for chunk in chunks).split()
    assert rejoined == body.split(), "splitting must not lose or reorder any word"


def test_a_section_that_fits_is_exactly_one_chunk():
    chunks = chunk_section(
        short_title="Digital Personal Data Protection Act, 2023",
        marginal_note="Short title and commencement",
        text=words(40),
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_idx == 0


def test_an_empty_section_produces_no_chunks():
    assert (
        chunk_section(
            short_title="Any Act, 1900",
            marginal_note="Omitted",
            text="   ",
            count_tokens=fake_counter,
            max_tokens=CEILING,
        )
        == []
    )


# --- splits keep their heading ---------------------------------------------


def test_sub_section_splits_all_carry_the_parent_heading():
    note = "Documents of which registration is compulsory"
    chunks = chunk_section(
        short_title="Registration Act, 1908",
        marginal_note=note,
        text=(f"(1) {words(300)}\n" f"Provided that {words(300)}\n" f"Explanation.-- {words(300)}"),
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) >= 3
    for chunk in chunks:
        assert note in chunk.heading_prefix
        assert "Registration Act, 1908" in chunk.heading_prefix
    assert len({chunk.heading_prefix for chunk in chunks}) == 1


def test_a_proviso_stays_with_its_provision_while_the_two_fit_together():
    """Splitting is a last resort: a proviso that fits beside its sub-section
    is kept beside it, because that is the reading the draftsman intended."""
    chunks = chunk_section(
        short_title="Transfer of Property Act, 1882",
        marginal_note="Part performance",
        text=f"(1) {words(300)}\nProvided that nothing in this section shall affect anything.",
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) == 1
    assert "Provided that" in chunks[0].text


def test_a_proviso_forced_into_its_own_chunk_still_carries_the_heading():
    chunks = chunk_section(
        short_title="Transfer of Property Act, 1882",
        marginal_note="Part performance",
        text=f"(1) {words(435)}\nProvided that nothing in this section shall affect anything.",
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    proviso = [c for c in chunks if c.text.startswith("Provided")]
    assert proviso, "the proviso no longer fits beside the sub-section"
    assert "Part performance" in proviso[0].heading_prefix


def test_chunk_indexes_are_contiguous_from_zero():
    chunks = chunk_section(
        short_title="Information Technology Act, 2000",
        marginal_note="Penalty for damage to computer",
        text="\n".join(f"({n}) {words(200)}" for n in range(1, 8)),
        count_tokens=fake_counter,
        max_tokens=CEILING,
    )
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


# --- the same assertions, against the model's own tokenizer -----------------
# A word count under-reports legal English by roughly a third ("notwithstanding",
# "hypothecation", "[2][State Government]"), so the ceiling has to be proved
# with the tokenizer the model will actually use.


@pytest.fixture(scope="module")
def real_counter():
    from app.core.config import get_settings
    from app.services.kb.embedding import token_counter

    try:
        return token_counter(get_settings())
    except Exception as exc:  # noqa: BLE001 — no weights cached, no network
        pytest.skip(f"embedding tokenizer unavailable: {type(exc).__name__}")


def test_real_tokenizer_respects_the_ceiling_on_dense_legal_text(real_counter):
    body = (
        "(1) Notwithstanding anything contained in the [2][Indian Registration Act, 1908], "
        "every instrument of hypothecation, mortgage by deposit of title-deeds, or "
        "conveyance chargeable with duty under Schedule I-A shall, "
    ) * 60
    chunks = chunk_section(
        short_title="Indian Stamp Act, 1899",
        marginal_note="Instruments chargeable with duty",
        text=body,
        count_tokens=real_counter,
        max_tokens=CEILING,
    )
    assert len(chunks) > 1
    for chunk in chunks:
        assert real_counter(chunk.embed_input) <= CEILING
        assert chunk.token_count == real_counter(chunk.embed_input)
