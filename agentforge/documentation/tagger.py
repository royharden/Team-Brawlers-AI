"""Taxonomy tagger — master plan §8.4. Loads templates/taxonomy_lookup.json. Stub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TaxonomyTagger:
    """Maps attack category → OWASP LLM10 / OWASP Agentic / AVID / NIST AI RMF."""

    def __init__(self, lookup_path: Path) -> None:
        self.lookup_path = lookup_path
        self._lookup: dict[str, Any] = {}

    def load(self) -> None:
        """Load the lookup JSON into memory."""
        if self.lookup_path.exists():
            self._lookup = json.loads(self.lookup_path.read_text(encoding="utf-8"))

    def tag(self, category: str) -> dict[str, Any]:
        """Return taxonomy tags for the given category. Stub returns {}."""
        return self._lookup.get(category, {})
