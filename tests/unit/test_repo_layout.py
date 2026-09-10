"""Spec §12 defines the tree. Keep it, and keep the scope fences visible."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED = [
    "apps/api/app/api/v1",
    "apps/api/app/db/models",
    "apps/api/app/services/kb/adapters",
    "apps/api/app/services/retrieval",
    "apps/api/app/services/answer",
    "apps/api/app/services/llm",
    "cli/legaledge_kb",
    "content/corpus",
    "content/prompts",
    "eval/gold",
    "eval/fixtures",
    "docs/adr",
    "deploy/caddy",
]

# Out of scope for Phase 1.1 (frontend, queue, object storage, k8s).
FORBIDDEN = ["apps/web", "worker", "k8s", "helm", "apps/api/app/services/queue"]


@pytest.mark.parametrize("relative", REQUIRED)
def test_required_directory_exists(relative):
    assert (REPO_ROOT / relative).is_dir(), f"missing {relative} (spec §12)"


@pytest.mark.parametrize("relative", FORBIDDEN)
def test_out_of_scope_directory_absent(relative):
    assert not (REPO_ROOT / relative).exists(), f"{relative} is outside Phase 1.1 scope"


def test_env_file_is_not_committed():
    assert ".env" in (REPO_ROOT / ".gitignore").read_text()
    assert not (REPO_ROOT / ".env").exists() or ".env" in (REPO_ROOT / ".gitignore").read_text()


def test_env_example_documents_every_setting():
    """A setting nobody can discover is a setting nobody sets correctly."""
    from app.core.config import Settings

    example = (REPO_ROOT / ".env.example").read_text()
    undocumented = [name for name in Settings.model_fields if name not in example]
    assert not undocumented, f"absent from .env.example: {undocumented}"


def test_dockerfile_ships_everything_the_migrations_need():
    """`alembic upgrade head` has to work inside the container, not just locally."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert "alembic.ini" in runtime, "alembic.ini is not copied into the runtime image"
    assert "COPY --chown=legaledge:legaledge apps ./apps" in runtime
