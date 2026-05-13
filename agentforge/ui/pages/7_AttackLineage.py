"""Attack Lineage page — master plan §12.

Takes an ``attack_id`` and renders the lineage tree as an indented bullet
list (with ``st.json`` as the visual fallback).
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
    attack_id = st.text_input("attack_id")
    if not attack_id:
        st.info("Enter an attack_id above to render its lineage tree.")
        return
    client = AgentForgeClient()
    try:
        tree = client.lineage(attack_id.strip())
    except Exception as exc:
        st.error(f"lineage unavailable: {exc}")
        return
    st.subheader("Tree")
    _render_node(tree)
    with st.expander("Raw JSON"):
        st.json(tree)


render()
