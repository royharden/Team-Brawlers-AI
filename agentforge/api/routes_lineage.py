"""/v1/lineage routes — Attack Lineage Map (master plan §4 / §8.2).

The :class:`agentforge.redteam.lineage.AttackLineage` tracker is an in-process
structure. Until Phase 8 persists lineage into ``attack_traces``, the API
serves a process-singleton registry that the orchestrator (or a test fixture)
populates via :func:`set_lineage`. Calls before any record() return 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agentforge.redteam.lineage import AttackLineage

router = APIRouter()


_lineage_registry: AttackLineage = AttackLineage()


def set_lineage(lineage: AttackLineage) -> None:
    """Inject the active lineage tracker — used by the orchestrator + tests."""
    global _lineage_registry
    _lineage_registry = lineage


def get_lineage() -> AttackLineage:
    return _lineage_registry


@router.get("/lineage/{attack_id}")
def lineage_for_attack(attack_id: str) -> dict[str, Any]:
    """Return the lineage tree rooted at ``attack_id``."""
    lineage = get_lineage()
    # AttackLineage has no "exists" predicate; check the children map directly.
    known = attack_id in lineage._parents or attack_id in lineage._children
    if not known:
        raise HTTPException(status_code=404, detail=f"attack_id not found: {attack_id}")
    return lineage.tree(attack_id)
