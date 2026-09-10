"""The one and only place in this codebase that reads the environment.

Rule (enforced by tests/unit/test_no_env_access.py): no module outside this one
may touch ``os.environ`` or ``os.getenv``. Everything goes through
:func:`get_settings`.
"""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dimensionality of NyayaLabs98/nyaya-embed-v1 (base: intfloat/multilingual-e5-base).
# This is a property of the model, not a deployment choice, so it is a constant
# rather than an env var: the migration column type and the model must agree.
EMBEDDING_DIM = 768

# The e5 family requires asymmetric prefixes. Getting these wrong degrades
# retrieval silently, so they live here as constants and are asserted in tests.
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

# Hard ceiling of the embedding model. MAX_CHUNK_TOKENS must stay below it.
EMBED_MODEL_MAX_TOKENS = 512


class ConfigError(RuntimeError):
    """Raised when the process environment cannot produce valid settings."""


class Settings(BaseSettings):
    """Every runtime knob, sourced from the environment.

    Required variables have no default: construction fails loudly if they are
    absent, which is what we want at startup rather than a 500 on first use.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # -- application -------------------------------------------------------
    APP_ENV: Literal["local", "ci", "staging", "production"] = "local"
    APP_NAME: str = "legaledge-api"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_JSON: bool = True

    # -- database ----------------------------------------------------------
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_POOL_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DB_ECHO: bool = False

    # -- cache (optional service) -----------------------------------------
    REDIS_URL: str | None = None

    # -- auth --------------------------------------------------------------
    JWT_SECRET: Annotated[str, Field(min_length=32)]
    JWT_ACCESS_TTL: int = Field(default=900, ge=60)
    JWT_REFRESH_TTL: int = Field(default=1_209_600, ge=3600)

    # -- credential envelope encryption -----------------------------------
    # 32 raw bytes, base64-encoded, for AES-256-GCM.
    CREDENTIAL_ENC_KEY: str

    # -- retrieval models --------------------------------------------------
    EMBED_MODEL: str = "NyayaLabs98/nyaya-embed-v1"
    EMBED_MODEL_REVISION: str = ""
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_MODEL_REVISION: str = ""

    # -- retrieval tuning --------------------------------------------------
    RETRIEVAL_TOP_K: int = Field(default=30, ge=1, le=200)
    RERANK_TOP_N: int = Field(default=6, ge=1, le=50)
    RERANK_SCORE_FLOOR: float = Field(default=0.30, ge=0.0, le=1.0)
    MAX_CHUNK_TOKENS: int = Field(default=450, ge=64, le=EMBED_MODEL_MAX_TOKENS)

    # -- corpus pipeline ---------------------------------------------------
    CORPUS_ARCHIVE_DIR: Path = Path("var/corpus_archive")
    FETCH_USER_AGENT: str = (
        "LegalEdgeKB/0.1 (+https://recklabs.ai/legaledge; contact: legal-kb@recklabs.com)"
    )
    FETCH_DELAY_SECONDS: float = Field(default=2.0, ge=0.0, le=60.0)

    # -- observability -----------------------------------------------------
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str | None = None
    SENTRY_DSN: str | None = None

    @field_validator("CREDENTIAL_ENC_KEY")
    @classmethod
    def _validate_enc_key(cls, value: str) -> str:
        """AES-256-GCM needs exactly 32 raw bytes; reject anything else now."""
        try:
            raw = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            msg = "CREDENTIAL_ENC_KEY must be valid base64 (32 raw bytes for AES-256-GCM)"
            raise ValueError(msg) from exc
        if len(raw) != 32:
            msg = f"CREDENTIAL_ENC_KEY must decode to 32 bytes, got {len(raw)}"
            raise ValueError(msg)
        return value

    @field_validator("FETCH_USER_AGENT")
    @classmethod
    def _validate_user_agent(cls, value: str) -> str:
        """Government portals are entitled to know who is fetching and how to complain."""
        if "contact:" not in value and "@" not in value:
            msg = "FETCH_USER_AGENT must carry a contact address (portal politeness)"
            raise ValueError(msg)
        return value

    @property
    def database_url_async(self) -> str:
        """SQLAlchemy URL for asyncpg (the API path)."""
        return str(self.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def database_url_sync(self) -> str:
        """SQLAlchemy URL for psycopg (Alembic and the CLI)."""
        return str(self.DATABASE_URL).replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


# The dotenv path get_settings() reads. Tests set this to None so a developer's
# real .env can never satisfy a variable the test is asserting is missing.
_ENV_FILE: str | None = ".env"


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid or missing configuration:"]
    for err in exc.errors():
        name = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  - {name}: {err['msg']}")
    lines.append("See .env.example for every variable and its expected shape.")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, failing loudly on a bad environment."""
    try:
        return Settings(_env_file=_ENV_FILE)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc


def reset_settings_cache() -> None:
    """Drop the cached settings. Used by tests; never call from app code."""
    get_settings.cache_clear()
