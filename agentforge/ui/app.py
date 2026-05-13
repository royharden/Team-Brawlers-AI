"""Streamlit entry — master plan §4.

Architecture invariant: this module talks to the FastAPI app over HTTP only.
It MUST NOT import `agentforge.memory.db` directly.
"""

from __future__ import annotations

import streamlit as st

from agentforge.ui.api_client import APIClient


def main() -> None:
    st.set_page_config(page_title="AgentForge", layout="wide")
    st.title("AgentForge — Adversarial AI Security Platform")
    st.info("Scaffolding — page content lands in Phase 5.")
    _ = APIClient()


if __name__ == "__main__":
    main()
