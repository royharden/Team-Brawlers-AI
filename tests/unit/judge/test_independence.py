"""CI guard — master plan §8.3 + AgDR-0001 (the per-class-import part still holds).

Judge code MUST NOT import from `agentforge.redteam.*`. This test reads every
`*.py` under `agentforge/judge/` with `ast` and fails if any forbidden import
is found.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge.judge.independence_lint import scan

# Resolve agentforge/judge/ relative to the inner repo root (3 parents up: tests/unit/judge/).
REPO_ROOT: Path = Path(__file__).resolve().parents[3]
JUDGE_PKG_ROOT: Path = REPO_ROOT / "agentforge" / "judge"


@pytest.mark.unit
def test_judge_does_not_import_redteam() -> None:
    """The independence lint must report zero offenders."""
    offenders = scan(JUDGE_PKG_ROOT)
    assert not offenders, (
        f"Judge MUST NOT import Red Team modules; offenders: "
        f"{ {str(p): sorted(imports) for p, imports in offenders.items()} }"
    )
