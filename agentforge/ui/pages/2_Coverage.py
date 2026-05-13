"""Coverage page — master plan §9.1.

Renders the 8-categories × 9-strategies coverage matrix as a heatmap. Clicking
a cell is a Phase 8 stub today.
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
    # Snapshot rows are not exposed through the dashboard endpoint yet, so we
    # render an empty heatmap; once a /v1/coverage endpoint lands the page
    # will read from it directly.
    coverage_heatmap([])
    st.caption("Per-cell drill-down lands in Phase 8.")


render()
