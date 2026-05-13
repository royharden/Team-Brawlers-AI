"""Defense Delta page — master plan §12.

Line chart of ``aggregate_pass_rate`` over the most-recent N snapshots
(operator-selectable; default 5) plus a per-cell heatmap of the delta
between the two most-recent fingerprints when N ≥ 2.

Sub-plan Next03 §3.6 added the selectbox + axis labels.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import defense_delta_chart


def render() -> None:
    st.title("Defense Delta")
    client = AgentForgeClient()

    raw_choice = st.selectbox(
        "Snapshots to show",
        options=[2, 5, 10, "all"],
        index=1,
    )
    last = raw_choice if isinstance(raw_choice, int) else 200

    try:
        trend = client.delta_trend(last=last)
    except Exception as exc:
        st.error(f"trend unavailable: {exc}")
        return
    snapshots = trend.get("snapshots") or []
    if not snapshots:
        st.info("No snapshots recorded yet.")
        return
    defense_delta_chart(snapshots)
    st.caption(
        "x = snapshot_at (oldest → newest) · y = aggregate_pass_rate "
        "(lower = target weaker / more attacks landed)"
    )

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
