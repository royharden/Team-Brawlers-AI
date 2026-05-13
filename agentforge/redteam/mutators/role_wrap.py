"""Role-wrap mutator — wraps prompt in pretend-role framing. Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class RoleWrapMutator(Mutator):
    name = "role_wrap"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
