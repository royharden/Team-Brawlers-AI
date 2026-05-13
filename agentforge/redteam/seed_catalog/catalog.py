"""SeedCatalog — lazily loads the per-category YAML seed files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# All 9 seed YAML files committed alongside this module. The original 3
# (prompt_injection, data_exfiltration, tool_misuse) are the Phase 2 set;
# the other 6 (state_corruption, denial_of_service, identity_role,
# clinical_integrity, observability_leakage, platform_self_attack) shipped
# in Phase 4 with the orchestrator's full 8-category coverage matrix -- but
# this constant was never extended, so the orchestrator's planner would
# pick categories that the catalog refused to serve. Fixed for C3-full
# (Plan_wk3_Claude_Next01 / AgDR-0016).
_CATEGORIES: tuple[str, ...] = (
    "prompt_injection",
    "data_exfiltration",
    "tool_misuse",
    "state_corruption",
    "denial_of_service",
    "identity_role",
    "clinical_integrity",
    "observability_leakage",
    "platform_self_attack",
)


class SeedCatalog:
    """Lazy in-memory view over the three committed seed YAMLs."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or Path(__file__).resolve().parent
        self._loaded: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._loaded is not None:
            return self._loaded
        data: dict[str, list[dict[str, Any]]] = {}
        for cat in _CATEGORIES:
            path = self._base / f"{cat}.yaml"
            if not path.exists():
                data[cat] = []
                continue
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
            seeds = doc.get("seeds") or []
            data[cat] = [dict(s) for s in seeds if isinstance(s, dict)]
        self._loaded = data
        return data

    def all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for seeds in self._load().values():
            out.extend(seeds)
        return out

    def by_category(self, category: str) -> list[dict[str, Any]]:
        return list(self._load().get(category, []))

    def by_id(self, seed_id: str) -> dict[str, Any]:
        for seed in self.all():
            if seed.get("id") == seed_id:
                return dict(seed)
        raise KeyError(f"seed_id not found in catalog: {seed_id!r}")
