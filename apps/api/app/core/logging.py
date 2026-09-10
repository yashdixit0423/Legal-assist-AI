"""structlog configuration: JSON in deployment, human-readable locally.

Two rules this module enforces in code rather than in review:

* secrets never reach a log sink — API keys, decrypted credentials, cookies and
  authorization headers are redacted by :func:`redact_sensitive`;
* a full prompt containing user input is never logged — the ``prompt`` and
  ``question`` keys are dropped, and callers log lengths and hashes instead.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog

from app.core.config import Settings

REDACTED = "[redacted]"

# Keys whose *value* must never be written to a log line.
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "credential_ciphertext",
        "enc_key",
        "jwt",
        "jwt_secret",
        "password",
        "provider_key",
        "refresh_token",
        "secret",
        "set-cookie",
        "token",
    }
)

# Keys that may contain end-user text or a full model prompt. Dropped outright:
# redacting them is not enough, because their presence tempts future callers.
DROPPED_KEYS = frozenset({"prompt", "messages", "question", "answer", "turns"})


def promote_logger_name(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Move ``logger_name`` to ``logger``.

    ``logger`` is a reserved keyword of ``structlog.get_logger()``, so the
    module name travels as ``logger_name`` and is renamed here — which also
    lets ConsoleRenderer show it as a bracketed prefix in development.
    """
    if "logger_name" in event_dict:
        event_dict["logger"] = event_dict.pop("logger_name")
    return event_dict


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: redact secrets and drop user text."""
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in DROPPED_KEYS:
            del event_dict[key]
        elif lowered in SENSITIVE_KEYS or lowered.endswith(("_secret", "_key", "_token")):
            event_dict[key] = REDACTED
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Install the structlog pipeline. Idempotent; safe to call per process."""
    shared: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        promote_logger_name,
        redact_sensitive,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.LOG_LEVEL]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy) through the same sink.
    logging.basicConfig(
        format="%(message)s", stream=sys.stderr, level=settings.LOG_LEVEL, force=True
    )
    for noisy in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a logger carrying ``logger=<name>``.

    The name is passed as an *initial value*, not via ``.bind()``: binding
    materialises the proxy immediately against whatever configuration happens
    to be installed. Modules create their logger at import time, before
    :func:`configure_logging` has run, so an eager bind would freeze
    structlog's console default and — the part that matters — skip
    :func:`redact_sensitive` for the lifetime of the process.

    ``add_logger_name`` is not used because it requires a stdlib logger
    factory, and we write straight to stderr; :func:`promote_logger_name`
    renames the key on the way out.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(logger_name=name)
    return logger
