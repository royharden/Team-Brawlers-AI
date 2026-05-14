"""Backfill ``attack_traces.attack_id`` for pre-Next05§2 rows — Next06 §4.

Closes AgDR-0026 follow-on #1. Before migration 0002 added
``attack_traces.attack_id``, the orchestrator embedded the agent-level
attack id in ``target_request_json["trace_id"]``. Post-migration rows
have ``attack_id`` populated directly. This script walks the pre-
migration rows (``attack_id IS NULL``) and derives the missing column
from the JSON blob — so the AttackLineage page's DB-walk path can
resolve trees that span the migration cutover.

The script is idempotent: re-running it on an already-backfilled DB
does nothing. Rows whose ``target_request_json`` lacks a ``trace_id``
are reported but not updated.

Usage:
    python scripts/backfill_attack_id.py
    python scripts/backfill_attack_id.py --dry-run

Exit codes:
    0 — success (rows updated reported in stdout JSON).
    1 — unexpected error during backfill (DB connection, schema mismatch).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the repo root importable when run directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from loguru import logger  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from agentforge.memory.db import get_session_factory  # noqa: E402
from agentforge.memory.models import AttackTrace  # noqa: E402


def _trace_id_from_request_json(raw: str | None) -> str | None:
    """Parse `target_request_json` and return its `trace_id` field.

    The orchestrator wrote `target_request_json["trace_id"] = attack.attack_id`
    long before the migration. Defensive against malformed JSON / missing key.
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    val = parsed.get("trace_id")
    if val is None:
        return None
    return str(val)


def backfill_attack_ids(
    session_factory: sessionmaker[Session],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Walk `attack_traces` rows with `attack_id IS NULL` and populate
    them from `target_request_json["trace_id"]`.

    Returns a stats dict: `{scanned, updated, no_trace_id_in_json}`.
    """
    stats = {"scanned": 0, "updated": 0, "no_trace_id_in_json": 0}
    session = session_factory()
    try:
        rows = session.scalars(select(AttackTrace).where(AttackTrace.attack_id.is_(None))).all()
        for row in rows:
            stats["scanned"] += 1
            derived = _trace_id_from_request_json(row.target_request_json)
            if derived is None:
                stats["no_trace_id_in_json"] += 1
                continue
            row.attack_id = derived
            stats["updated"] += 1
        if not dry_run:
            session.commit()
        else:
            session.rollback()
    finally:
        session.close()
    return stats


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be updated without writing.",
    )
    args = parser.parse_args()

    try:
        session_factory = get_session_factory()
    except Exception as exc:
        logger.error("Failed to acquire session factory: {}", exc)
        return 1

    stats = backfill_attack_ids(session_factory, dry_run=args.dry_run)
    summary: dict[str, Any] = {"dry_run": args.dry_run, **stats}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
