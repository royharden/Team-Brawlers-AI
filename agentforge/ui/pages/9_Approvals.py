"""Approval Queue page — sub-plan Next03 §5 + Next04 (POST wiring).

Reads ``GET /v1/approval/queue`` and POSTs to
``/v1/approval/{vr_id}/{approve,reject,dismiss}``. The queue line is
rewritten in place with a ``review`` block carrying status + reviewer +
timestamp; the page surfaces the review state on each item so a second
visit shows what's already been triaged.
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


def _do_action(action: str, vr_id: str, client: AgentForgeClient) -> None:
    """Call the matching POST endpoint and st.rerun() the page on success."""
    method = {"approve": client.approve, "reject": client.reject, "dismiss": client.dismiss}[action]
    try:
        method(vr_id)
    except Exception as exc:
        st.error(f"{action} failed for {vr_id}: {exc}")
        return
    st.success(f"{vr_id}: {action}d")
    st.rerun()


def render() -> None:
    st.title("Approval Queue")
    st.caption(
        "High+/Critical findings that landed in `data/notifier_queue.jsonl` "
        "during a campaign. Approve / Reject / Dismiss stamps a `review` block "
        "on the queue line — visible on the next page load."
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

    # Split pending vs reviewed for cleaner display.
    pending: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    for item in items:
        review = (item.get("payload") or {}).get("review")
        (reviewed if review else pending).append(item)

    st.write(f"**{len(pending)} pending · {len(reviewed)} reviewed**")

    if pending:
        st.subheader("Pending")
        for idx, item in enumerate(pending):
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

            col_a, col_r, col_d, _ = st.columns([1, 1, 1, 4])
            if col_a.button("Approve", key=f"approve_{idx}_{vr_id}", type="primary"):
                _do_action("approve", vr_id, client)
            if col_r.button("Reject", key=f"reject_{idx}_{vr_id}"):
                _do_action("reject", vr_id, client)
            if col_d.button("Dismiss", key=f"dismiss_{idx}_{vr_id}"):
                _do_action("dismiss", vr_id, client)

    if reviewed:
        st.subheader("Reviewed (history)")
        for item in reviewed:
            vr_id = item.get("vr_id") or "?"
            review = (item.get("payload") or {}).get("review") or {}
            status = review.get("status", "?")
            reviewer = review.get("reviewer", "?")
            reviewed_at = review.get("reviewed_at", "?")
            st.write(f"- **{vr_id}** — {status} by {reviewer} at `{reviewed_at}`")


render()
