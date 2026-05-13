"""Judge meta-eval page — master plan §10.

Shows precision / recall / F1 / Krippendorff α with floor-met badges and
a working **Recompute** button (sub-plan Next03 §3.4) that POSTs to
``/v1/judge/recompute`` and refreshes the page on success.

Sub-plan Next04 added the layer selector — the page reads + recomputes
either ``external_final`` or ``internal_progress`` from the same UI.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient

# Repo root: agentforge/ui/pages/6_JudgeMeta.py -> parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_META_DIR = _REPO_ROOT / "evals" / "meta_eval"


def _meta_path(layer: str) -> Path:
    return _META_DIR / f"judge_{layer}_v1_metrics.json"


def _load_metrics(layer: str) -> dict:
    path = _meta_path(layer)
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def render() -> None:
    st.title("Judge Meta-Eval")

    layer = st.selectbox(
        "Judge layer",
        options=["external_final", "internal_progress"],
        index=0,
        help="external_final = the binding rubric judge (Sonnet). internal_progress = the fast Haiku judge used for branch pruning.",
    )

    data = _load_metrics(layer)
    if not data:
        st.warning(f"No meta-eval data found at {_meta_path(layer)}. Run Recompute below.")
    else:
        metrics = data.get("metrics") or {}
        floor = data.get("floor") or {}
        floor_met = metrics.get("floor_met") or {}

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Precision", f"{metrics.get('precision', 0):.3f}")
        c2.metric("Recall", f"{metrics.get('recall', 0):.3f}")
        c3.metric("F1", f"{metrics.get('f1', 0):.3f}")
        c4.metric("Krippendorff α", f"{metrics.get('krippendorff_alpha', 0):.3f}")

        st.subheader("Floor met")
        for k in ("precision", "recall", "f1"):
            ok = bool(floor_met.get(k))
            threshold = floor.get(k)
            msg = f"{k}: floor={threshold} | met={ok}"
            (st.success if ok else st.error)(msg)

    if st.button(f"Recompute {layer}", type="primary"):
        client = AgentForgeClient()
        try:
            with st.spinner(f"Re-running meta-eval ({layer}) against the gold set..."):
                client.recompute_judge_meta(layer=layer)
        except Exception as exc:
            st.error(f"recompute failed: {exc}")
            return
        st.success("Meta-eval recomputed. Refreshing...")
        st.rerun()


render()
