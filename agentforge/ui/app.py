"""Streamlit entry — master plan §4 / §12.

This module talks to the FastAPI app over HTTP only — it MUST NOT import
``agentforge.memory.*``. Use :class:`agentforge.ui.api_client.AgentForgeClient`
for everything DB-shaped.

The canonical Dashboard view lives in ``pages/1_Dashboard.py``; this entry
point renders a short status sidebar + a link to that page.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient

PAGE_TITLE = "AgentForge | Adversarial AI Security Platform"


def _render_sidebar(client: AgentForgeClient) -> None:
    """Sidebar showing platform status. Network failures degrade gracefully."""
    with st.sidebar:
        st.header("Platform status")
        try:
            health = client.healthz()
            st.success(f"API ok — v{health.get('version', '?')}")
        except Exception as exc:
            st.error(f"API unreachable: {exc}")
            return

        try:
            dash = client.get_dashboard()
        except Exception as exc:
            st.warning(f"dashboard unavailable: {exc}")
            return

        st.metric("Runs", dash.get("totals", {}).get("runs", 0))
        st.metric("Open VRs", dash.get("totals", {}).get("vrs_open", 0))
        st.metric("Spend (USD)", dash.get("totals", {}).get("spend_usd", "0"))

        fingerprint = dash.get("latest_fingerprint")
        if fingerprint:
            st.caption(f"Target fingerprint: `{fingerprint[:16]}…`")

        floor = dash.get("judge_floor_met") or {}
        if floor:
            ok = all(bool(v) for v in floor.values())
            badge = "PASS" if ok else "FAIL"
            (st.success if ok else st.error)(f"Judge floor met: {badge}")


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title("AgentForge — Adversarial AI Security Platform")
    st.caption(
        "Multi-agent adversarial AI security platform for the OpenEMR Clinical Co-Pilot. "
        "Use the left-hand navigation to drill into Coverage, VulnReports, Cost, "
        "Live Runs, Judge Meta-Eval, Attack Lineage, and Defense Delta."
    )
    client = AgentForgeClient()
    _render_sidebar(client)
    st.info("Open the **Dashboard** page in the left sidebar for the full overview.")


if __name__ == "__main__":
    main()
