"""The polite fetcher.

Government portals are slow, occasionally down, and must not be hammered. Every
request carries a contact-bearing User-Agent, waits ``FETCH_DELAY_SECONDS``
between calls, and retries with exponential backoff. Everything fetched is
archived on disk with its SHA-256 so the pipeline never needs the portal twice.

India Code serves no ``robots.txt`` at all (measured 2026-09-11: the path 502s on
the apex host). Absent rules are treated as permission-with-politeness, not as an
error, and the check is recorded per run.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.core.errors import FetchError
from app.core.logging import get_logger

logger = get_logger(__name__)

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


@dataclass
class ArchivedDocument:
    """A file written under ``CORPUS_ARCHIVE_DIR``, with its checksum."""

    path: Path
    sha256: str
    bytes_written: int
    from_cache: bool = False


@dataclass
class FetchStats:
    """Counters for one run, written onto the ``ingest_runs`` row."""

    requests: int = 0
    cached: int = 0
    warnings: list[str] = field(default_factory=list)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class PoliteClient:
    """A rate-limited, retrying HTTP client for one portal."""

    def __init__(self, settings: Settings, *, base_url: str) -> None:
        self._settings = settings
        self._base_url = base_url.rstrip("/")
        self._delay = settings.FETCH_DELAY_SECONDS
        self._last_request_at = 0.0
        self.stats = FetchStats()
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.FETCH_USER_AGENT,
                "Accept": "application/json, text/plain, */*",
            },
            timeout=httpx.Timeout(60.0, connect=20.0),
            follow_redirects=True,
        )
        self._robots = self._load_robots()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _load_robots(self) -> urllib.robotparser.RobotFileParser | None:
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(f"{self._base_url}/robots.txt")
        try:
            response = self._client.get(f"{self._base_url}/robots.txt")
        except httpx.HTTPError as exc:
            self.stats.warnings.append(f"robots.txt unreachable ({type(exc).__name__})")
            return None
        if response.status_code != 200 or not response.text.strip():
            self.stats.warnings.append(
                f"no robots.txt served (HTTP {response.status_code}); "
                "proceeding with rate limiting"
            )
            return None
        parser.parse(response.text.splitlines())
        return parser

    def may_fetch(self, url: str) -> bool:
        """Honour robots.txt when the portal publishes one."""
        if self._robots is None:
            return True
        return self._robots.can_fetch(self._settings.FETCH_USER_AGENT, url)

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if self._last_request_at and elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_at = time.monotonic()

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _request(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        self._wait_turn()
        response = self._client.get(url, params=params)
        # 4xx other than 429 will not improve on retry.
        if response.status_code == 429 or response.status_code >= 500:
            response.raise_for_status()
        return response

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON document, relative to the portal base URL."""
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        if not self.may_fetch(url):
            msg = f"robots.txt disallows {url}"
            raise FetchError(msg)
        try:
            response = self._request(url, params)
        except httpx.HTTPError as exc:
            msg = f"GET {url} failed: {type(exc).__name__}"
            raise FetchError(msg) from exc
        self.stats.requests += 1
        if response.status_code != 200:
            msg = f"GET {url} returned HTTP {response.status_code}"
            raise FetchError(msg)
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            msg = f"GET {url} did not return JSON"
            raise FetchError(msg) from exc
        return payload


def archive_json(
    settings: Settings, *, slug: str, name: str, payload: object, refresh: bool = False
) -> ArchivedDocument:
    """Write a fetched payload under the archive directory and checksum it.

    Re-running with an unchanged source is a no-op: an existing archive is
    reused unless ``refresh`` is set, which is what makes the pipeline resumable.
    """
    directory = settings.CORPUS_ARCHIVE_DIR / slug
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name

    if target.exists() and not refresh:
        existing = target.read_bytes()
        return ArchivedDocument(
            path=target,
            sha256=sha256_bytes(existing),
            bytes_written=len(existing),
            from_cache=True,
        )

    serialised = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True).encode()
    target.write_bytes(serialised)
    logger.info("archived", slug=slug, name=name, bytes=len(serialised))
    return ArchivedDocument(
        path=target, sha256=sha256_bytes(serialised), bytes_written=len(serialised)
    )


def read_archive(settings: Settings, *, slug: str, name: str) -> Any:
    """Load a previously archived payload, or fail loudly."""
    target = settings.CORPUS_ARCHIVE_DIR / slug / name
    if not target.exists():
        msg = f"no archived document at {target}; run `legaledge-kb fetch` first"
        raise FetchError(msg)
    return json.loads(target.read_text(encoding="utf-8"))
