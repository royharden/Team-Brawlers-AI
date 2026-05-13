"""Language mutators — translate-roundtrip + paraphrase. Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class LanguageMutator(Mutator):
    name = "language"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
