"""Approval Queue page — sub-plan Next03 §5.

Reads ``GET /v1/approval/queue`` (already implemented at
``agentforge/api/routes_approval.py``). The Approve / Reject endpoints
return 501 today — the buttons are wired but disabled with a tooltip
explaining the deferred state. Useful for the demo storyline ("here's the
human-in-the-loop queue an operator would triage").
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import severity_badge


def _badge_for_kind(kind: str) -> str:
    """Map approval-queue `kind` strings to a severity tier for the badge."""
    kind_lower = (kind or "").lower()
    if "critical" in kind_lower:
        return "critical"
    if "high" in kind_lower:
        return "high"
    if "medium" in kind_lower:
        return "medium"
    return "info"


def render() -> None:
    st.title("Approval Queue")
    st.caption(
        "High+/Critical findings that landed in `data/notifier_queue.jsonl` "
        "during a campaign. Approve / Reject endpoints are deferred (501) — "
        "see Plan_wk3_Claude_Next03 §5."
    )

    client = AgentForgeClient()
    try:
        payload = client.approval_queue()
    except Exception as exc:
        st.error(f"queue unavailable: {exc}")
        return

    items: list[dict[str, Any]] = payload.get("items") or []
    if not items:
        st.info("No queued findings — the campaign is clean (or hasn't run yet).")
        return

    st.write(f"**{len(items)} pending**")

    for idx, item in enumerate(items):
        vr_id = item.get("vr_id") or "?"
        kind = item.get("kind") or "unknown"
        bg, fg = severity_badge(_badge_for_kind(kind))
        st.markdown(
            f"<div style='background:{bg};color:{fg};padding:6px 12px;"
            f"border-radius:6px;display:inline-block;margin-bottom:4px;'>"
            f"<b>{vr_id}</b> — {kind}</div>",
            unsafe_allow_html=True,
        )
        payload_body = item.get("payload") or {}
        if isinstance(payload_body, dict) and payload_body:
            with st.expander(f"Payload — {vr_id}", expanded=False):
                st.json(payload_body)

        col_a, col_r, _ = st.columns([1, 1, 4])
        col_a.button(
            "Approve",
            key=f"approve_{idx}_{vr_id}",
            disabled=True,
            help="POST /v1/approval/{vr_id}/approve is 501 (deferred). See Next03 §5.",
        )
        col_r.button(
            "Reject",
            key=f"reject_{idx}_{vr_id}",
            disabled=True,
            help="POST /v1/approval/{vr_id}/reject is 501 (deferred). See Next03 §5.",
        )


render()
