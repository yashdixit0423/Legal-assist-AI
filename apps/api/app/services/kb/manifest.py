"""Reading content/corpus/manifest.toml.

TOML rather than YAML so the pipeline needs no extra dependency (stdlib
``tomllib``); the manifest stays a data file either way.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import CorpusError

DEFAULT_MANIFEST = Path("content/corpus/manifest.toml")


@dataclass(frozen=True)
class ActEntry:
    """One Act to ingest, as declared in the manifest."""

    slug: str
    short_title: str
    tier: int
    act_id: str
    handle: str
    act_number: str
    year: int
    jurisdiction: str
    level: str
    ministry: str
    expected_sections: int | None = None

    @property
    def source_url(self) -> str:
        return f"https://indiacode.gov.in/handle/{self.handle}"


def load_manifest(path: Path | None = None) -> list[ActEntry]:
    """Return every Act in the manifest, in declaration order."""
    target = path or DEFAULT_MANIFEST
    if not target.exists():
        msg = f"corpus manifest not found at {target}"
        raise CorpusError(msg)
    raw = tomllib.loads(target.read_text(encoding="utf-8"))
    entries = [ActEntry(**item) for item in raw.get("act", [])]
    slugs = [entry.slug for entry in entries]
    if len(slugs) != len(set(slugs)):
        msg = "duplicate slug in corpus manifest"
        raise CorpusError(msg)
    return entries


def select_acts(
    entries: list[ActEntry], *, tier: int | None = None, slug: str | None = None
) -> list[ActEntry]:
    """Filter the manifest by tier or slug, failing loudly on an unknown slug."""
    chosen = entries
    if tier is not None:
        chosen = [entry for entry in chosen if entry.tier == tier]
    if slug is not None:
        chosen = [entry for entry in chosen if entry.slug == slug]
        if not chosen:
            msg = f"no Act with slug {slug!r} in the manifest"
            raise CorpusError(msg)
    return chosen
