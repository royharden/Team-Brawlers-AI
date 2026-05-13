"""Tests for UI components — master plan §4 / §12."""

from __future__ import annotations

import pytest

from agentforge.ui.components import (
    SEVERITY_COLORS,
    coverage_heatmap,
    severity_badge,
)


@pytest.mark.unit
def test_coverage_heatmap_returns_8x9_grid() -> None:
    """`coverage_heatmap` shapes a sparse snapshot into the canonical 8x9 grid; missing cells are None."""
    snapshot = [
        {
            "category": "prompt_injection",
            "strategy": "single_turn",
            "attempts": 5,
            "passes": 3,
            "failures": 2,
            "last_pass_rate": 0.6,
        }
    ]
    grid = coverage_heatmap(snapshot)
    assert len(grid["categories"]) == 8
    assert len(grid["strategies"]) == 9
    assert len(grid["pass_rate"]) == 8
    assert all(len(row) == 9 for row in grid["pass_rate"])
    # Single seeded cell should be 0.6, all others None.
    assert grid["pass_rate"][0][0] == 0.6
    assert grid["attempts"][0][0] == 5
    # An uncovered cell:
    assert grid["pass_rate"][1][1] is None


@pytest.mark.unit
def test_severity_badge_returns_color_tuples() -> None:
    """`severity_badge` returns the (bg, fg) hex tuple for known severities and falls back to "unknown" otherwise."""
    high_bg, high_fg = severity_badge("high")
    assert high_bg.startswith("#")
    assert high_fg.startswith("#")
    assert severity_badge("HIGH") == SEVERITY_COLORS["high"]
    assert severity_badge("does-not-exist") == SEVERITY_COLORS["unknown"]
