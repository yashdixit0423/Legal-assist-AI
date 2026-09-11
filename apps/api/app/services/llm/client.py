"""The one place that talks to a model provider.

LiteLLM so the provider is a configuration string rather than a code path, and
so Stage 7's per-user keys change one argument rather than this module.

Every provider failure is translated into the typed hierarchy in
:mod:`app.core.errors`. That matters most for a missing or rejected key: the
frontend routes those to Settings, and it can only do so if they arrive as
``missing_provider_key`` and ``provider_key_invalid`` rather than as a 500.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import (
    InvalidProviderKeyError,
    MissingProviderKeyError,
    ProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Completion:
    """What the provider returned, plus what it cost."""

    text: str
    model: str
    tokens_in: int | None
    tokens_out: int | None


def require_api_key(settings: Settings) -> str:
    """The configured key, or the typed 402.

    Called before retrieval spends anything only when the question is going to
    reach the model — an abstention needs no key, which is both correct and the
    reason an out-of-corpus question costs nothing.
    """
    key = settings.LLM_API_KEY.strip()
    if not key:
        raise MissingProviderKeyError(details={"provider": settings.LLM_MODEL.split("/", 1)[0]})
    return key


async def complete(settings: Settings, messages: list[dict[str, str]]) -> Completion:
    """One non-streaming completion. Streaming arrives with SSE in Stage 6."""
    import litellm
    from litellm import exceptions as llm_errors

    api_key = require_api_key(settings)
    try:
        response = await litellm.acompletion(
            model=settings.LLM_MODEL,
            messages=messages,
            api_key=api_key,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
    except llm_errors.AuthenticationError as exc:
        raise InvalidProviderKeyError(details={"provider_message": str(exc)[:200]}) from exc
    except llm_errors.RateLimitError as exc:
        raise ProviderQuotaError(details={"provider_message": str(exc)[:200]}) from exc
    except llm_errors.Timeout as exc:
        raise ProviderTimeoutError(details={"provider_message": str(exc)[:200]}) from exc
    except llm_errors.APIError as exc:
        raise ProviderError(details={"provider_message": str(exc)[:200]}) from exc

    usage = getattr(response, "usage", None)
    text = (response.choices[0].message.content or "").strip()
    completion = Completion(
        text=text,
        model=str(getattr(response, "model", settings.LLM_MODEL)),
        tokens_in=getattr(usage, "prompt_tokens", None),
        tokens_out=getattr(usage, "completion_tokens", None),
    )
    logger.info(
        "llm_completion",
        model=completion.model,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
    )
    return completion
