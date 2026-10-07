"""The ephemeral document store — docs/adr/0005.

Process memory only: no disk, no Redis, no database. A server restart forgets
every document, which is the point. Documents expire after an idle TTL, and
both a per-user and a global cap evict the least recently used, so the store
cannot grow without bound.

**One API process only.** A second uvicorn worker would have its own, empty
store and answer ``document_not_found`` for documents the first one holds.
Move this to Redis with the same TTL before running more than one worker.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from app.core.errors import LegalEdgeError
from app.core.logging import get_logger
from app.services.documents.extract import DocumentKind, LocatorKind

IDLE_TTL_SECONDS = 60 * 60
MAX_PER_USER = 6
MAX_TOTAL = 500


class DocumentNotFoundError(LegalEdgeError):
    """Unknown, expired and someone else's are deliberately indistinguishable."""

    code = "document_not_found"
    http_status = 404
    message = "That document is no longer available. Attach it again to keep using it."


@dataclass(frozen=True)
class DocumentChunk:
    """One embedded passage and where it sits in the document."""

    locator: int
    text: str
    vector: npt.NDArray[np.float32]


@dataclass
class StoredDocument:
    id: str
    user_id: str
    filename: str
    kind: DocumentKind
    locator_kind: LocatorKind
    pages: int | None
    chunks: list[DocumentChunk]
    last_used: float = 0.0
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


def new_document_id() -> str:
    """Unguessable, so an id is useless to anyone it was not issued to."""
    return secrets.token_urlsafe(18)


class DocumentStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = IDLE_TTL_SECONDS,
        max_per_user: int = MAX_PER_USER,
        max_total: int = MAX_TOTAL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_per_user = max_per_user
        self.max_total = max_total
        self._clock = clock
        self._docs: OrderedDict[str, StoredDocument] = OrderedDict()
        self._lock = threading.Lock()

    # Every public method sweeps first, so an expired document is gone the
    # moment anyone touches the store — there is no background task to forget.
    def _sweep(self) -> None:
        cutoff = self._clock() - self.ttl_seconds
        for doc_id in [d.id for d in self._docs.values() if d.last_used < cutoff]:
            del self._docs[doc_id]

    def put(self, document: StoredDocument) -> StoredDocument:
        with self._lock:
            self._sweep()
            document.last_used = self._clock()
            self._docs[document.id] = document
            self._docs.move_to_end(document.id)
            owned = [d.id for d in self._docs.values() if d.user_id == document.user_id]
            for doc_id in owned[: max(0, len(owned) - self.max_per_user)]:
                del self._docs[doc_id]
            while len(self._docs) > self.max_total:
                self._docs.popitem(last=False)
            return document

    def get(self, user_id: str, document_id: str) -> StoredDocument:
        with self._lock:
            self._sweep()
            document = self._docs.get(document_id)
            if document is None or not secrets.compare_digest(document.user_id, user_id):
                raise DocumentNotFoundError()
            document.last_used = self._clock()
            self._docs.move_to_end(document_id)
            return document

    def get_many(self, user_id: str, document_ids: list[str]) -> list[StoredDocument]:
        """In request order, without duplicates; any miss fails the whole request."""
        seen: dict[str, StoredDocument] = {}
        for document_id in document_ids:
            if document_id not in seen:
                seen[document_id] = self.get(user_id, document_id)
        return list(seen.values())

    def delete(self, user_id: str, document_id: str) -> None:
        with self._lock:
            self._sweep()
            document = self._docs.get(document_id)
            if document is None or not secrets.compare_digest(document.user_id, user_id):
                raise DocumentNotFoundError()
            del self._docs[document_id]

    def expires_at(self, document: StoredDocument) -> dt.datetime:
        """Wall-clock expiry if the document is not used again."""
        idle = self._clock() - document.last_used
        remaining = max(0.0, self.ttl_seconds - idle)
        return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=remaining)

    def __len__(self) -> int:
        with self._lock:
            self._sweep()
            return len(self._docs)


_STORE = DocumentStore()

logger = get_logger(__name__)

_WORKER_FLAG = re.compile(r"^(?:--workers|-w)(?:=(\d+))?$")


def configured_workers(
    environ: Mapping[str, str] | None = None, argv: Sequence[str] | None = None
) -> int:
    """How many server processes the launch configuration asks for.

    Reads the conventional places: ``WEB_CONCURRENCY`` (uvicorn, gunicorn and
    most PaaS), ``UVICORN_WORKERS``, and ``--workers N`` / ``-w N`` on the
    command line. It is a best effort — a process manager can still start
    several copies behind a load balancer, which no process can see.
    """
    env = os.environ if environ is None else environ
    args = list(sys.argv if argv is None else argv)
    counts = [
        int(value)
        for key in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
        if (value := env.get(key, "").strip()).isdigit()
    ]
    for index, arg in enumerate(args):
        match = _WORKER_FLAG.match(arg)
        if not match:
            continue
        value = match.group(1) or (args[index + 1] if index + 1 < len(args) else "")
        if value.isdigit():
            counts.append(int(value))
    return max(counts, default=1)


def warn_if_multiple_workers(
    environ: Mapping[str, str] | None = None, argv: Sequence[str] | None = None
) -> bool:
    """Say plainly, at startup, that Chat documents will not be shared."""
    workers = configured_workers(environ, argv)
    if workers <= 1:
        return False
    logger.warning(
        "chat_documents_single_process_only",
        workers=workers,
        detail=(
            f"{workers} worker processes are configured, but uploaded Chat documents "
            "are held in one process's memory (docs/adr/0005). A question routed to "
            "a different worker than the upload will get document_not_found. Run a "
            "single worker, or move the document store to Redis."
        ),
    )
    return True


def get_store() -> DocumentStore:
    return _STORE


__all__ = [
    "DocumentChunk",
    "DocumentNotFoundError",
    "DocumentStore",
    "StoredDocument",
    "configured_workers",
    "get_store",
    "new_document_id",
    "warn_if_multiple_workers",
]
