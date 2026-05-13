"""Citation mutator — injects fake authoritative citations. Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class CitationMutator(Mutator):
    name = "citation"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
