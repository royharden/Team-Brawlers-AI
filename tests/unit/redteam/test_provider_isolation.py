"""CI guard - master plan §6 + AgDR-0001 + AgDR-0013 + AgDR-0024.

Two invariants:

1. The `openai` SDK is imported ONLY by:
   - `agentforge/redteam/openrouter_client.py` (AgDR-0013 — OpenRouter via
     OpenAI-compatible API).
   - `agentforge/redteam/openai_client.py`     (AgDR-0024 — direct OpenAI
     second-tier fallback when OpenRouter rate-limits).
2. The `anthropic` SDK is imported ONLY by `agentforge/redteam/anthropic_client.py`.

These guardrails ensure provider boundaries stay clean and tests can swap one
backend for another without dragging the other SDK along.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[3]
REDTEAM_PKG_ROOT: Path = REPO_ROOT / "agentforge" / "redteam"

_SANCTIONED_IMPORTERS: dict[str, set[str]] = {
    "openai": {"openrouter_client.py", "openai_client.py"},
    "anthropic": {"anthropic_client.py"},
}


def _file_imports(path: Path) -> set[str]:
    """Return the set of top-level package names imported by this file."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.unit
@pytest.mark.parametrize("forbidden_sdk", ["openai", "anthropic"])
def test_only_sanctioned_module_imports_sdk(forbidden_sdk: str) -> None:
    """Every module under agentforge/redteam/ must NOT import the forbidden
    SDK unless its filename is in the sanctioned set."""
    sanctioned = _SANCTIONED_IMPORTERS[forbidden_sdk]
    offenders: list[str] = []
    for py in REDTEAM_PKG_ROOT.rglob("*.py"):
        if py.name in sanctioned:
            continue
        imports = _file_imports(py)
        if forbidden_sdk in imports:
            offenders.append(str(py.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"{forbidden_sdk!r} SDK must only be imported by "
        f"{sorted(sanctioned)}; offenders: {offenders}"
    )


@pytest.mark.unit
def test_sanctioned_module_actually_imports_its_sdk() -> None:
    """Sanity-check the inverse: the sanctioned module DOES import the SDK
    (catches accidental deletion of the sanctioned import)."""
    for sdk, sanctioned_names in _SANCTIONED_IMPORTERS.items():
        for filename in sanctioned_names:
            path = REDTEAM_PKG_ROOT / filename
            assert path.exists(), f"sanctioned file missing: {path}"
            imports = _file_imports(path)
            assert sdk in imports, f"{path.relative_to(REPO_ROOT)} should import {sdk!r}"
