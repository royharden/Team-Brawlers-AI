"""VulnReports page — master plan §12.

Filterable list of vuln reports + click-through that renders the markdown
content of each report.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import severity_badge


def render() -> None:
    st.title("Vulnerability Reports")
    client = AgentForgeClient()

    col1, col2 = st.columns(2)
    severity = col1.selectbox(
        "Severity",
        ["", "critical", "high", "medium", "low", "info"],
        index=0,
    )
    status = col2.selectbox(
        "Status",
        ["", "open", "fixed", "closed", "wontfix"],
        index=0,
    )

    try:
        data = client.list_reports(
            severity=severity or None,
            status=status or None,
        )
    except Exception as exc:
        st.error(f"reports unavailable: {exc}")
        return

    reports = data.get("reports", [])
    if not reports:
        st.info("No vuln reports match the current filter.")
        return

    for r in reports:
        bg, fg = severity_badge(r.get("severity", "unknown"))
        st.markdown(
            f"<div style='background:{bg};color:{fg};padding:6px 12px;"
            f"border-radius:6px;display:inline-block;margin-bottom:4px;'>"
            f"<b>{r.get('vr_id')}</b> — {r.get('severity')}</div>",
            unsafe_allow_html=True,
        )
        st.write(
            f"status: `{r.get('status')}` · fix_status: `{r.get('fix_status')}`"
            f" · defcon: {r.get('defcon')}"
        )

    selected = st.text_input("Open VR by vr_id")
    if selected:
        try:
            detail = client.get_report(selected.strip())
        except Exception as exc:
            st.error(f"could not fetch {selected}: {exc}")
        else:
            st.markdown(detail.get("content_markdown") or "_no markdown body_")


render()
