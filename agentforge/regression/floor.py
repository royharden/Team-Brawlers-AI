"""Floor reader / writer for evals/floor.json — master plan §13."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Floor:
    """Wrap evals/floor.json. AgDR-gated writes (Phase 3)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        return self._data

    @property
    def max_new_regressions_per_run(self) -> int:
        return int(self._data.get("max_new_regressions_per_run", 0))
