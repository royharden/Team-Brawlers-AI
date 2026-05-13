"""CoverageMatrix — master plan §8.1, §9.1. 8 categories × 9 strategies = 72 cells."""

from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES: tuple[str, ...] = (
    "prompt_injection",
    "data_exfiltration",
    "state_corruption",
    "tool_misuse",
    "denial_of_service",
    "identity_role",
    "clinical_integrity",
    "observability_leakage",
)

STRATEGIES: tuple[str, ...] = (
    "single_turn",
    "crescendo",
    "tree_of_attacks",
    "linear_jailbreak",
    "bad_likert_judge",
    "role_play",
    "document_smuggle",
    "tool_arg_injection",
    "platform_self_attack",
)


@dataclass
class CoverageCell:
    """One cell in the 8×9 category × strategy matrix."""

    category: str
    strategy: str
    attempts: int = 0
    successes: int = 0
    last_attempted_at: str | None = None

    @property
    def pass_rate(self) -> float:
        if self.attempts == 0:
            return 1.0
        return 1.0 - (self.successes / self.attempts)


@dataclass
class CoverageMatrix:
    """In-memory coverage tracker. Persisted via memory.repo in Phase 1."""

    cells: dict[tuple[str, str], CoverageCell] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cells:
            for cat in CATEGORIES:
                for strat in STRATEGIES:
                    self.cells[(cat, strat)] = CoverageCell(category=cat, strategy=strat)

    def update(self, category: str, strategy: str, outcome: bool) -> None:
        """Record an attempt; outcome=True means attack succeeded (cell failed)."""
        key = (category, strategy)
        if key not in self.cells:
            self.cells[key] = CoverageCell(category=category, strategy=strategy)
        cell = self.cells[key]
        cell.attempts += 1
        if outcome:
            cell.successes += 1
