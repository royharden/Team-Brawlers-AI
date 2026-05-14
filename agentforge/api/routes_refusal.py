"""/v1/refusal-rate route — sub-plan Next05 §5 + Next06 §2.

Computes refusal rate from attack traces by running the deterministic
refusal-marker detector
(``agentforge.judge.deterministic.refusal_taxonomy.detect_refusal``)
over each trace's stored ``target_response_json.body_text_preview``
(orchestrator persists a 512-char preview).

Refusal here = the *target* (Co-Pilot under test) declined the attack —
the defense working as designed. Useful for the demo storyline: the
operator sees at-a-glance that their hardening efforts are landing.

Next06 §2 extensions over the original Next05 §5 shape:
  - ``?since=<iso8601>`` scopes the scan to a sliding window (e.g.
    "refusal rate over the last 24h").
  - ``?buckets=N`` returns a ``trend`` array with N evenly-spaced
    time buckets — feeds the Cost-tab line chart that catches
    defensive regressions visually.
  - ``by_mutator`` aggregates per individual mutator id across the
    ``mutator_chain_json`` column.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session

from agentforge.api.deps import get_session
from agentforge.api.responses import RefusalRateResponse, RefusalTrendBucket
from agentforge.config import get_settings
from agentforge.judge.deterministic.refusal_taxonomy import detect_refusal
from agentforge.judge.llm_refusal_classifier import classify_refusal
from agentforge.memory.models import AttackJob, AttackTrace

router = APIRouter()


def _body_text(trace: AttackTrace) -> str:
    """Pull the response body preview from the trace's persisted JSON."""
    raw = trace.target_response_json or "{}"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    body = parsed.get("body_text_preview") or parsed.get("body_text") or ""
    return body if isinstance(body, str) else ""


def _build_llm_detector() -> Callable[[str], bool]:
    """Build a detector callable backed by Haiku, falling back to the
    deterministic detector when the Anthropic key isn't configured.

    Constructs an SDK client once per request — the route handler holds
    the closure for the duration of the scan, so we avoid re-init cost
    when the operator hits a 1000-row Cost-tab refresh with detector=llm.
    """
    cfg = get_settings()
    if not cfg.anthropic.api_key:
        logger.warning(
            "detector=llm requested but ANTHROPIC_API_KEY is not set — "
            "falling back to deterministic detector"
        )

        def _deterministic_only(body_text: str) -> bool:
            return detect_refusal(body_text) is not None

        return _deterministic_only

    try:
        import anthropic

        sdk_client = anthropic.Anthropic(api_key=cfg.anthropic.api_key)
    except Exception as exc:  # broad: covers missing dep + auth-time errors
        logger.warning("detector=llm could not init Anthropic SDK: {}", exc)

        def _deterministic_after_init_fail(body_text: str) -> bool:
            return detect_refusal(body_text) is not None

        return _deterministic_after_init_fail

    model = cfg.anthropic.fast_model

    def _llm_detect(body_text: str) -> bool:
        if not body_text:
            return False
        verdict = classify_refusal(body_text, client=sdk_client, model=model)
        return verdict.is_refusal

    return _llm_detect


def _refused(trace: AttackTrace, *, detector: Callable[[str], bool]) -> bool:
    """Apply the active detector to the trace's response body."""
    body = _body_text(trace)
    if not body:
        return False
    return detector(body)


def _mutators_in_trace(trace: AttackTrace) -> list[str]:
    """Parse `mutator_chain_json` defensively → list of mutator ids."""
    raw = trace.mutator_chain_json or "[]"
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(m) for m in parsed if m]


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp; accept both naive (UTC-assumed) and
    timezone-aware. Raises HTTPException 400 on bad input so the FastAPI
    error message points the operator at the offending query string."""
    try:
        # `fromisoformat` accepts "Z" since 3.11.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid `since` (not ISO-8601): {value!r}",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _compute_trend(
    rows: Sequence[Any],
    *,
    buckets: int,
    window_start: datetime,
    window_end: datetime,
    detector: Callable[[str], bool],
) -> list[RefusalTrendBucket]:
    """Bucket the rows into `buckets` evenly-spaced windows between
    `window_start` and `window_end` and compute refusal rate per bucket.

    Buckets are half-open `[start, end)` except the last which is closed
    so the most-recent row always lands somewhere. Empty buckets carry
    `n_attacks=0` and `refusal_rate=0.0` — a flat zero-line in the chart
    is a deliberate visual signal that the operator had no activity
    during that window, not an outage.
    """
    if buckets <= 0:
        return []
    total = window_end - window_start
    if total.total_seconds() <= 0:
        return []
    width = total / buckets

    out: list[RefusalTrendBucket] = []
    bucket_indices: list[tuple[int, int]] = [(0, 0) for _ in range(buckets)]

    for trace, job in rows:
        created_at = job.created_at
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        if created_at < window_start or created_at > window_end:
            continue
        offset = created_at - window_start
        # Compute bucket index. Clamp to last bucket on the right edge.
        idx = min(int(offset / width), buckets - 1)
        n, r = bucket_indices[idx]
        n += 1
        if _refused(trace, detector=detector):
            r += 1
        bucket_indices[idx] = (n, r)

    for i in range(buckets):
        bucket_start = window_start + width * i
        bucket_end = bucket_start + width
        n, r = bucket_indices[i]
        rate = (r / n) if n else 0.0
        out.append(
            RefusalTrendBucket(
                bucket_start=bucket_start,
                bucket_end=bucket_end,
                n_attacks=n,
                n_refusals=r,
                refusal_rate=rate,
            )
        )
    return out


@router.get("/refusal-rate", response_model=RefusalRateResponse)
def get_refusal_rate(
    last: int = Query(default=100, ge=1, le=1000),
    since: str | None = Query(default=None),
    buckets: int = Query(default=0, ge=0, le=48),
    detector: str = Query(default="deterministic", pattern="^(deterministic|llm)$"),
    session: Session = Depends(get_session),
) -> RefusalRateResponse:
    """Refusal-rate aggregate over recent attack traces.

    Query params:
      - `last` (default 100) — caps the slice to most-recent N.
      - `since` (optional, ISO 8601) — sliding-window filter; when both
        `since` and `last` are set, `since` is the dominant filter.
      - `buckets` (optional, 1–48) — when set, also return a `trend`
        array with N evenly-spaced time buckets between the earliest
        and latest scanned attack (or `since`..now if `since` is set).
      - `detector` — `deterministic` (default, free regex-marker scan)
        or `llm` (Haiku-backed classifier, Next06 §3, catches
        non-canonical refusals the regex misses; falls back to
        deterministic when no ANTHROPIC_API_KEY).
    """
    since_dt: datetime | None = _parse_iso(since) if since else None

    detector_fn: Callable[[str], bool]
    if detector == "llm":
        detector_fn = _build_llm_detector()
    else:

        def _deterministic(body_text: str) -> bool:
            return detect_refusal(body_text) is not None

        detector_fn = _deterministic

    q = (
        session.query(AttackTrace, AttackJob)
        .join(AttackJob, AttackJob.id == AttackTrace.attack_job_id)
        .order_by(AttackJob.created_at.desc(), AttackJob.id.desc())
    )
    if since_dt is not None:
        # AttackJob.created_at is stored naive (DateTime column without
        # timezone). Compare against the naive UTC equivalent so SQLite
        # equality works across timezone-aware filter input.
        q = q.filter(AttackJob.created_at >= since_dt.replace(tzinfo=None))
    rows = q.limit(last).all()

    total = 0
    refusals = 0
    by_cat_total: dict[str, int] = defaultdict(int)
    by_cat_refusals: dict[str, int] = defaultdict(int)
    by_strat_total: dict[str, int] = defaultdict(int)
    by_strat_refusals: dict[str, int] = defaultdict(int)
    by_mut_total: dict[str, int] = defaultdict(int)
    by_mut_refusals: dict[str, int] = defaultdict(int)
    for trace, job in rows:
        total += 1
        is_refusal = _refused(trace, detector=detector_fn)
        by_cat_total[job.category] += 1
        by_strat_total[job.strategy] += 1
        for mut in _mutators_in_trace(trace):
            by_mut_total[mut] += 1
            if is_refusal:
                by_mut_refusals[mut] += 1
        if is_refusal:
            refusals += 1
            by_cat_refusals[job.category] += 1
            by_strat_refusals[job.strategy] += 1

    rate = (refusals / total) if total else 0.0
    by_category = {cat: (by_cat_refusals[cat] / by_cat_total[cat]) for cat in by_cat_total}
    by_strategy = {
        strat: (by_strat_refusals[strat] / by_strat_total[strat]) for strat in by_strat_total
    }
    by_mutator = {mut: (by_mut_refusals[mut] / by_mut_total[mut]) for mut in by_mut_total}

    trend: list[RefusalTrendBucket] | None = None
    if buckets > 0 and rows:
        # Window: from `since` (or earliest scanned row's created_at) to now.
        now = datetime.now(UTC)
        earliest_naive = min(
            (j.created_at for _, j in rows if j.created_at is not None),
            default=None,
        )
        if earliest_naive is None:
            window_start = now - timedelta(hours=1)
        else:
            earliest_aware = (
                earliest_naive.replace(tzinfo=UTC)
                if earliest_naive.tzinfo is None
                else earliest_naive
            )
            window_start = since_dt or earliest_aware
        # Guarantee a non-zero width even when all rows share a timestamp.
        if (now - window_start).total_seconds() <= 0:
            window_start = now - timedelta(seconds=buckets)
        trend = _compute_trend(
            rows,
            buckets=buckets,
            window_start=window_start,
            window_end=now,
            detector=detector_fn,
        )

    return RefusalRateResponse(
        n_attacks_scanned=total,
        n_refusals=refusals,
        refusal_rate=rate,
        by_category=by_category,
        by_strategy=by_strategy,
        by_mutator=by_mutator,
        trend=trend,
        detector=detector,
    )
