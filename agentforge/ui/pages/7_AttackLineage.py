"""Attack Lineage page — master plan §12.

The operator picks a recent attack from the dropdown (sourced from the
``attack_traces`` table via ``GET /v1/lineage/recent``) and the page
renders its DB-backed metadata plus the in-process AttackLineage tree
(empty across uvicorn restarts; surfaced as a caveat).

Sub-plan Next03 §3.5 added the dropdown + the new endpoint behind it.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from agentforge.ui.api_client import AgentForgeClient


def _render_node(node: dict[str, Any], depth: int = 0) -> None:
    prefix = "  " * depth
    aid = node.get("attack_id")
    strat = node.get("strategy")
    chain = ",".join(node.get("mutator_chain") or [])
    st.text(f"{prefix}- {aid}  ({strat})  [{chain}]")
    for c in node.get("children") or []:
        _render_node(c, depth + 1)


def render() -> None:
    st.title("Attack Lineage")
    client = AgentForgeClient()

    try:
        recent = client.lineage_recent(limit=50)
    except Exception as exc:
        st.error(f"recent attacks unavailable: {exc}")
        return
    rows = recent.get("rows") or []
    if not rows:
        st.info("No attack traces in the DB yet — fire `tb attack` to populate.")
        return

    def _label(r: dict[str, Any]) -> str:
        aid = str(r.get("attack_id") or "")[:8]
        cat = r.get("category", "?")
        strat = r.get("strategy", "?")
        when = r.get("created_at", "")
        return f"{aid}  {cat}/{strat}  {when}"

    selected = st.selectbox(
        "Select recent attack",
        options=rows,
        index=0,
        format_func=_label,
    )
    if selected is None:
        return

    st.subheader("Trace metadata (DB)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Latency (ms)", int(selected.get("latency_ms") or 0))
    c2.metric("Category", selected.get("category", "?"))
    c3.metric("Strategy", selected.get("strategy", "?"))
    if selected.get("target_error"):
        st.error(f"target error: {selected['target_error']}")
    st.code(
        f"attack_id: {selected.get('attack_id')}\nattack_job_id: {selected.get('attack_job_id')}"
    )

    st.subheader("Lineage tree")
    st.caption(
        "Tries the in-process AttackLineage registry first (live within "
        "this uvicorn process), falls back to a DB walk of "
        "`attack_traces.parent_attack_id` (sub-plan Next05 §2 — survives "
        "restarts for any attack written post-migration)."
    )
    try:
        tree = client.lineage(str(selected.get("attack_id")))
    except Exception as exc:
        st.warning(f"no lineage tree available for this attack_id: {exc}")
        return
    _render_node(tree)
    with st.expander("Raw JSON"):
        st.json(tree)


render()
