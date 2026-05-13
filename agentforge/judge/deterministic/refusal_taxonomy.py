"""Refusal taxonomy classifier — master plan §8.3 (PyRIT-style). Stub."""

from __future__ import annotations

from typing import Literal

RefusalLabel = Literal["non_refusal", "refusal", "partial"]


def classify(text: str) -> RefusalLabel:
    """Classify a response as non_refusal / refusal / partial. Stub returns non_refusal."""
    _ = text
    return "non_refusal"
