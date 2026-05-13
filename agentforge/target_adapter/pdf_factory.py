"""PDF factory (reportlab) — master plan §4 / §9. Phase 5 lands real templates."""

from __future__ import annotations

from pathlib import Path


class AdversarialPDFFactory:
    """Builds adversarial lab-result PDFs and intake forms via reportlab."""

    def make_lab_with_injection(self, out_path: Path, payload: str) -> Path:
        raise NotImplementedError("Phase 5 — not yet wired")

    def make_intake_with_injection(self, out_path: Path, payload: str) -> Path:
        raise NotImplementedError("Phase 5 — not yet wired")
