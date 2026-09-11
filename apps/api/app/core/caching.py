"""ETags and cache headers for the corpus reads — spec §06.

The corpus changes when an ingest runs, which is roughly never during a
browsing session, so the section a reader opens twice should cost one round
trip and one rendering. An ETag over the serialised payload gives that without
a cache to invalidate: the client sends the tag back, and an unchanged
response becomes a 304 with no body.

Deliberately weak-ish and content-derived rather than time-derived. A tag
built from ``updated_at`` would need every response to carry a reliable
timestamp for everything it embeds — a section read also contains its statute
and its cross-references — and getting that wrong serves stale law. Hashing
what is actually about to be sent cannot be wrong about what was sent.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel

# Corpus reads are public and immutable between ingest runs. Five minutes is
# short enough that a re-ingest becomes visible quickly and long enough to
# absorb a reader clicking through an Act.
PUBLIC_MAX_AGE = 300


def _serialise(payload: Any) -> bytes:
    if isinstance(payload, BaseModel):
        return payload.model_dump_json().encode()
    if isinstance(payload, list):
        return json.dumps(
            [p.model_dump(mode="json") if isinstance(p, BaseModel) else p for p in payload],
            sort_keys=True,
            default=str,
        ).encode()
    return json.dumps(payload, sort_keys=True, default=str).encode()


def compute_etag(payload: Any) -> str:
    return '"' + hashlib.sha256(_serialise(payload)).hexdigest()[:32] + '"'


def apply_cache_headers(request: Request, response: Response, payload: Any) -> None:
    """Set ``ETag`` and ``Cache-Control``; signal 304 when the client is current.

    FastAPI has already decided it is returning a body by the time a route
    handler runs, so a true empty 304 needs the status set on the injected
    response and the body discarded by the client. Setting the status here is
    what Starlette honours.
    """
    etag = compute_etag(payload)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={PUBLIC_MAX_AGE}"
    if request.headers.get("if-none-match") == etag:
        response.status_code = 304
