"""Document-smuggle mutator — adversarial PDFs / intake forms (reportlab). Stub."""

from __future__ import annotations

from agentforge.redteam.mutators.base import Mutator


class DocumentSmuggleMutator(Mutator):
    name = "document_smuggle"

    def apply(self, prompt: str, seed_int: int) -> str:
        raise NotImplementedError("Phase 2 — not yet wired")
