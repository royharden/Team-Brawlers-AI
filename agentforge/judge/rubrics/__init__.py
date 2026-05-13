"""Per-category rubric library — master plan §8.3.

`RubricRegistry` collects every (Rubric, check_fn) pair across the per-category
modules and exposes them by category for the judge layer to iterate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentforge.judge.rubrics import (
    clinical_integrity as _clinical_integrity,
)
from agentforge.judge.rubrics import (
    data_exfiltration as _data_exfil,
)
from agentforge.judge.rubrics import (
    denial_of_service as _denial_of_service,
)
from agentforge.judge.rubrics import (
    identity_role as _identity_role,
)
from agentforge.judge.rubrics import (
    observability_leakage as _observability_leakage,
)
from agentforge.judge.rubrics import (
    platform_self_attack as _platform_self_attack,
)
from agentforge.judge.rubrics import (
    prompt_injection as _pi,
)
from agentforge.judge.rubrics import (
    state_corruption as _state_corruption,
)
from agentforge.judge.rubrics import (
    tool_misuse as _tool_misuse,
)
from agentforge.judge.rubrics.base import Rubric, RubricOutcome

CheckFn = Callable[[dict[str, Any], dict[str, Any]], RubricOutcome]


# All per-category rubric modules participating in the registry.
_RUBRIC_MODULES: tuple[Any, ...] = (
    _pi,
    _data_exfil,
    _tool_misuse,
    _state_corruption,
    _denial_of_service,
    _identity_role,
    _clinical_integrity,
    _observability_leakage,
    _platform_self_attack,
)


class RubricRegistry:
    """Index of (Rubric, check_fn) pairs by category."""

    def __init__(self) -> None:
        self._by_category: dict[str, list[tuple[Rubric, CheckFn]]] = {}
        for module in _RUBRIC_MODULES:
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
