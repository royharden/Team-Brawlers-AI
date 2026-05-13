"""Defense Delta Score — master plan §4 / §12 / §14 Phase 6.

Snapshot of the coverage aggregates per target fingerprint. Drives the
CISO-watchable trend line + Phase-6 before/after fix comparison.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

from agentforge.memory.models import DefenseDeltaSnapshot as _SnapshotRow
from agentforge.orchestrator.coverage import CoverageMatrix


class DefenseDeltaSnapshot(BaseModel):
    """One per-fingerprint snapshot of the coverage matrix aggregates."""

    target_fingerprint: str
    snapshot_at: datetime
    aggregate_pass_rate: float
    by_cell: dict[str, float] = Field(default_factory=dict)


class DefenseDelta:
    """Master plan §4 + §12 + §14 Phase 6.

    Aggregates the coverage matrix into a single fingerprint-tagged snapshot
    so the dashboard can plot the resilience trend over time and so Phase-6
    fix-validation can compute (post-fix − pre-fix) per cell.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        coverage: CoverageMatrix,
    ) -> None:
        self._session_factory = session_factory
        self._coverage = coverage

    # ----------------------------------------------------------------- ops

    def snapshot(self, target_fingerprint: str) -> DefenseDeltaSnapshot:
        """Compute the snapshot from the current coverage matrix and persist it."""
        cells = self._coverage.snapshot()
        by_cell: dict[str, float] = {}
        total_decided = 0
        total_passed = 0
        for c in cells:
            key = f"{c.category}:{c.strategy}"
            decided = c.passes + c.failures
            if decided == 0:
                # Empty cells do not contribute to the aggregate.
                continue
            pass_rate = c.passes / decided
            by_cell[key] = pass_rate
            total_decided += decided
            total_passed += c.passes

        aggregate = (total_passed / total_decided) if total_decided > 0 else 0.0
        snapshot_at = datetime.now(timezone.utc)

        session = self._session_factory()
        try:
            row = _SnapshotRow(
                fingerprint=target_fingerprint,
                snapshot_at=snapshot_at,
                aggregate_pass_rate=aggregate,
                by_cell_json=json.dumps(by_cell, sort_keys=True),
            )
            session.add(row)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        return DefenseDeltaSnapshot(
            target_fingerprint=target_fingerprint,
            snapshot_at=snapshot_at,
            aggregate_pass_rate=aggregate,
            by_cell=by_cell,
        )

    def trend(self, last_n: int = 10) -> list[DefenseDeltaSnapshot]:
        """Most-recent first."""
        session = self._session_factory()
        try:
            rows = (
                session.query(_SnapshotRow)
                .order_by(_SnapshotRow.snapshot_at.desc(), _SnapshotRow.id.desc())
                .limit(last_n)
                .all()
            )
            out = [
                DefenseDeltaSnapshot(
                    target_fingerprint=r.fingerprint,
                    snapshot_at=r.snapshot_at,
                    aggregate_pass_rate=r.aggregate_pass_rate or 0.0,
                    by_cell=json.loads(r.by_cell_json or "{}"),
                )
                for r in rows
            ]
        finally:
            session.close()
        return out

    def delta(self, fp_a: str, fp_b: str) -> dict[str, float]:
        """Per-cell (b − a) pass-rate difference using each fingerprint's
        most-recent snapshot. Cells absent from either side default to 0."""
        snap_a = self._latest_for(fp_a)
        snap_b = self._latest_for(fp_b)
        keys = set(snap_a.by_cell.keys()) | set(snap_b.by_cell.keys())
        return {
            key: snap_b.by_cell.get(key, 0.0) - snap_a.by_cell.get(key, 0.0)
            for key in sorted(keys)
        }

    # ----------------------------------------------------------------- utils

    def _latest_for(self, fingerprint: str) -> DefenseDeltaSnapshot:
        session = self._session_factory()
        try:
            row = (
                session.query(_SnapshotRow)
                .filter_by(fingerprint=fingerprint)
                .order_by(_SnapshotRow.snapshot_at.desc(), _SnapshotRow.id.desc())
                .first()
            )
            if row is None:
                return DefenseDeltaSnapshot(
                    target_fingerprint=fingerprint,
                    snapshot_at=datetime.now(timezone.utc),
                    aggregate_pass_rate=0.0,
                    by_cell={},
                )
            return DefenseDeltaSnapshot(
                target_fingerprint=row.fingerprint,
                snapshot_at=row.snapshot_at,
                aggregate_pass_rate=row.aggregate_pass_rate or 0.0,
                by_cell=json.loads(row.by_cell_json or "{}"),
            )
        finally:
            session.close()


__all__ = ["DefenseDelta", "DefenseDeltaSnapshot"]
