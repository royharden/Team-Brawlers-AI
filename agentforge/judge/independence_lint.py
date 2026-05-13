"""Judge-independence lint — master plan §8.3.

Real implementation. Parses Python source files with `ast` and returns the set
of forbidden `agentforge.redteam.*` imports. Used by
`tests/unit/judge/test_independence.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIX: str = "agentforge.redteam"


def scan_file(path: Path) -> set[str]:
    """Return the set of forbidden import names found in `path`."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return set()

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return set()

    offenders: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == FORBIDDEN_PREFIX or alias.name.startswith(FORBIDDEN_PREFIX + "."):
                    offenders.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == FORBIDDEN_PREFIX or module.startswith(FORBIDDEN_PREFIX + "."):
                offenders.add(module)
    return offenders


def scan(judge_pkg_root: Path) -> dict[Path, set[str]]:
    """Scan every `*.py` under `judge_pkg_root` and return offenders by file."""
    results: dict[Path, set[str]] = {}
    for py in judge_pkg_root.rglob("*.py"):
        offenders = scan_file(py)
        if offenders:
            results[py] = offenders
    return results
