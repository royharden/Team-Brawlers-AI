"""Orchestrator Agent — master plan §8.1."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger


class OrchestratorAgent:
    """Strategic loop: decides what to attack next, halts on budget."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Phase 1 wires real dependencies (memory, coverage, budget_guard, scheduler, llm)."""
        logger.debug("OrchestratorAgent stub init (Phase 0)")

    async def plan_next_batch(self, run_id: UUID, batch_size: int = 10) -> list[Any]:
        """Snapshot coverage + verdicts + cost, call Sonnet, return ranked AttackJobs."""
        raise NotImplementedError("Phase 1 — not yet wired")

    async def step(self, run_id: UUID) -> None:
        """Outer orchestration loop (plan → generate → execute → judge → document)."""
        raise NotImplementedError("Phase 1 — not yet wired")
