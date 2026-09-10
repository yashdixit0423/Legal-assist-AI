"""Secrets and user text must not reach a log sink."""

from __future__ import annotations

import pytest

from app.core.logging import DROPPED_KEYS, REDACTED, SENSITIVE_KEYS, redact_sensitive


@pytest.mark.parametrize("key", sorted(SENSITIVE_KEYS))
def test_sensitive_values_are_redacted(key):
    out = redact_sensitive(None, "info", {"event": "x", key: "sk-live-abc123"})
    assert out[key] == REDACTED
    assert "sk-live-abc123" not in str(out)


@pytest.mark.parametrize("key", sorted(DROPPED_KEYS))
def test_user_text_and_prompts_are_dropped_entirely(key):
    out = redact_sensitive(None, "info", {"event": "x", key: "my landlord evicted me"})
    assert key not in out
    assert "landlord" not in str(out)


@pytest.mark.parametrize(
    "key", ["provider_api_key", "session_token", "encryption_key", "AUTHORIZATION"]
)
def test_suffix_and_case_variants_are_caught(key):
    out = redact_sensitive(None, "info", {key: "value-to-hide"})
    assert out[key] == REDACTED


def test_ordinary_fields_survive():
    out = redact_sensitive(None, "info", {"event": "e", "statute_id": 7, "latency_ms": 12.5})
    assert out == {"event": "e", "statute_id": 7, "latency_ms": 12.5}


def test_configure_logging_emits_json(capsys, settings_env):
    from app.core.config import get_settings
    from app.core.logging import configure_logging, get_logger

    configure_logging(get_settings())
    get_logger("test").info("hello", api_key="sk-should-not-appear", statute="dpdp-2023")
    captured = capsys.readouterr().err
    assert '"event": "hello"' in captured
    assert "sk-should-not-appear" not in captured
    assert REDACTED in captured


def test_logger_created_before_configuration_still_redacts(capsys, settings_env):
    """Regression: an eagerly-bound logger silently escapes the redaction chain.

    Every module in this codebase creates its logger at import time, which is
    before configure_logging() runs. If get_logger() binds eagerly, those
    loggers keep structlog's default processors and leak secrets forever.
    """
    import structlog

    from app.core.config import get_settings
    from app.core.logging import configure_logging, get_logger

    structlog.reset_defaults()
    early_logger = get_logger("imported.before.configuration")  # as a module would

    configure_logging(get_settings())
    early_logger.info("late_event", api_key="sk-must-not-appear", question="private text")

    captured = capsys.readouterr().err
    assert '"event": "late_event"' in captured, "renderer chain was not applied"
    assert '"logger": "imported.before.configuration"' in captured
    assert "sk-must-not-appear" not in captured
    assert "private text" not in captured
