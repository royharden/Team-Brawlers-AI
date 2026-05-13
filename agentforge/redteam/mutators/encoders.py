"""Encoder mutators — base64 / rot13 / leet / homoglyph / morse / piglatin / unicode. Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class EncoderMutator(Mutator):
    name = "encoder"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
