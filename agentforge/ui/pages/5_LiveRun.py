"""LiveRun page — master plan §12.

Live streaming wires up when the live target adapter lands. Until then, the
page shows the most-recent regression batch as a substitute.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient


def render() -> None:
    st.title("Live Run")
    st.info(
        "Live attack streaming wires up when the live target adapter lands. "
        "For now, use `tb attack --mock` from CLI."
    )
    client = AgentForgeClient()
    try:
        batch = client.latest_regression_results()
    except Exception as exc:
        st.error(f"regression results unavailable: {exc}")
        return
    st.subheader("Most-recent regression batch (substitute view)")
    if batch.get("file"):
        st.caption(f"source: {batch['file']}")
    rows = batch.get("rows") or []
    if not rows:
        st.info("No regression batch on disk yet.")
        return
    st.dataframe([{"case_id": r.get("case_id"), "outcome": r.get("outcome")} for r in rows])


render()
