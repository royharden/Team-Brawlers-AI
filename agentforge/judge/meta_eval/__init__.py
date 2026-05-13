"""Judge meta-eval — master plan §10 / §22 DoD 16.

Validates the External Final Judge against a hand-labeled gold set. The judge
is independent of the Red Team agent (per master plan §8.3); this package
must NOT import ``agentforge.redteam.*`` and the
``tests/unit/judge/test_independence.py`` lint enforces it.
"""

from __future__ import annotations

from agentforge.judge.meta_eval.gold_set_schema import GoldCase, GoldSet
from agentforge.judge.meta_eval.metrics import (
    DEFAULT_FLOOR,
    JudgeMetrics,
    compute_judge_metrics,
)
from agentforge.judge.meta_eval.runner import (
    DEFAULT_OUTPUT_DIR,
    MetaEvalRunner,
    run_meta_eval,
)

__all__ = [
    "DEFAULT_FLOOR",
    "DEFAULT_OUTPUT_DIR",
    "GoldCase",
    "GoldSet",
    "JudgeMetrics",
    "MetaEvalRunner",
    "compute_judge_metrics",
    "run_meta_eval",
]
