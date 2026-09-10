"""requirements/*.txt is generated; it must not drift from pyproject.toml."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_sync_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sync_requirements", REPO_ROOT / "scripts" / "sync_requirements.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_requirements_files_match_pyproject():
    for path, expected in _load_sync_module().render().items():
        actual = (REPO_ROOT / path).read_text()
        assert actual == expected, f"{path} is stale — run: python scripts/sync_requirements.py"


def test_api_requirements_use_the_cpu_torch_index():
    """A CUDA torch wheel would add ~2 GB to the image for no benefit."""
    body = (REPO_ROOT / "requirements" / "api.txt").read_text()
    assert "https://download.pytorch.org/whl/cpu" in body
    assert "torch==" in body


def test_corpus_dependencies_are_not_in_the_api_requirements():
    api = (REPO_ROOT / "requirements" / "api.txt").read_text()
    for heavy in ("docling", "ocrmypdf", "datasets", "pymupdf"):
        assert heavy not in api


def test_ragas_is_confined_to_the_eval_group():
    """Architecture rule: ragas must never be importable from app code."""
    for group in ("api", "corpus", "dev"):
        assert "ragas" not in (REPO_ROOT / "requirements" / f"{group}.txt").read_text()
    assert "ragas==" in (REPO_ROOT / "requirements" / "eval.txt").read_text()


def test_no_forbidden_models_in_dependencies():
    """law-ai/InLegalBERT has no place in the retrieval path (spec correction 3)."""
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    declared = " ".join(
        project["dependencies"]
        + [dep for group in project["optional-dependencies"].values() for dep in group]
    ).lower()
    assert "inlegalbert" not in declared


def test_every_dependency_is_pinned_exactly():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    all_deps = project["dependencies"] + [
        dep for group in project["optional-dependencies"].values() for dep in group
    ]
    unpinned = [dep for dep in all_deps if "==" not in dep or "*" in dep.split("==", 1)[1]]
    assert not unpinned, f"unpinned or wildcard dependencies: {unpinned}"
