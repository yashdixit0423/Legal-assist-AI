"""The test suite itself must never reach a model provider."""

from __future__ import annotations

import pytest


def test_no_provider_key_is_visible_to_tests():
    from app.core.config import get_settings

    assert get_settings().LLM_API_KEY == ""


async def test_an_unmocked_llm_call_fails_loudly():
    from app.core.config import get_settings
    from app.core.errors import MissingProviderKeyError
    from app.services.llm import client as llm

    messages = [{"role": "user", "content": "hello"}]
    # Without a key the client refuses before any network: the typed 402.
    with pytest.raises(MissingProviderKeyError):
        await llm.complete(get_settings(), messages)
    # With a key supplied, litellm itself is stubbed to refuse.
    with pytest.raises(AssertionError, match="not mocked"):
        await llm.complete(get_settings(), messages, api_key="sk-test-not-real")
