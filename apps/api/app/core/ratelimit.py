"""Rate limiting, hand-rolled — spec §06.

Two backends behind one interface:

* **Redis** when ``REDIS_URL`` is set. A fixed window per key, incremented with
  ``INCR`` and given a TTL on first write, which is one round trip and correct
  across every API process.
* **In-process** otherwise, so a developer without Redis is limited rather than
  unlimited. It counts per *process*, so with more than one worker the
  effective limit is the configured number times the worker count. That is a
  real weakness and is why production wants Redis; it is logged loudly at
  startup rather than left for someone to discover from a bill.

A fixed window, not a sliding one: it permits a burst of up to 2x the limit
across a window boundary, and in exchange it is two lines of Redis and
obviously correct. The limits here exist to stop a runaway client spending
someone's provider budget, not to shape traffic precisely.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Decision:
    """The outcome of one check, and what to tell the client."""

    allowed: bool
    limit: int
    remaining: int
    reset_after: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(self.reset_after),
        }


class _InProcessCounter:
    """Fixed-window counters in local memory. One process only."""

    def __init__(self) -> None:
        self._windows: dict[tuple[str, int], int] = {}

    def incr(self, key: str, window_seconds: int) -> tuple[int, int]:
        now = int(time.time())
        bucket = now // window_seconds
        self._prune(bucket)
        count = self._windows.get((key, bucket), 0) + 1
        self._windows[(key, bucket)] = count
        reset_after = (bucket + 1) * window_seconds - now
        return count, reset_after

    def _prune(self, current_bucket: int) -> None:
        stale = [k for k in self._windows if k[1] < current_bucket - 1]
        for key in stale:
            del self._windows[key]


_local = _InProcessCounter()
_redis_client: object | None = None


async def _redis(settings: Settings) -> object | None:
    global _redis_client  # noqa: PLW0603 — one client per process
    if not settings.REDIS_URL:
        return None
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def check(settings: Settings, *, key: str, limit: int, window_seconds: int) -> Decision:
    """Count one request against ``key`` and say whether it is allowed.

    A Redis failure is **not** a request failure: the limiter falls back to the
    in-process counter and logs. An outage in the thing that says "no" must not
    become an outage in the thing that says "yes".
    """
    client = await _redis(settings)
    if client is not None:
        try:
            now = int(time.time())
            bucket = now // window_seconds
            redis_key = f"rl:{key}:{bucket}"
            count = int(await client.incr(redis_key))  # type: ignore[attr-defined]
            if count == 1:
                await client.expire(redis_key, window_seconds)  # type: ignore[attr-defined]
            reset_after = (bucket + 1) * window_seconds - now
            return _decide(count, limit, reset_after)
        except Exception as exc:  # noqa: BLE001 — see the docstring
            logger.warning("ratelimit_redis_unavailable", exc_type=type(exc).__name__)

    count, reset_after = _local.incr(key, window_seconds)
    return _decide(count, limit, reset_after)


def _decide(count: int, limit: int, reset_after: int) -> Decision:
    return Decision(
        allowed=count <= limit,
        limit=limit,
        remaining=limit - count,
        reset_after=reset_after,
    )


async def enforce(settings: Settings, *, key: str, limit: int, window_seconds: int) -> Decision:
    """Check and raise :class:`RateLimitedError` when over the limit."""
    decision = await check(settings, key=key, limit=limit, window_seconds=window_seconds)
    if not decision.allowed:
        raise RateLimitedError(
            f"Rate limit exceeded: {limit} per {window_seconds}s. "
            f"Try again in {decision.reset_after}s.",
            details={"retry_after_seconds": decision.reset_after},
        )
    return decision


def warn_if_not_shared(settings: Settings) -> None:
    """Say plainly, at startup, when limits are per-process rather than global."""
    if settings.REDIS_URL:
        return
    logger.warning(
        "ratelimit_in_process_only",
        detail=(
            "REDIS_URL is unset: rate limits count per process, so N workers "
            "allow N times the configured limit. Set REDIS_URL in production."
        ),
        app_env=settings.APP_ENV,
    )
