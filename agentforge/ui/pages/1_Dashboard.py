"""Dashboard page — master plan §12.

Canonical home for the cross-platform overview: totals, latest run, judge
floor status, and the Defense Delta sparkline.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import defense_delta_chart


def render() -> None:
    st.title("Dashboard")
    client = AgentForgeClient()

    try:
        dash = client.get_dashboard()
    except Exception as exc:  # noqa: BLE001
        st.error(f"dashboard unavailable: {exc}")
        return

    totals = dash.get("totals", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runs", totals.get("runs", 0))
    c2.metric("Attacks", totals.get("attacks", 0))
    c3.metric("Open VRs", totals.get("vrs_open", 0))
    c4.metric("Spend (USD)", totals.get("spend_usd", "0"))

    cov = dash.get("coverage_summary", {})
    st.progress(min(1.0, (cov.get("pct") or 0.0) / 100.0))
    st.caption(
        f"Coverage: {cov.get('covered_cells', 0)} / {cov.get('total_cells', 72)} "
        f"cells ({cov.get('pct', 0.0):.1f}%)"
    )

    latest = dash.get("latest_run") or {}
    if latest:
        st.subheader("Latest run")
        st.json(latest)
    else:
        st.info("No runs recorded yet.")

    floor = dash.get("judge_floor_met") or {}
    if floor:
        st.subheader("Judge floor")
        st.write({k: ("PASS" if v else "FAIL") for k, v in floor.items()})

    try:
        trend = client.delta_trend(last=10)
        defense_delta_chart(trend.get("snapshots", []))
    except Exception as exc:  # noqa: BLE001
        st.caption(f"defense-delta trend unavailable: {exc}")


render()
