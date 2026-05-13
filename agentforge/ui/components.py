"""Shared Streamlit components — master plan §4."""

from __future__ import annotations

import streamlit as st


def header_banner(title: str, subtitle: str = "") -> None:
    """Render a consistent header across pages."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
