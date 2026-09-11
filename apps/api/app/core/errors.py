"""The domain exception hierarchy.

Every error the API can return is one of these. The mapping to HTTP lives in
one place (:mod:`app.core.error_handlers`), and every error carries a stable
machine-readable ``code`` so a client can branch on it instead of parsing prose.

The code that matters most to the frontend is ``missing_provider_key``: it must
never surface as a generic 500, because the correct UI response is to route the
user to Settings.
"""

from __future__ import annotations

from typing import Any


class LegalEdgeError(Exception):
    """Base class for every expected failure in this application."""

    code: str = "internal_error"
    http_status: int = 500
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_payload(self) -> dict[str, Any]:
        """The ``error`` object of the JSON response body."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


# -- configuration ---------------------------------------------------------


class ConfigurationError(LegalEdgeError):
    code = "configuration_error"
    http_status = 500
    message = "The server is misconfigured."


# -- request-level ---------------------------------------------------------


class InvalidRequestError(LegalEdgeError):
    code = "invalid_request"
    http_status = 422
    message = "The request body or parameters are invalid."


class NotFoundError(LegalEdgeError):
    code = "not_found"
    http_status = 404
    message = "The requested resource does not exist."


class ConflictError(LegalEdgeError):
    code = "conflict"
    http_status = 409
    message = "That resource already exists."


class RateLimitedError(LegalEdgeError):
    code = "rate_limited"
    http_status = 429
    message = "Too many requests. Try again shortly."


# -- auth ------------------------------------------------------------------


class AuthenticationError(LegalEdgeError):
    code = "unauthenticated"
    http_status = 401
    message = "Authentication is required."


class AuthorizationError(LegalEdgeError):
    code = "forbidden"
    http_status = 403
    message = "You do not have access to this resource."


# -- bring-your-own-key provider path -------------------------------------


class ProviderError(LegalEdgeError):
    """Base for anything that goes wrong with the user's own LLM provider."""

    code = "provider_error"
    http_status = 502
    message = "The model provider returned an error."


class MissingProviderKeyError(ProviderError):
    """No usable provider credential is configured for this user.

    Distinct code and status on purpose: the frontend routes to Settings.
    """

    code = "missing_provider_key"
    http_status = 402
    message = "No provider API key is configured. Add one in Settings to ask questions."


class InvalidProviderKeyError(ProviderError):
    code = "provider_key_invalid"
    http_status = 401
    message = "The stored provider API key was rejected by the provider."


class ProviderQuotaError(ProviderError):
    code = "provider_quota_exceeded"
    http_status = 402
    message = "The provider reports the key is out of quota or credit."


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    http_status = 504
    message = "The model provider did not respond in time."


# -- corpus pipeline -------------------------------------------------------


class CorpusError(LegalEdgeError):
    code = "corpus_error"
    http_status = 500
    message = "The corpus pipeline failed."


class FetchError(CorpusError):
    code = "corpus_fetch_failed"
    message = "A source document could not be fetched."


class ParseError(CorpusError):
    code = "corpus_parse_failed"
    message = "A source document could not be parsed into sections."


class IngestVerificationError(CorpusError):
    code = "corpus_verification_failed"
    message = "Parsed output failed a continuity or plausibility assertion."


# -- retrieval and answering ----------------------------------------------


class RetrievalError(LegalEdgeError):
    code = "retrieval_failed"
    http_status = 500
    message = "Retrieval over the corpus failed."


class CitationValidationError(LegalEdgeError):
    """The model cited a section that was not in the packed context."""

    code = "citation_validation_failed"
    http_status = 500
    message = "The generated answer cited a section that was not retrieved."


# -- dependencies ----------------------------------------------------------


class ServiceUnavailableError(LegalEdgeError):
    code = "service_unavailable"
    http_status = 503
    message = "A required dependency is unavailable."


class DatabaseUnavailableError(ServiceUnavailableError):
    code = "database_unavailable"
    message = "The database is unavailable."
