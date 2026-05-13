"""Persuasion mutator — adds authority / urgency framing. Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class PersuasionMutator(Mutator):
    name = "persuasion"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
