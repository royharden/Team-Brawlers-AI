"""/v1/judge routes — judge meta-eval recompute (sub-plan Next03 §3.4).

POST /v1/judge/recompute kicks the meta-eval runner against the gold set
and refreshes ``evals/meta_eval/judge_<layer>_v1_metrics.json`` — the same
file the JudgeMeta UI page reads. The runner uses the deterministic-only
judge path by default (no live LLM call), so the route is cheap (~hundreds
of milliseconds for v1's gold set) and safe to expose as a synchronous
endpoint.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

router = APIRouter()


@router.post("/judge/recompute")
def recompute_judge_meta(
    layer: Literal["external_final", "internal_progress"] = Query(
        default="external_final",
        description="Judge layer to meta-evaluate.",
    ),
) -> dict[str, Any]:
    """Re-run the meta-eval runner and return the resulting metrics dict.

    Raises 503 if the meta-eval module isn't available (defensive — it
    shipped in Phase 6, but keep the import lazy so an environment without
    it still serves the rest of the API).
    """
    try:
        from agentforge.judge.meta_eval.runner import run_meta_eval
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"meta-eval module unavailable: {exc}",
        ) from exc

    try:
        metrics = run_meta_eval(layer=layer)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"meta-eval gold set unavailable: {exc}",
        ) from exc
    except Exception as exc:
        logger.warning("judge recompute failed: {}", exc)
        raise HTTPException(
            status_code=500,
            detail=f"meta-eval run failed: {exc}",
        ) from exc

    try:
        return {"layer": layer, "metrics": metrics.model_dump()}
    except AttributeError:
        # Defensive — older JudgeMetrics implementations may not have
        # model_dump; fall back to dict() if available.
        if hasattr(metrics, "dict"):
            return {"layer": layer, "metrics": metrics.dict()}
        return {"layer": layer, "metrics": {}}
