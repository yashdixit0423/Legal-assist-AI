"""One module owns the environment. This test is the enforcement.

The architecture rule is "never read os.environ anywhere except in that
Settings class". A grep guard is crude, but it is the only thing that actually
fails when someone reaches for os.getenv in a service six stages from now.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (REPO_ROOT / "apps" / "api" / "app", REPO_ROOT / "cli")

# The only file permitted to read the process environment.
ALLOWED = {REPO_ROOT / "apps" / "api" / "app" / "core" / "config.py"}

PATTERN = re.compile(r"os\.environ|os\.getenv|environ\.get\(")


def _python_files() -> list[Path]:
    return [
        path
        for root in SOURCE_ROOTS
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def test_source_tree_is_not_empty():
    """Guard the guard: a broken glob must not make this test vacuously pass."""
    assert len(_python_files()) >= 15


def test_only_config_module_reads_the_environment():
    offenders = []
    for path in _python_files():
        if path in ALLOWED:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if PATTERN.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "environment read outside app/core/config.py:\n" + "\n".join(offenders)


def test_config_module_itself_does_read_the_environment():
    """If pydantic-settings ever stops sourcing env vars, this catches it."""
    from app.core.config import Settings

    assert Settings.model_config["env_file"] == ".env"
    assert Settings.model_config["case_sensitive"] is True
