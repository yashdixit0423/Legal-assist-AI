"""The exception hierarchy and its HTTP mapping."""

from __future__ import annotations

import inspect

import pytest

from app.core import errors
from app.core.errors import (
    LegalEdgeError,
    MissingProviderKeyError,
    NotFoundError,
    ProviderError,
)


def _all_error_classes() -> list[type[LegalEdgeError]]:
    return [
        obj
        for _, obj in inspect.getmembers(errors, inspect.isclass)
        if issubclass(obj, LegalEdgeError) and obj is not LegalEdgeError
    ]


def test_every_error_has_a_distinct_machine_readable_code():
    codes = [cls.code for cls in _all_error_classes()]
    duplicates = {code for code in codes if codes.count(code) > 1}
    assert not duplicates, f"duplicate error codes: {duplicates}"
    assert all(code.islower() and " " not in code for code in codes)


def test_missing_provider_key_is_not_a_generic_500():
    """The frontend routes to Settings on this code; it must never be internal_error."""
    exc = MissingProviderKeyError()
    assert exc.code == "missing_provider_key"
    assert exc.http_status == 402
    assert exc.http_status < 500
    assert isinstance(exc, ProviderError)
    assert "Settings" in exc.message


def test_payload_carries_code_and_optional_details():
    exc = NotFoundError("No such statute.", details={"slug": "nonexistent-act"})
    assert exc.to_payload() == {
        "code": "not_found",
        "message": "No such statute.",
        "details": {"slug": "nonexistent-act"},
    }


def test_payload_omits_empty_details():
    assert "details" not in NotFoundError().to_payload()


@pytest.mark.parametrize("cls", _all_error_classes())
def test_status_codes_are_plausible(cls):
    assert 400 <= cls.http_status <= 599
    assert cls.message and cls.message[0].isupper()
