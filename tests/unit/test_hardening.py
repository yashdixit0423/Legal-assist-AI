"""Rate limiting and HTTP caching — Stage 9.

Smoke-level, except the limiter's fail-open behaviour, which gets its own test
because getting it backwards turns an outage in the thing that says "no" into
an outage in the thing that says "yes".
"""

from __future__ import annotations

import pytest

from app.core.errors import RateLimitedError
from app.core.ratelimit import _InProcessCounter, check, enforce


@pytest.fixture(autouse=True)
def _isolate_counters(monkeypatch):
    """Each test gets its own window store."""
    import app.core.ratelimit as rl

    monkeypatch.setattr(rl, "_local", _InProcessCounter())
    monkeypatch.setattr(rl, "_redis_client", None)


async def test_requests_under_the_limit_are_allowed(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    for expected_remaining in (2, 1, 0):
        decision = await check(settings, key="k", limit=3, window_seconds=60)
        assert decision.allowed
        assert decision.remaining == expected_remaining


async def test_the_request_over_the_limit_raises(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    for _ in range(3):
        await enforce(settings, key="k", limit=3, window_seconds=60)
    with pytest.raises(RateLimitedError) as caught:
        await enforce(settings, key="k", limit=3, window_seconds=60)
    assert caught.value.http_status == 429
    assert "retry_after_seconds" in caught.value.details


async def test_limits_are_per_key(settings_env):
    """One user exhausting their budget must not lock everyone else out."""
    from app.core.config import get_settings

    settings = get_settings()
    for _ in range(3):
        await enforce(settings, key="user-a", limit=3, window_seconds=60)
    decision = await check(settings, key="user-b", limit=3, window_seconds=60)
    assert decision.allowed


async def test_a_redis_failure_falls_back_instead_of_failing_the_request(settings_env, monkeypatch):
    """An outage in the limiter must not become an outage in the API."""
    import app.core.ratelimit as rl
    from app.core.config import get_settings

    class Broken:
        async def incr(self, *_args, **_kwargs):
            raise ConnectionError("redis is down")

    async def broken_redis(_settings):
        return Broken()

    monkeypatch.setattr(rl, "_redis", broken_redis)
    decision = await check(get_settings(), key="k", limit=3, window_seconds=60)
    assert decision.allowed, "a dead Redis must not block traffic"


def test_headers_tell_the_client_where_it_stands(settings_env):
    from app.core.ratelimit import Decision

    headers = Decision(allowed=True, limit=20, remaining=7, reset_after=42).headers()
    assert headers["X-RateLimit-Limit"] == "20"
    assert headers["X-RateLimit-Remaining"] == "7"
    assert headers["X-RateLimit-Reset"] == "42"


def test_remaining_never_reports_negative(settings_env):
    from app.core.ratelimit import Decision

    headers = Decision(allowed=False, limit=5, remaining=-3, reset_after=1).headers()
    assert headers["X-RateLimit-Remaining"] == "0"


def test_the_in_process_counter_rolls_over_between_windows():
    counter = _InProcessCounter()
    first, _ = counter.incr("k", window_seconds=1)
    assert first == 1
    second, _ = counter.incr("k", window_seconds=1)
    assert second == 2


# --- caching ----------------------------------------------------------------


def test_the_same_payload_gives_the_same_etag():
    from app.core.caching import compute_etag
    from app.schemas.corpus import SectionIndexEntry

    a = SectionIndexEntry(id=1, section_no="27", marginal_note="X", is_omitted=False)
    b = SectionIndexEntry(id=1, section_no="27", marginal_note="X", is_omitted=False)
    assert compute_etag(a) == compute_etag(b)


def test_a_changed_payload_gives_a_different_etag():
    """The tag is derived from what is actually being sent, so it cannot be
    wrong about what was sent."""
    from app.core.caching import compute_etag
    from app.schemas.corpus import SectionIndexEntry

    a = SectionIndexEntry(id=1, section_no="27", marginal_note="X", is_omitted=False)
    b = SectionIndexEntry(id=1, section_no="27", marginal_note="Y", is_omitted=False)
    assert compute_etag(a) != compute_etag(b)


def test_a_matching_if_none_match_sets_304():
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.caching import apply_cache_headers, compute_etag

    payload = {"a": 1}
    etag = compute_etag(payload)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"if-none-match", etag.encode())],
    }
    response = Response()
    apply_cache_headers(Request(scope), response, payload)
    assert response.status_code == 304
    assert response.headers["ETag"] == etag


def test_a_stale_if_none_match_returns_the_body():
    from starlette.requests import Request
    from starlette.responses import Response

    from app.core.caching import apply_cache_headers

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"if-none-match", b'"stale"')],
    }
    response = Response()
    apply_cache_headers(Request(scope), response, {"a": 1})
    assert response.status_code == 200
    assert "max-age" in response.headers["Cache-Control"]


# --- client address ---------------------------------------------------------


def test_only_the_leftmost_forwarded_hop_is_trusted():
    """X-Forwarded-For is client-settable. Trusting the whole chain would let
    anyone forge a fresh identity per request and walk around the limit."""
    from starlette.requests import Request

    from app.api.deps import client_ip

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": ("10.0.0.9", 1234),
        "headers": [(b"x-forwarded-for", b"203.0.113.7, 198.51.100.2")],
    }
    assert client_ip(Request(scope)) == "203.0.113.7"


def test_the_peer_address_is_used_when_there_is_no_proxy():
    from starlette.requests import Request

    from app.api.deps import client_ip

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": ("10.0.0.9", 1234),
        "headers": [],
    }
    assert client_ip(Request(scope)) == "10.0.0.9"
