"""Per-category rubric library — master plan §8.3.

`RubricRegistry` collects every (Rubric, check_fn) pair across the per-category
modules and exposes them by category for the judge layer to iterate.
"""

from __future__ import annotations

from typing import Any, Callable

from agentforge.judge.rubrics import (
    data_exfiltration as _data_exfil,
)
from agentforge.judge.rubrics import (
    prompt_injection as _pi,
)
from agentforge.judge.rubrics import (
    tool_misuse as _tool_misuse,
)
from agentforge.judge.rubrics.base import Rubric, RubricOutcome

CheckFn = Callable[[dict[str, Any], dict[str, Any]], RubricOutcome]


class RubricRegistry:
    """Index of (Rubric, check_fn) pairs by category."""

    def __init__(self) -> None:
        self._by_category: dict[str, list[tuple[Rubric, CheckFn]]] = {}
        for module in (_pi, _data_exfil, _tool_misuse):
            rubrics: list[Rubric] = list(getattr(module, "RUBRICS", []))
            checks: dict[str, CheckFn] = dict(getattr(module, "CHECKS", {}))
            for rubric in rubrics:
                fn = checks.get(rubric.id)
                if fn is None:
                    continue
                self._by_category.setdefault(rubric.category, []).append((rubric, fn))

    def categories(self) -> list[str]:
        return list(self._by_category.keys())

    def rubrics_for(self, category: str) -> list[tuple[Rubric, CheckFn]]:
        return list(self._by_category.get(category, []))


__all__ = ["RubricRegistry", "Rubric", "RubricOutcome", "CheckFn"]
