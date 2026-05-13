"""/v1/refusal-rate route — sub-plan Next05 §5.

Computes refusal rate from the most-recent N attack traces by running
the deterministic refusal-marker detector
(``agentforge.judge.deterministic.refusal_taxonomy.detect_refusal``)
over each trace's stored ``target_response_json.body_text_preview``
(orchestrator persists a 512-char preview).

Refusal here = the *target* (Co-Pilot under test) declined the attack —
which is the defense working as designed. Useful for the demo storyline:
operators can see at-a-glance that their hardening efforts are landing.
"""

from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import RefusalRateResponse
from agentforge.judge.deterministic.refusal_taxonomy import detect_refusal
from agentforge.memory.models import AttackJob, AttackTrace

router = APIRouter()


def _refused(trace: AttackTrace) -> bool:
    """True if the trace's target_response shows a refusal marker."""
    raw = trace.target_response_json or "{}"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    body = parsed.get("body_text_preview") or parsed.get("body_text") or ""
    if not isinstance(body, str) or not body:
        return False
    return detect_refusal(body) is not None


@router.get("/refusal-rate", response_model=RefusalRateResponse)
def get_refusal_rate(
    last: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> RefusalRateResponse:
    """Refusal-rate aggregate over the most-recent ``last`` attack traces.

    Joins ``attack_traces`` × ``attack_jobs`` so we can break down by
    category + strategy. The detector is the same deterministic taxonomy
    the Red Team's `paraphrase` path uses for `refusal_observed`.
    """
    rows = (
        session.query(AttackTrace, AttackJob)
        .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
        .order_by(AttackJob.created_at.desc(), AttackJob.id.desc())
        .limit(last)
        .all()
    )

    total = 0
    refusals = 0
    by_cat_total: dict[str, int] = defaultdict(int)
    by_cat_refusals: dict[str, int] = defaultdict(int)
    by_strat_total: dict[str, int] = defaultdict(int)
    by_strat_refusals: dict[str, int] = defaultdict(int)
    for trace, job in rows:
        total += 1
        is_refusal = _refused(trace)
        by_cat_total[job.category] += 1
        by_strat_total[job.strategy] += 1
        if is_refusal:
            refusals += 1
            by_cat_refusals[job.category] += 1
            by_strat_refusals[job.strategy] += 1

    rate = (refusals / total) if total else 0.0
    by_category = {cat: (by_cat_refusals[cat] / by_cat_total[cat]) for cat in by_cat_total}
    by_strategy = {
        strat: (by_strat_refusals[strat] / by_strat_total[strat]) for strat in by_strat_total
    }
    return RefusalRateResponse(
        n_attacks_scanned=total,
        n_refusals=refusals,
        refusal_rate=rate,
        by_category=by_category,
        by_strategy=by_strategy,
    )
