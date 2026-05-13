"""Top-level regression runner — master plan §13.

Loads frozen regression cases from ``evals/regression/*.json``, replays each
against the target via :class:`Replay`, enforces ``evals/floor.json`` via
:class:`FloorEnforcer`, and persists a JSONL transcript of the batch under
``evals/results/regression_<timestamp>.jsonl``.

The CI gate (master plan §22 Definition of Done) treats a non-zero exit
code from this runner as a merge blocker.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from agentforge.regression.case_schema import (
    RegressionCase,
    ReplayBatch,
    ReplayOutcome,
)
from agentforge.regression.floor import FloorEnforcer, FloorResult
from agentforge.regression.replay import Replay


class RegressionRunner:
    """Loads + replays + persists regression cases."""

    def __init__(
        self,
        replay: Replay,
        floor_enforcer: FloorEnforcer,
        regression_dir: Path,
        results_dir: Path,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._replay = replay
        self._floor_enforcer = floor_enforcer
        self._regression_dir = Path(regression_dir)
        self._results_dir = Path(results_dir)
        self._session_factory = session_factory

    # ----------------------------------------------------------------- load

    def discover_cases(self) -> list[RegressionCase]:
        """Walk ``regression_dir`` for VR-*.json files; load each via
        :meth:`RegressionCase.from_json`. Files are returned sorted by name
        so output ordering is deterministic across runs.
        """
        if not self._regression_dir.exists():
            return []
        cases: list[RegressionCase] = []
        for path in sorted(self._regression_dir.glob("VR-*.json")):
            cases.append(RegressionCase.from_json(path))
        return cases

    def _find_case(self, vr_id: str) -> RegressionCase:
        path = self._regression_dir / f"{vr_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Regression case not found: {path} " f"(searched in {self._regression_dir})"
            )
        return RegressionCase.from_json(path)

    # ------------------------------------------------------------------ run

    def run_one(
        self,
        vr_id: str,
        *,
        target_fingerprint: str,
    ) -> ReplayOutcome:
        """Single-case run for ``tb regress --case VR-####``."""
        case = self._find_case(vr_id)
        outcome = self._replay.run_case(case, target_fingerprint=target_fingerprint)
        if self._session_factory is not None:
            self._persist_outcome_to_repo(outcome)
        return outcome

    def run_all(
        self,
        *,
        target_fingerprint: str,
        previous_batch: ReplayBatch | None = None,
    ) -> tuple[ReplayBatch, FloorResult]:
        """Run every discovered case; emit + persist :class:`ReplayBatch`,
        then evaluate it against the floor.
        """
        started = datetime.now(UTC)
        cases = self.discover_cases()

        outcomes: list[ReplayOutcome] = []
        for case in cases:
            outcomes.append(self._replay.run_case(case, target_fingerprint=target_fingerprint))

        ended = datetime.now(UTC)

        cases_failed_as_expected: list[str] = []
        cases_passed_unexpectedly: list[str] = []
        cases_errored: list[str] = []
        for oc in outcomes:
            if oc.observed_outcome == "fail":
                cases_failed_as_expected.append(oc.vr_id)
            elif oc.observed_outcome == "passed":
                cases_passed_unexpectedly.append(oc.vr_id)
            else:
                cases_errored.append(oc.vr_id)

        batch = ReplayBatch(
            started_at=started,
            ended_at=ended,
            target_fingerprint=target_fingerprint,
            cases_run=len(outcomes),
            cases_passed_unexpectedly=sorted(cases_passed_unexpectedly),
            cases_failed_as_expected=sorted(cases_failed_as_expected),
            cases_errored=sorted(cases_errored),
            new_regressions=[],  # populated below from FloorResult
        )

        floor_result = self._floor_enforcer.evaluate(batch, previous_batch=previous_batch)
        # Populate new_regressions on the batch post-hoc so the JSONL header
        # carries the floor's verdict alongside the raw observations.
        batch = batch.model_copy(update={"new_regressions": floor_result.new_regressions})

        self._write_results_jsonl(batch, outcomes)
        if self._session_factory is not None:
            for oc in outcomes:
                self._persist_outcome_to_repo(oc)

        return batch, floor_result

    # ------------------------------------------------------------ persistence

    def _write_results_jsonl(self, batch: ReplayBatch, outcomes: list[ReplayOutcome]) -> None:
        """Atomic JSONL write — header line first, then one line per outcome."""
        self._results_dir.mkdir(parents=True, exist_ok=True)
        # ISO-8601 timestamp, filesystem-safe (colons replaced).
        stamp = batch.started_at.strftime("%Y%m%dT%H%M%SZ")
        out_path = self._results_dir / f"regression_{stamp}.jsonl"

        # Atomic write: build full content first, write to .tmp, then rename.
        lines: list[str] = []
        lines.append(json.dumps({"header": batch.model_dump(mode="json")}, ensure_ascii=False))
        for oc in outcomes:
            lines.append(json.dumps({"outcome": oc.model_dump(mode="json")}, ensure_ascii=False))
        content = "\n".join(lines) + "\n"

        tmp_path = out_path.with_suffix(".jsonl.tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, out_path)

    def _persist_outcome_to_repo(self, outcome: ReplayOutcome) -> None:
        """Update ``regression_cases.last_run_outcome`` + ``last_run_at`` for the
        replayed vr_id, if such a row exists. No-op when the case is not yet
        registered in the DB (e.g. first-run-before-curator-write paths).
        """
        if self._session_factory is None:
            return
        # Lazy import to avoid pulling SQLAlchemy in environments that only
        # consume the file-based regression machinery.
        from agentforge.memory.models import RegressionCase as RegressionCaseRow

        session = self._session_factory()
        try:
            row = (
                session.query(RegressionCaseRow)
                .filter(RegressionCaseRow.vr_id == outcome.vr_id)
                .one_or_none()
            )
            if row is None:
                # Insert a stub row so subsequent runs can update it. We mark
                # what_bug_this_catches with the vr_id as a placeholder; the
                # curator owns the canonical row creation.
                row = RegressionCaseRow(
                    id=str(uuid.uuid4()),
                    vr_id=outcome.vr_id,
                    what_bug_this_catches=f"auto-stub for {outcome.vr_id}",
                    case_json="{}",
                    last_run_at=outcome.timestamp,
                    last_run_outcome=outcome.observed_outcome,
                )
                session.add(row)
            else:
                row.last_run_at = outcome.timestamp
                row.last_run_outcome = outcome.observed_outcome
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


__all__ = ["RegressionRunner"]
