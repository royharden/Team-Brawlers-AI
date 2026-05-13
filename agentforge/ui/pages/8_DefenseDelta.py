"""Defense Delta page — master plan §12.

Line chart of ``aggregate_pass_rate`` over time + per-cell heatmap of the
delta between the two most-recent fingerprints (when present).
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import defense_delta_chart


def render() -> None:
    st.title("Defense Delta")
    client = AgentForgeClient()
    try:
        trend = client.delta_trend(last=20)
    except Exception as exc:
        st.error(f"trend unavailable: {exc}")
        return
    snapshots = trend.get("snapshots") or []
    if not snapshots:
        st.info("No snapshots recorded yet.")
        return
    defense_delta_chart(snapshots)

    if len(snapshots) >= 2:
        st.subheader("Per-cell delta (b − a) for the two most-recent fingerprints")
        b = snapshots[0]
        a = snapshots[1]
        diff: dict[str, float] = {}
        keys = set((a.get("by_cell") or {}).keys()) | set((b.get("by_cell") or {}).keys())
        for k in sorted(keys):
            av = float((a.get("by_cell") or {}).get(k, 0.0))
            bv = float((b.get("by_cell") or {}).get(k, 0.0))
            diff[k] = bv - av
        st.write(diff)


render()
