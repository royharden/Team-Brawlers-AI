"""Regression case + replay schema — master plan §13.

Pydantic models that mirror the on-disk shape of ``evals/regression/VR-####.json``
(emitted by :class:`agentforge.documentation.regression_curator.RegressionCurator`)
plus the in-memory bookkeeping types the runner needs.

The on-disk JSON shape is the source of truth — the curator writes it and the
regression runner consumes it. Adding a new optional field here without
extending the curator's ``emit_case`` is fine; doing the reverse (curator
writes a field the schema rejects) is a contract break and must be caught by
:meth:`RegressionCase.from_json` round-trip tests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------- types


class RegressionMetadata(BaseModel):
    """Curator-emitted bookkeeping wrapped inside each regression JSON file."""

    model_config = ConfigDict(extra="allow")

    originating_run_id: str
    target_fingerprint_at_discovery: str
    replay_command: str  # canonical shape: "tb regress --case VR-####"
    expected_outcome: Literal["fail"] = "fail"
    emitted_at: datetime


class RegressionCase(BaseModel):
    """In-memory representation of a regression case JSON file.

    Maps 1-1 to ``evals/regression/VR-####.json`` files (which the
    Documentation Agent's :class:`RegressionCurator` emits as part of
    ``write_report``).
    """

    model_config = ConfigDict(extra="allow")

    id: str  # seed.id; e.g. "prompt_injection_persona_override"
    vr_id: str  # "VR-####"
    category: str
    subcategory: str | None = None
    prompt: str
    expected_safe_behavior: str
    what_bug_this_catches: str = Field(min_length=1)
    severity: Literal["Critical", "High", "Medium", "Low", "Info"] = "Medium"
    references: list[str] = Field(default_factory=list)
    regression_metadata: RegressionMetadata
    turns: list[dict[str, Any]] | None = None
    mutator_directives: list[str] | None = None
    target_endpoint: str | None = None
    notes: str | None = None

    @field_validator("what_bug_this_catches")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("what_bug_this_catches must be non-empty (master plan §13)")
        return v

    @classmethod
    def from_json(cls, path: Path) -> RegressionCase:
        """Load a regression case JSON file from disk."""
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return cls.model_validate(data)

    def to_json(self, path: Path) -> None:
        """Persist this regression case to disk as JSON (indented)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")


# -------------------------------------------------------- replay outcome types


class ReplayOutcome(BaseModel):
    """One regression case → one verdict from the External Final Judge."""

    model_config = ConfigDict(extra="allow")

    vr_id: str
    case_id: str
    timestamp: datetime
    target_fingerprint: str  # fingerprint AT replay time (NOT at discovery)
    observed_outcome: Literal["fail", "passed", "error"]
    expected_outcome: Literal["fail"] = "fail"
    matched_expected: bool  # True iff observed == expected (i.e. still fails)
    judge_verdict_summary: str = ""
    judge_outcomes: dict[str, str] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


class ReplayBatch(BaseModel):
    """The output of one full ``tb regress`` run."""

    model_config = ConfigDict(extra="allow")

    started_at: datetime
    ended_at: datetime
    target_fingerprint: str
    cases_run: int
    cases_passed_unexpectedly: list[str] = Field(default_factory=list)
    cases_failed_as_expected: list[str] = Field(default_factory=list)
    cases_errored: list[str] = Field(default_factory=list)
    # NEW regressions — populated by the FloorEnforcer, not the runner itself.
    new_regressions: list[str] = Field(default_factory=list)


__all__ = [
    "RegressionCase",
    "RegressionMetadata",
    "ReplayBatch",
    "ReplayOutcome",
]
