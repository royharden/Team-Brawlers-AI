"""Judge meta-eval runner — master plan §10. Stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class MetaEvalRunner:
    """Replays the gold set against ExternalFinalJudge and emits metrics. Stub."""

    def __init__(self, gold_set_path: Path) -> None:
        self.gold_set_path = gold_set_path

    async def run(self) -> dict[str, Any]:
        raise NotImplementedError("Phase 3 — not yet wired")
