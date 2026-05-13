"""Taxonomy tagger — master plan §8.4.

Best-effort mapping based on OWASP LLM Top 10 (2025 draft), OWASP Agentic
Top 10 (2025 draft), AVID v1, and the NIST AI RMF GenAI Profile.
Refined in Phase 6.

The mapping is data-driven: edit `templates/taxonomy_lookup.json` to add or
adjust category → control-id lists. Unknown categories return empty OWASP /
AVID lists plus the `default` NIST set so that even uncategorized findings
get *some* NIST RMF traceability.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_DEFAULT_LOOKUP_PATH = Path(__file__).parent / "templates" / "taxonomy_lookup.json"


class TagSet(BaseModel):
    """Four-axis taxonomy mapping for a single category."""

    owasp_llm_top_10: list[str] = Field(default_factory=list)
    owasp_agentic_top_10: list[str] = Field(default_factory=list)
    avid: list[str] = Field(default_factory=list)
    nist_ai_rmf: list[str] = Field(default_factory=list)


class Tagger:
    """Maps an attack category to a `TagSet`.

    The taxonomy JSON is loaded once at init time; subsequent `.tag()` calls
    are pure dict lookups.
    """

    def __init__(self, lookup_path: Path | None = None) -> None:
        """Load `taxonomy_lookup.json` (or the path provided) into memory."""
        path = lookup_path if lookup_path is not None else _DEFAULT_LOOKUP_PATH
        self.lookup_path = path
        if not path.exists():
            raise FileNotFoundError(f"taxonomy lookup file missing: {path}")
        self._lookup: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    def _section(self, name: str) -> dict[str, list[str]]:
        section = self._lookup.get(name, {})
        if not isinstance(section, dict):
            return {}
        return section

    def tag(self, category: str) -> TagSet:
        """Return the union of category-specific mappings.

        For NIST AI RMF, the `default` set is always included so that every
        finding carries at least the floor NIST controls (`Measure 2.7` /
        `Manage 2.4`). Unknown categories return empty OWASP / AVID lists
        plus the default NIST set.
        """
        llm = self._section("owasp_llm_top_10_2025").get(category, [])
        agentic = self._section("owasp_agentic_top_10_2025").get(category, [])
        avid = self._section("avid_v1").get(category, [])

        nist_section = self._section("nist_ai_rmf_genai_profile")
        nist_default = list(nist_section.get("default", []))
        nist_category = list(nist_section.get(category, []))
        # Union, preserving order: defaults first, then category-specific
        # additions that are not already present.
        seen: set[str] = set(nist_default)
        nist: list[str] = list(nist_default)
        for item in nist_category:
            if item not in seen:
                nist.append(item)
                seen.add(item)

        return TagSet(
            owasp_llm_top_10=list(llm),
            owasp_agentic_top_10=list(agentic),
            avid=list(avid),
            nist_ai_rmf=nist,
        )


__all__ = ["TagSet", "Tagger"]
