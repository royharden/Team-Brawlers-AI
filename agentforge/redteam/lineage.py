"""Attack lineage tracker — master plan §8.2.

In-memory + persistence-friendly: a Phase-3 task will mirror records into
`attack_traces.mutator_chain_json` via the memory repo.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from agentforge.memory.schemas import MutatedAttack


class AttackLineage:
    """Tree-of-attacks-shaped lineage tracker."""

    def __init__(self) -> None:
        self._parents: dict[str, str | None] = {}
        self._children: dict[str, list[str]] = defaultdict(list)
        self._meta: dict[str, dict[str, Any]] = {}

    def record(self, attack: MutatedAttack) -> None:
        aid = attack.attack_id
        pid = attack.parent_attack_id
        self._parents[aid] = pid
        if pid is not None:
            kids = self._children[pid]
            if aid not in kids:
                kids.append(aid)
        # ensure node has a child entry (even if empty)
        self._children.setdefault(aid, [])
        self._meta[aid] = {
            "seed_id": attack.seed_id,
            "mutator_chain": list(attack.mutator_chain),
            "strategy": attack.strategy,
            "category": attack.category,
        }

    def ancestors(self, attack_id: str) -> list[str]:
        """Root → attack_id (exclusive of attack_id itself)."""
        chain: list[str] = []
        cur = self._parents.get(attack_id)
        while cur is not None:
            chain.append(cur)
            cur = self._parents.get(cur)
        return list(reversed(chain))

    def descendants(self, attack_id: str) -> list[str]:
        """BFS from attack_id, exclusive of itself."""
        out: list[str] = []
        q: deque[str] = deque(self._children.get(attack_id, []))
        while q:
            node = q.popleft()
            out.append(node)
            q.extend(self._children.get(node, []))
        return out

    def tree(self, root: str) -> dict[str, Any]:
        """Nested dict representation for UI rendering."""

        def _node(aid: str) -> dict[str, Any]:
            meta = self._meta.get(aid, {})
            return {
                "attack_id": aid,
                "seed_id": meta.get("seed_id"),
                "mutator_chain": meta.get("mutator_chain", []),
                "strategy": meta.get("strategy"),
                "children": [_node(c) for c in self._children.get(aid, [])],
            }

        return _node(root)
