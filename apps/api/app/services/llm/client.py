"""The one place that talks to a model provider.

LiteLLM so the provider is a configuration string rather than a code path, and
so Stage 7's per-user keys change one argument rather than this module.

Every provider failure is translated into the typed hierarchy in
:mod:`app.core.errors`. That matters most for a missing or rejected key: the
frontend routes those to Settings, and it can only do so if they arrive as
``missing_provider_key`` and ``provider_key_invalid`` rather than as a 500.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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


def _configure_litellm() -> None:
    """Stop LiteLLM reaching out to GitHub on first use.

    Observed in Stage 4: the first completion fetched
    ``model_prices_and_context_window.json`` from raw.githubusercontent.com.
    That is an unannounced outbound call on the request path, it fails in an
    air-gapped deployment, and nothing in this design needs it — we do not
    compute costs, we report the provider's own token counts.
    """
    import litellm

    litellm.suppress_debug_info = True
    litellm.telemetry = False
    # Use whatever pricing table shipped with the package; never refresh it.
    litellm.model_cost_map_url = ""


def provider_of(model: str) -> str:
    """The provider half of a LiteLLM model id (``anthropic/claude-...``)."""
    return model.split("/", 1)[0]


def require_api_key(settings: Settings, api_key: str | None = None) -> str:
    """The key to use for this call, or the typed 402.

    ``api_key`` is the caller's own, resolved from the vault. When it is absent
    the environment's ``LLM_API_KEY`` is used — the single-key development mode
    Stages 4-6 ran on — and that fallback is **refused in production**, so a
    deployment cannot quietly bill every user's questions to the operator.

    Reached only when a question is actually going to the model: an abstention
    needs no key at all, which is why an out-of-corpus question costs nothing
    and works for a user who has stored nothing.
    """
    if api_key and api_key.strip():
        return api_key.strip()
    fallback = settings.LLM_API_KEY.strip()
    if fallback and not settings.is_production:
        logger.warning("llm_using_shared_env_key", app_env=settings.APP_ENV)
        return fallback
    raise MissingProviderKeyError(details={"provider": provider_of(settings.LLM_MODEL)})


def _translate(exc: Exception) -> Exception:
    """Map a LiteLLM failure onto our typed hierarchy.

    One translation table shared by the streaming and non-streaming paths, so
    a provider error means the same thing to a client either way.
    """
    from litellm import exceptions as llm_errors

    detail = {"provider_message": str(exc)[:200]}
    if isinstance(exc, llm_errors.AuthenticationError):
        return InvalidProviderKeyError(details=detail)
    if isinstance(exc, llm_errors.RateLimitError):
        return ProviderQuotaError(details=detail)
    if isinstance(exc, llm_errors.Timeout):
        return ProviderTimeoutError(details=detail)
    if isinstance(exc, llm_errors.APIError):
        return ProviderError(details=detail)
    return exc


async def complete(
    settings: Settings,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout_seconds: float | None = None,
    api_key: str | None = None,
) -> Completion:
    """One non-streaming completion.

    The overrides exist for query rewriting, which wants a cheaper model and a
    shorter leash than an answer does.
    """
    import litellm

    _configure_litellm()
    key = require_api_key(settings, api_key)
    try:
        response = await litellm.acompletion(
            model=model or settings.LLM_MODEL,
            messages=messages,
            api_key=key,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=max_tokens or settings.LLM_MAX_OUTPUT_TOKENS,
            timeout=timeout_seconds or settings.LLM_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise _translate(exc) from exc

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


async def stream(
    settings: Settings, messages: list[dict[str, str]], *, api_key: str | None = None
) -> AsyncIterator[str | Completion]:
    """Yield text deltas as they arrive, then one final :class:`Completion`.

    The trailing Completion carries the assembled text and the usage numbers,
    so a caller that needs the whole answer — the citation validator does —
    does not have to reassemble the deltas itself and risk disagreeing with
    what was actually sent.
    """
    import litellm

    _configure_litellm()
    key = require_api_key(settings, api_key)
    chunks: list[str] = []
    usage = None
    model = settings.LLM_MODEL
    try:
        response = await litellm.acompletion(
            model=settings.LLM_MODEL,
            messages=messages,
            api_key=key,
            temperature=settings.LLM_TEMPERATURE,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for part in response:
            usage = getattr(part, "usage", None) or usage
            model = str(getattr(part, "model", model) or model)
            choices = getattr(part, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if text:
                chunks.append(text)
                yield text
    except Exception as exc:
        raise _translate(exc) from exc

    yield Completion(
        text="".join(chunks).strip(),
        model=model,
        tokens_in=getattr(usage, "prompt_tokens", None),
        tokens_out=getattr(usage, "completion_tokens", None),
    )


# Smallest completion each provider will accept, used only to ask "does this key
# work?". One token is cheaper than any provider's model-listing endpoint and,
# unlike listing, it proves the key can actually be used to generate.
PROBE_MESSAGES = [{"role": "user", "content": "ping"}]
PROBE_MODELS = {
    "anthropic": "anthropic/claude-3-5-haiku-20241022",
    "openai": "openai/gpt-4o-mini",
    "google": "gemini/gemini-2.0-flash",
    "groq": "groq/llama-3.1-8b-instant",
    "openrouter": "openrouter/openai/gpt-4o-mini",
}


async def probe(settings: Settings, *, provider: str, api_key: str) -> None:
    """Verify a key against its provider. Raises a typed ProviderError if not.

    Deliberately a one-token generation rather than a model list: a key that
    can list models cannot necessarily generate with them, and generating is
    what we are about to do with it.
    """
    import litellm

    _configure_litellm()
    model = PROBE_MODELS.get(provider)
    if model is None:
        raise ProviderError(f"No verification probe is defined for {provider!r}.")
    try:
        await litellm.acompletion(
            model=model,
            messages=PROBE_MESSAGES,
            api_key=api_key,
            max_tokens=1,
            timeout=min(settings.LLM_TIMEOUT_SECONDS, 20.0),
        )
    except Exception as exc:
        translated = _translate(exc)
        if isinstance(translated, ProviderError):
            raise translated from exc
        raise ProviderError(details={"provider_message": str(exc)[:200]}) from exc
