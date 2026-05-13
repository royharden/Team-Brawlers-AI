"""Content-addressed mutation cache — keyed on (seed_id, mutator_chain, seed_int)."""

from __future__ import annotations

import hashlib
from typing import Any


class MutationCache:
    """Caches deterministic mutator output to avoid recomputation."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    @staticmethod
    def key(seed_id: str, mutator_chain: list[str], seed_int: int) -> str:
        payload = f"{seed_id}|{'>'.join(mutator_chain)}|{seed_int}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, k: str) -> Any | None:
        return self._store.get(k)

    def put(self, k: str, value: Any) -> None:
        self._store[k] = value
