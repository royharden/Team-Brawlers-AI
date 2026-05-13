"""Regression curator service on Documentation Agent — master plan §8.4 + §13."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RegressionCuratorError(Exception):
    """Raised when an invariant of the regression curator is violated."""


class RegressionCurator:
    """Emits `evals/regression/VR-####.json` for each confirmed exploit.

    Hard invariant (master plan §8.4 step 10 + §13): refuses to write a case
    whose `what_bug_this_catches` is empty.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def emit_case(self, vr_id: str, what_bug_this_catches: str, payload: dict[str, Any]) -> Path:
        if not what_bug_this_catches or not what_bug_this_catches.strip():
            raise RegressionCuratorError(
                f"Refusing to emit regression case {vr_id}: "
                "what_bug_this_catches is empty (master plan §13)"
            )
        _ = payload  # Phase 3 writes the actual JSON
        raise NotImplementedError("Phase 3 — not yet wired")
