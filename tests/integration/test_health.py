"""GET /v1/health — the Stage 0 acceptance endpoint."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app import __version__


async def test_health_reports_version_and_shape(client, database_reachable):
    if not database_reachable:
        pytest.skip("no reachable DATABASE_URL; covered by the simulated-outage test")
    response = await client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["database"]["connected"] is True
    assert body["database"]["latency_ms"] >= 0
    # Stage 0 ships no migrations, so the corpus is empty and the schema is absent.
    assert body["corpus"]["statutes"] == 0
    assert body["corpus"]["sections"] == 0
    assert body["corpus"]["chunks"] == 0


async def test_health_is_degraded_and_503_when_the_database_is_down(client, monkeypatch):
    """A broken dependency must not read as healthy to a deploy probe."""

    class _FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return False

        async def execute(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", None, Exception("connection refused"))

    monkeypatch.setattr("app.api.v1.health.get_sessionmaker", lambda: (lambda: _FailingSession()))
    response = await client.get("/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"]["connected"] is False
    assert body["database"]["error"] == "OperationalError"


async def test_health_error_never_leaks_the_connection_string(client, monkeypatch):
    class _LeakySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return False

        async def execute(self, *_args, **_kwargs):
            raise OperationalError(
                "SELECT 1", None, Exception("password authentication failed for legaledge")
            )

    monkeypatch.setattr("app.api.v1.health.get_sessionmaker", lambda: (lambda: _LeakySession()))
    response = await client.get("/v1/health")
    assert "password" not in response.text
    assert "legaledge:legaledge" not in response.text


async def test_health_requires_no_credentials(client, database_reachable):
    """Corpus and liveness endpoints are never gated (spec §06)."""
    response = await client.get("/v1/health")
    assert response.status_code in (200, 503)
    assert "www-authenticate" not in {k.lower() for k in response.headers}


async def test_openapi_and_metrics_are_served(client):
    assert (await client.get("/openapi.json")).status_code == 200
    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "http_request" in metrics.text


async def test_driver_level_failure_is_degraded_not_a_500(client, monkeypatch):
    """asyncpg raises its own exception types; a health probe must survive them."""
    from asyncpg.exceptions import InvalidAuthorizationSpecificationError

    class _AuthFailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return False

        async def execute(self, *_args, **_kwargs):
            raise InvalidAuthorizationSpecificationError('role "legaledge" does not exist')

    monkeypatch.setattr(
        "app.api.v1.health.get_sessionmaker", lambda: (lambda: _AuthFailingSession())
    )
    response = await client.get("/v1/health")
    assert response.status_code == 503
    assert response.json()["database"]["error"] == "InvalidAuthorizationSpecificationError"
