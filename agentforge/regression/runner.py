"""Regression runner — master plan §13. Replays evals/regression/*.json. Stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RegressionRunner:
    """Replays confirmed-exploit cases and enforces floor.json."""

    def __init__(self, cases_dir: Path, floor_path: Path) -> None:
        self.cases_dir = cases_dir
        self.floor_path = floor_path

    async def run_all(self) -> dict[str, Any]:
        raise NotImplementedError("Phase 3 — not yet wired")
