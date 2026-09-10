"""Every failure leaves the API in the same envelope shape."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.error_handlers import REQUEST_ID_HEADER, register_exception_handlers
from app.core.errors import MissingProviderKeyError, NotFoundError
from app.core.middleware import RequestContextMiddleware


class _Body(BaseModel):
    top_k: int


@pytest.fixture
def error_app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)

    @application.get("/domain")
    async def domain() -> None:
        raise NotFoundError("No such section.", details={"section_no": "99Z"})

    @application.get("/no-key")
    async def no_key() -> None:
        raise MissingProviderKeyError()

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("a secret-bearing internal message")

    @application.post("/validated")
    async def validated(body: _Body) -> dict[str, int]:
        return {"top_k": body.top_k}

    return application


@pytest.fixture
async def error_client(error_app):
    # raise_app_exceptions=False mirrors uvicorn: the 500 response is sent to the
    # client and the traceback is logged, rather than escaping into the caller.
    async with AsyncClient(
        transport=ASGITransport(app=error_app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


async def test_domain_error_maps_to_its_own_status_and_code(error_client):
    response = await error_client.get("/domain")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == {"section_no": "99Z"}
    assert error["request_id"]


async def test_missing_provider_key_returns_402_not_500(error_client):
    response = await error_client.get("/no-key")
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "missing_provider_key"


async def test_unexpected_error_is_opaque_to_the_client(error_client):
    response = await error_client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret-bearing" not in response.text


async def test_request_validation_error_is_reshaped(error_client):
    response = await error_client.post("/validated", json={"top_k": "many"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["details"]["fields"][0]["field"] == "top_k"


async def test_unknown_route_uses_the_envelope(error_client):
    response = await error_client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_request_id_is_echoed_and_honoured(error_client):
    response = await error_client.get("/domain", headers={REQUEST_ID_HEADER: "abc123"})
    assert response.headers[REQUEST_ID_HEADER] == "abc123"
    assert response.json()["error"]["request_id"] == "abc123"
