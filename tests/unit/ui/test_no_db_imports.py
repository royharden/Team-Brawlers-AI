"""AST guard — UI layer is HTTP-only.

Architecture invariant: nothing under ``agentforge/ui/`` may import
``agentforge.memory.db``, ``agentforge.memory.models``, or
``agentforge.memory.repo``. The UI talks to the platform over HTTP via
:mod:`agentforge.ui.api_client`; the FastAPI app owns all DB access.

Mirrors the style of ``tests/unit/redteam/test_provider_isolation.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
UI_PKG_ROOT: Path = REPO_ROOT / "agentforge" / "ui"

_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "agentforge.memory.db",
    "agentforge.memory.models",
    "agentforge.memory.repo",
)


def _file_imports(path: Path) -> set[str]:
    """Return every dotted module name imported by this file."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.unit
def test_ui_layer_does_not_import_memory_modules() -> None:
    """Architecture invariant: nothing under `agentforge/ui/` may import `agentforge.memory.{db,models,repo}` (AgDR-0002 / master plan §4)."""
    offenders: list[tuple[str, str]] = []
    for py in UI_PKG_ROOT.rglob("*.py"):
        for imp in _file_imports(py):
            for prefix in _FORBIDDEN_PREFIXES:
                if imp == prefix or imp.startswith(prefix + "."):
                    offenders.append((str(py.relative_to(REPO_ROOT)), imp))
    assert not offenders, (
        "agentforge/ui/ must be HTTP-only (no memory.* imports). " f"Offenders: {offenders}"
    )


@pytest.mark.unit
def test_ui_layer_only_imports_api_responses_from_api() -> None:
    """The single sanctioned ``agentforge.api.*`` import from the UI is the
    Pydantic response models. Routes / deps must NOT be imported."""
    offenders: list[tuple[str, str]] = []
    for py in UI_PKG_ROOT.rglob("*.py"):
        for imp in _file_imports(py):
            if not imp.startswith("agentforge.api"):
                continue
            if imp == "agentforge.api.responses" or imp.startswith("agentforge.api.responses."):
                continue
            offenders.append((str(py.relative_to(REPO_ROOT)), imp))
    assert not offenders, (
        "UI may only import `agentforge.api.responses` from agentforge.api.*. "
        f"Offenders: {offenders}"
    )
