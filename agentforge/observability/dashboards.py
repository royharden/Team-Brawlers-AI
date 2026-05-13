"""Dashboard data shaping helpers — master plan §12.

Cross-cutting helpers used by both the FastAPI routes and the Streamlit
pages. Pure session/data shaping — no Streamlit / no FastAPI imports — so
this module is safe to import from either side.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from agentforge.memory.models import CostLedgerEntry, DefenseDeltaSnapshot
from agentforge.orchestrator.coverage import CATEGORIES, STRATEGIES


def aggregate_run_costs(
    session: Session,
    *,
    since_date: date | None = None,
) -> dict[str, Any]:
    """Roll up the ``cost_ledger`` table.

    Returns a dict with keys::

        {
            "total":   Decimal,         # USD across all matching rows
            "n_calls": int,             # row count
            "by_role": {role: Decimal}, # grouped sum per agent_role
        }

    When ``since_date`` is given, only rows with ``timestamp >= since_date``
    (UTC midnight) are aggregated — used by the ``/v1/cost/today`` endpoint.
    """
    q = session.query(
        CostLedgerEntry.agent_role,
        func.coalesce(func.sum(CostLedgerEntry.cost_usd), 0),
        func.count(CostLedgerEntry.id),
    )
    if since_date is not None:
        floor = datetime.combine(since_date, time.min).replace(tzinfo=timezone.utc)
        # SQLite stores naive datetimes; compare against naive too.
        q = q.filter(CostLedgerEntry.timestamp >= floor.replace(tzinfo=None))
    rows = q.group_by(CostLedgerEntry.agent_role).all()

    by_role: dict[str, Decimal] = {}
    total = Decimal("0")
    n_calls = 0
    for role, sum_val, cnt in rows:
        amt = sum_val if isinstance(sum_val, Decimal) else Decimal(str(sum_val))
        by_role[str(role)] = amt
        total = total + amt
        n_calls += int(cnt or 0)
    return {"total": total, "n_calls": n_calls, "by_role": by_role}


def coverage_pct(matrix: list[dict[str, Any]]) -> float:
    """Percent of the 72-cell matrix with ``attempts > 0``.

    ``matrix`` is a list of dicts with at least an ``attempts`` field. The
    denominator is always ``len(CATEGORIES) * len(STRATEGIES) == 72`` — sparse
    inputs count missing cells as uncovered.
    """
    total_cells = len(CATEGORIES) * len(STRATEGIES)
    if total_cells == 0:
        return 0.0
    covered = sum(1 for row in matrix if int(row.get("attempts") or 0) > 0)
    return (covered / total_cells) * 100.0


def recent_fingerprints(session: Session, limit: int = 5) -> list[str]:
    """Distinct target fingerprints from the most-recent snapshots.

    Most-recent first. Duplicates are filtered (we want unique fingerprints
    in observed order); the function inspects at most ``limit * 10`` rows so
    a flood of one fingerprint can't starve older ones.
    """
    rows = (
        session.query(DefenseDeltaSnapshot.fingerprint)
        .order_by(
            DefenseDeltaSnapshot.snapshot_at.desc(), DefenseDeltaSnapshot.id.desc()
        )
        .limit(max(limit * 10, limit))
        .all()
    )
    out: list[str] = []
    seen: set[str] = set()
    for (fp,) in rows:
        if fp in seen:
            continue
        seen.add(fp)
        out.append(fp)
        if len(out) >= limit:
            break
    return out


# --- Legacy stub (preserved for any older imports) ----------------------------


def shape_coverage_matrix(rows: list[Any]) -> list[dict[str, Any]]:
    """Light shape helper: pass-through with row.attempts surfaced."""
    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append(
                {
                    "category": getattr(r, "category", None),
                    "strategy": getattr(r, "strategy", None),
                    "attempts": getattr(r, "attempts", 0),
                    "passes": getattr(r, "passes", 0),
                    "failures": getattr(r, "failures", 0),
                    "last_pass_rate": getattr(r, "last_pass_rate", None),
                }
            )
    return out


__all__ = [
    "aggregate_run_costs",
    "coverage_pct",
    "recent_fingerprints",
    "shape_coverage_matrix",
]
