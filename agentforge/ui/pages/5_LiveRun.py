"""LiveRun page — sub-plan Next05 §1.

Operator clicks **Start campaign** → page POSTs `/v1/runs/start` → polls
`/v1/runs/{run_id}/state` every ~1.5s until terminal state. Dashboard
totals + cost auto-refresh alongside.

Streamlit can't easily consume SSE, so this page polls. The same
`/v1/runs/{run_id}/stream` SSE endpoint is available for `curl` / non-
Streamlit consumers (per the demo storyline).
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient

_TERMINAL_STATES = {"completed", "failed", "halted"}
_POLL_INTERVAL_S = 1.5


def _state_badge(status: str) -> str:
    color_map = {
        "pending": "#525252",
        "running": "#1d4ed8",
        "completed": "#15803d",
        "halted": "#b45309",
        "failed": "#b91c1c",
    }
    bg = color_map.get(status, "#525252")
    return (
        f"<span style='background:{bg};color:#fff;padding:4px 10px;"
        f"border-radius:6px;font-weight:600;'>{status.upper()}</span>"
    )


def _render_dashboard_strip(client: AgentForgeClient) -> None:
    """Live dashboard totals so the operator sees the campaign tick."""
    try:
        dash = client.get_dashboard()
    except Exception as exc:
        st.error(f"dashboard unavailable: {exc}")
        return
    totals = dash.get("totals", {})
    cov = dash.get("coverage_summary", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs", totals.get("runs", 0))
    c2.metric("Attacks", totals.get("attacks", 0))
    c3.metric("Coverage", f"{cov.get('covered_cells', 0)}/{cov.get('total_cells', 72)}")
    c4.metric("Spend (USD)", str(totals.get("spend_usd", "0"))[:8])


def _render_run_state(state: dict[str, Any]) -> None:
    status = state.get("status", "?")
    st.markdown(_state_badge(status), unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Attacks executed", int(state.get("attacks_executed") or 0))
    c2.metric("Findings written", int(state.get("findings_written") or 0))
    c3.metric("Halted?", "yes" if state.get("halted") else "no")
    if state.get("halt_reason"):
        st.warning(f"Halt reason: `{state['halt_reason']}`")
    if state.get("error"):
        st.error(f"Error: `{state['error']}`")
    started = state.get("started_at")
    finished = state.get("finished_at")
    if started:
        st.caption(f"started {started}{' · finished ' + finished if finished else ''}")


def render() -> None:
    st.title("Live Run")
    st.caption(
        "Fire a campaign from the UI; polling refreshes every ~1.5s until terminal "
        "state. Server-Sent Events also available at "
        "`/v1/runs/{run_id}/stream` for `curl` / non-Streamlit consumers."
    )
    client = AgentForgeClient()

    # --- Start controls ---
    if "live_run_id" not in st.session_state:
        st.session_state["live_run_id"] = None

    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
    run_type = c1.selectbox(
        "Run type",
        options=["smoke", "seeded", "exploratory"],
        index=0,
    )
    count = c2.number_input("Count", min_value=1, max_value=10, value=1)
    if c3.button(
        "Start campaign",
        type="primary",
        disabled=bool(st.session_state["live_run_id"]),
    ):
        try:
            resp = client.start_run(run_type=run_type, count=int(count))
            st.session_state["live_run_id"] = resp.get("run_id")
            st.success(f"Started run `{resp.get('run_id', '?')[:8]}`...")
        except Exception as exc:
            st.error(f"start failed: {exc}")
    if c4.button("Clear", disabled=not st.session_state["live_run_id"]):
        st.session_state["live_run_id"] = None
        st.rerun()

    st.divider()
    st.subheader("Dashboard")
    _render_dashboard_strip(client)

    rid = st.session_state.get("live_run_id")
    if not rid:
        st.info(
            "Click **Start campaign** above to fire one orchestrator step "
            "against the live sidecar. The dashboard ticks as the run progresses."
        )
        return

    # --- Poll the live state until terminal ---
    st.divider()
    st.subheader(f"Run `{rid[:8]}`")
    placeholder = st.empty()

    state: dict[str, Any] | None = None
    deadline = time.time() + 180  # safety: never poll for more than 3 min
    while time.time() < deadline:
        try:
            state = client.get_run_live_state(rid)
        except Exception as exc:
            st.error(f"state fetch failed: {exc}")
            return
        with placeholder.container():
            _render_run_state(state)
        if state.get("status") in _TERMINAL_STATES:
            break
        time.sleep(_POLL_INTERVAL_S)

    # Final-state render after the loop exits.
    if state is not None:
        with placeholder.container():
            _render_run_state(state)
    st.divider()
    st.subheader("Dashboard (post-run)")
    _render_dashboard_strip(client)


render()
