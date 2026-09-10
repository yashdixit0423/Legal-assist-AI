"""The single place where domain errors become HTTP responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import InvalidRequestError, LegalEdgeError
from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def _envelope(
    *, code: str, message: str, request_id: str | None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    if request_id:
        error["request_id"] = request_id
    return {"error": error}


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


async def handle_legaledge_error(request: Request, exc: Exception) -> JSONResponse:
    """Domain errors: status and code come from the exception class."""
    assert isinstance(exc, LegalEdgeError)  # noqa: S101 — registered for this type only
    log = logger.bind(error_code=exc.code, path=request.url.path, request_id=_request_id(request))
    if exc.http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        log.error("request_failed", message=exc.message)
    else:
        log.info("request_rejected", message=exc.message)
    return JSONResponse(
        status_code=exc.http_status,
        content=_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details or None,
            request_id=_request_id(request),
        ),
    )


async def handle_request_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI body/query validation, reshaped into our envelope."""
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    domain = InvalidRequestError(details={"fields": _validation_fields(exc)})
    return JSONResponse(
        status_code=domain.http_status,
        content=_envelope(
            code=domain.code,
            message=domain.message,
            details=domain.details,
            request_id=_request_id(request),
        ),
    )


def _validation_fields(exc: RequestValidationError) -> list[dict[str, str]]:
    return [
        {"field": ".".join(str(p) for p in err["loc"][1:]) or "<body>", "problem": err["msg"]}
        for err in exc.errors()
    ]


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Starlette's own 404/405 and anything raising HTTPException."""
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = {
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    }.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code=code, message=str(exc.detail), request_id=_request_id(request)),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. Logs the traceback; the client learns nothing about it."""
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        request_id=_request_id(request),
        exc_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            code="internal_error",
            message="An unexpected error occurred.",
            request_id=_request_id(request),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every handler onto the application."""
    app.add_exception_handler(LegalEdgeError, handle_legaledge_error)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected_error)
