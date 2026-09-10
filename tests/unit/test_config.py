"""Settings must fail loudly, and the model contract must not drift."""

from __future__ import annotations

import pytest

from app.core.config import (
    EMBED_MODEL_MAX_TOKENS,
    EMBEDDING_DIM,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    ConfigError,
    Settings,
    get_settings,
    reset_settings_cache,
)


def test_settings_load_from_environment(settings_env):
    settings = get_settings()
    assert settings.APP_ENV == "ci"
    assert str(settings.DATABASE_URL).startswith("postgresql://")
    assert settings.RETRIEVAL_TOP_K == 30
    assert settings.RERANK_TOP_N == 6
    assert settings.MAX_CHUNK_TOKENS == 450


@pytest.mark.parametrize("missing", ["DATABASE_URL", "JWT_SECRET", "CREDENTIAL_ENC_KEY"])
def test_missing_required_variable_fails_loudly(settings_env, missing):
    """get_settings() raises ConfigError naming the variable, not a bare KeyError."""
    settings_env.setattr("app.core.config._ENV_FILE", None)
    settings_env.delenv(missing)
    reset_settings_cache()
    with pytest.raises(ConfigError) as excinfo:
        get_settings()
    assert missing in str(excinfo.value)


def test_missing_required_variable_message_names_the_variable(settings_env):
    """The error text has to be actionable, not just non-zero."""
    from pydantic import ValidationError

    from app.core.config import _format_validation_error

    settings_env.delenv("JWT_SECRET")
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)
    message = _format_validation_error(excinfo.value)
    assert "JWT_SECRET" in message
    assert ".env.example" in message


@pytest.mark.parametrize(
    "bad_key",
    [
        "not-base64!!",
        "AAAA",  # decodes to 3 bytes
        "",
    ],
)
def test_credential_key_must_be_32_bytes_base64(settings_env, bad_key):
    settings_env.setenv("CREDENTIAL_ENC_KEY", bad_key)
    with pytest.raises(Exception, match="CREDENTIAL_ENC_KEY|Field required"):
        Settings(_env_file=None)


def test_short_jwt_secret_rejected(settings_env):
    settings_env.setenv("JWT_SECRET", "too-short")
    with pytest.raises(Exception, match="at least 32"):
        Settings(_env_file=None)


def test_user_agent_must_carry_a_contact(settings_env):
    """Portal politeness (spec §03) is a validation rule, not a convention."""
    settings_env.setenv("FETCH_USER_AGENT", "python-requests/2.31")
    with pytest.raises(Exception, match="contact"):
        Settings(_env_file=None)


def test_chunk_budget_cannot_exceed_the_embedding_model_limit(settings_env):
    """MAX_CHUNK_TOKENS above 512 would silently truncate passages."""
    settings_env.setenv("MAX_CHUNK_TOKENS", str(EMBED_MODEL_MAX_TOKENS + 1))
    with pytest.raises(Exception, match="less than or equal"):
        Settings(_env_file=None)


def test_driver_specific_urls(settings_env):
    settings = get_settings()
    assert settings.database_url_async.startswith("postgresql+asyncpg://")
    assert settings.database_url_sync.startswith("postgresql+psycopg://")


def test_embedding_contract_matches_nyaya_embed_v1(settings_env):
    """768 dims and the e5 prefixes are the whole retrieval contract."""
    assert EMBEDDING_DIM == 768
    assert PASSAGE_PREFIX == "passage: "
    assert QUERY_PREFIX == "query: "
    assert EMBED_MODEL_MAX_TOKENS == 512
    settings = get_settings()
    assert settings.EMBED_MODEL == "NyayaLabs98/nyaya-embed-v1"
    assert settings.RERANK_MODEL == "BAAI/bge-reranker-v2-m3"
    assert settings.MAX_CHUNK_TOKENS < EMBED_MODEL_MAX_TOKENS


def test_default_model_is_not_inlegalbert_or_bge_m3(settings_env):
    """Two models are explicitly wrong for this corpus; keep them out."""
    settings = get_settings()
    forbidden = ("inlegalbert", "bge-m3")
    assert not any(name in settings.EMBED_MODEL.lower() for name in forbidden)
