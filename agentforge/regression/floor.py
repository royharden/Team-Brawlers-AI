"""Floor enforcement for ``evals/floor.json`` — master plan §13.

The floor is the contract a regression run MUST satisfy. Violating it is a
CI hard gate (non-zero exit code). Two semantic checks live here:

* **new_regressions** — vr_ids that flipped from "no signal / passing" in
  the previous batch to "failing" in the current batch. These are bugs
  that re-appeared after a target change and they ALWAYS block the gate
  unless explicitly whitelisted under ``known_failing_cases``.
* **unexpected_passes** — vr_ids that flipped from "failing" to "passing"
  between runs. These are NOT failures — they are fix candidates surfaced
  for the human reviewer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentforge.regression.case_schema import ReplayBatch


class Floor(BaseModel):
    """Schema for ``evals/floor.json``.

    ``judge_floor`` is a per-layer dict of per-metric thresholds; the
    regression runner doesn't enforce it (that's the meta-eval runner's
    job, sub-agent F2), but we keep it on the schema so reads + writes
    round-trip cleanly.
    """

    model_config = ConfigDict(extra="allow")

    max_new_regressions_per_run: int = 0
    known_failing_cases: list[str] = Field(default_factory=list)
    judge_floor: dict[str, dict[str, float]] = Field(default_factory=dict)


class FloorResult(BaseModel):
    """The outcome of evaluating one :class:`ReplayBatch` against the floor."""

    floor_exceeded: bool
    new_regressions: list[str] = Field(default_factory=list)
    unexpected_passes: list[str] = Field(default_factory=list)
    summary: str = ""
    exit_code: int = 0  # 0 if floor met, 1 if exceeded


class FloorEnforcer:
    """Reads ``evals/floor.json``; evaluates a :class:`ReplayBatch`.

    A "new regression" is a vr_id that ``failed`` in the current batch AND
    ``passed`` in the previous batch. With no previous batch every failing
    case is, by definition, a new regression — that matches the PRD intent
    of "block the merge until a human reviews any new failure".

    The ``known_failing_cases`` whitelist on the floor is the escape hatch:
    a vr_id on that list NEVER counts as a new regression, even on the
    first run.
    """

    def __init__(self, floor: Floor) -> None:
        self._floor = floor

    @classmethod
    def from_json(cls, path: Path) -> FloorEnforcer:
        data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(Floor.model_validate(data))

    @property
    def floor(self) -> Floor:
        return self._floor

    def evaluate(
        self,
        batch: ReplayBatch,
        *,
        previous_batch: ReplayBatch | None = None,
    ) -> FloorResult:
        known = set(self._floor.known_failing_cases)
        prev_failed = (
            set(previous_batch.cases_failed_as_expected) if previous_batch else set()
        )
        prev_passed = (
            set(previous_batch.cases_passed_unexpectedly) if previous_batch else set()
        )

        # Currently failing in this batch.
        now_failing = set(batch.cases_failed_as_expected)
        now_passing = set(batch.cases_passed_unexpectedly)

        if previous_batch is None:
            # No baseline → every failing case (sans whitelist) is "new".
            new_regs = sorted(now_failing - known)
        else:
            # New regression = failing now AND (previously passing OR previously
            # unseen). A vr_id that was already failing in the previous batch
            # is "known still-broken", not a new regression.
            previously_seen_as_failing = prev_failed
            new_regs = sorted(
                vr_id
                for vr_id in now_failing
                if vr_id not in previously_seen_as_failing and vr_id not in known
            )

        # Unexpected passes: failing previously, passing now. Fix candidates!
        unexpected_passes = sorted(now_passing & prev_failed) if previous_batch else sorted(
            now_passing
        )

        exceeded = len(new_regs) > self._floor.max_new_regressions_per_run
        exit_code = 1 if exceeded else 0
        if exceeded:
            summary = (
                f"FLOOR EXCEEDED: {len(new_regs)} new regression(s) "
                f"(max allowed: {self._floor.max_new_regressions_per_run}). "
                f"New: {new_regs}"
            )
        else:
            summary = (
                f"Floor OK: {len(new_regs)} new regression(s) "
                f"(<= max {self._floor.max_new_regressions_per_run}), "
                f"{len(unexpected_passes)} fix candidate(s)."
            )

        return FloorResult(
            floor_exceeded=exceeded,
            new_regressions=new_regs,
            unexpected_passes=unexpected_passes,
            summary=summary,
            exit_code=exit_code,
        )


__all__ = ["Floor", "FloorEnforcer", "FloorResult"]
