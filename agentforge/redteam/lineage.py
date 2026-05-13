"""Attack lineage tracker — master plan §8.2."""

from __future__ import annotations

from uuid import UUID


class AttackLineage:
    """Records parent → child attack relationships for tree-of-attacks + crescendo."""

    def __init__(self) -> None:
        self._edges: list[tuple[UUID, UUID, list[str]]] = []

    def record(self, parent_id: UUID, child_id: UUID, mutator_chain: list[str]) -> None:
        """Record a single lineage edge. Persisted via memory.repo in Phase 2."""
        self._edges.append((parent_id, child_id, list(mutator_chain)))
