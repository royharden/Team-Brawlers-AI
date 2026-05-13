"""Coverage page — master plan §9.1.

Renders the 8-categories × 9-strategies coverage matrix as a heatmap. The
operator picks a cell from the selectbox below the heatmap to drill into
its ``coverage_cells`` row: attempts / passes / failures / pass rate /
last_attempt_at.

Sub-plan Next03 §3.1 added the per-cell drill-down + the
``GET /v1/coverage/cells`` endpoint behind it.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import coverage_heatmap


def render() -> None:
    st.title("Coverage")
    client = AgentForgeClient()
    try:
        dash = client.get_dashboard()
    except Exception as exc:
        st.error(f"coverage unavailable: {exc}")
        return

    summary = dash.get("coverage_summary") or {}
    st.metric(
        "Covered cells",
        f"{summary.get('covered_cells', 0)} / {summary.get('total_cells', 72)}",
    )
    st.caption(f"Coverage %: {summary.get('pct', 0.0):.1f}")

    try:
        payload = client.get_coverage_cells()
    except Exception as exc:
        st.error(f"per-cell detail unavailable: {exc}")
        coverage_heatmap([])
        return

    cells = payload.get("cells") or []
    coverage_heatmap(cells)

    if not cells:
        st.info("No coverage cells recorded yet — fire `tb attack` to populate.")
        return

    st.subheader("Per-cell drill-down")
    cell_keys = sorted(f"{c.get('category', '?')}/{c.get('strategy', '?')}" for c in cells)
    selected = st.selectbox("Inspect cell", options=cell_keys, index=0)
    if not selected:
        return
    match = next(
        (c for c in cells if f"{c.get('category', '?')}/{c.get('strategy', '?')}" == selected),
        None,
    )
    if match is None:
        st.warning("Selected cell not found in payload.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Attempts", int(match.get("attempts") or 0))
    c2.metric("Passes", int(match.get("passes") or 0))
    c3.metric("Failures", int(match.get("failures") or 0))
    pass_rate = float(match.get("last_pass_rate") or 0.0)
    st.write(f"Last pass rate: **{pass_rate:.2%}**")
    last_at = match.get("last_attempt_at")
    if last_at:
        st.write(f"Last attempt at: `{last_at}`")
    else:
        st.write("Last attempt at: _never_")


render()
