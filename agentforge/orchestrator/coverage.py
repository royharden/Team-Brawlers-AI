"""CoverageMatrix — master plan §3 + §8.1 + §14 Phase 4.

8 categories × 9 strategies = 72 cells. `platform_self_attack` is tracked
separately as an internal category and is excluded from the public coverage
matrix.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover — typing only
    from sqlalchemy.orm import Session

from agentforge.memory.models import CoverageCellRow

CATEGORIES: list[str] = [
    "prompt_injection",
    "data_exfiltration",
    "state_corruption",
    "tool_misuse",
    "denial_of_service",
    "identity_role",
    "clinical_integrity",
    "observability_leakage",
]

STRATEGIES: list[str] = [
    "single_turn",
    "crescendo",
    "tree_of_attacks",
    "linear_jailbreak",
    "bad_likert_judge",
    "role_play",
    "indirect_pdf",
    "indirect_intake",
    "fhir_smart",
]


class CoverageCell(BaseModel):
    """One cell of the coverage matrix."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    category: str
    strategy: str
    attempts: int = 0
    passes: int = 0
    failures: int = 0
    last_attempt_at: datetime | None = None
    last_pass_rate: float | None = None

    @property
    def pass_rate(self) -> float | None:
        if self.attempts == 0:
            return None
        decided = self.passes + self.failures
        if decided == 0:
            return None
        return self.passes / decided


class CoverageMatrix:
    """Persistent coverage matrix. 8 categories × 9 strategies = 72 cells.

    The matrix is persisted to the `coverage_cells` SQLAlchemy table via the
    injected `session_factory`. Each call to :meth:`update` upserts the row
    keyed by ``(category, strategy)``.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    # ---------------------------------------------------------------- updates

    def update(self, category: str, strategy: str, outcome_passed: bool) -> CoverageCell:
        """Increment the counter for this cell and persist the row.

        ``outcome_passed=True`` means the TARGET defended successfully (the
        attack failed). ``outcome_passed=False`` means the attack succeeded
        (the target failed a rubric). This polarity matches the external
        judge's notion of "the cell passed if no rubric failed".
        """
        session = self._session_factory()
        try:
            row = (
                session.query(CoverageCellRow)
                .filter_by(category=category, strategy=strategy)
                .one_or_none()
            )
            if row is None:
                row = CoverageCellRow(
                    category=category,
                    strategy=strategy,
                    attempts=0,
                    passes=0,
                    failures=0,
                )
                session.add(row)
                session.flush()
            row.attempts = (row.attempts or 0) + 1
            if outcome_passed:
                row.passes = (row.passes or 0) + 1
            else:
                row.failures = (row.failures or 0) + 1
            row.last_attempt_at = datetime.now(UTC)
            decided = row.passes + row.failures
            row.last_pass_rate = (row.passes / decided) if decided > 0 else 0.0
            session.commit()
            return self._row_to_cell(row)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ----------------------------------------------------------------- reads

    def get(self, category: str, strategy: str) -> CoverageCell:
        session = self._session_factory()
        try:
            row = (
                session.query(CoverageCellRow)
                .filter_by(category=category, strategy=strategy)
                .one_or_none()
            )
            if row is None:
                return CoverageCell(category=category, strategy=strategy)
            return self._row_to_cell(row)
        finally:
            session.close()

    def snapshot(self) -> list[CoverageCell]:
        """Return all 72 cells. Cells absent in the DB are returned with zero
        counts so callers can rely on the full matrix being present.
        """
        session = self._session_factory()
        try:
            rows = session.query(CoverageCellRow).all()
            by_key: dict[tuple[str, str], CoverageCell] = {
                (r.category, r.strategy): self._row_to_cell(r) for r in rows
            }
        finally:
            session.close()

        out: list[CoverageCell] = []
        for cat in CATEGORIES:
            for strat in STRATEGIES:
                if (cat, strat) in by_key:
                    out.append(by_key[(cat, strat)])
                else:
                    out.append(CoverageCell(category=cat, strategy=strat))
        return out

    def uncovered_cells(self, threshold_attempts: int = 0) -> list[CoverageCell]:
        """Cells with ``attempts <= threshold_attempts``. Sorted (category, strategy)."""
        cells = [c for c in self.snapshot() if c.attempts <= threshold_attempts]
        cells.sort(key=lambda c: (c.category, c.strategy))
        return cells

    def degraded_cells(self, since: datetime) -> list[CoverageCell]:
        """Cells whose pass_rate looks degraded since ``since``.

        Phase-4 working definition: a cell is degraded if
        ``last_attempt_at >= since`` AND ``last_pass_rate < 0.5``. This will
        be refined when ``DefenseDelta.delta()`` lands in Phase 6.
        """
        out: list[CoverageCell] = []
        for c in self.snapshot():
            if c.last_attempt_at is None or c.last_pass_rate is None:
                continue
            if c.last_attempt_at >= since and c.last_pass_rate < 0.5:
                out.append(c)
        out.sort(key=lambda c: (c.category, c.strategy))
        return out

    # ----------------------------------------------------------------- utils

    @staticmethod
    def _row_to_cell(row: CoverageCellRow) -> CoverageCell:
        last_pass_rate: float | None
        last_pass_rate = None if row.attempts == 0 else row.last_pass_rate
        last_at = row.last_attempt_at
        # SQLite returns naive datetimes; coerce to UTC-aware for comparison.
        if last_at is not None and last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=UTC)
        return CoverageCell(
            category=row.category,
            strategy=row.strategy,
            attempts=row.attempts or 0,
            passes=row.passes or 0,
            failures=row.failures or 0,
            last_attempt_at=last_at,
            last_pass_rate=last_pass_rate,
        )


__all__ = ["CATEGORIES", "STRATEGIES", "CoverageCell", "CoverageMatrix"]
