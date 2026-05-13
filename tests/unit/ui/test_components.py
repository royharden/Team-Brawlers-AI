"""Tests for UI components — master plan §4 / §12."""

from __future__ import annotations

import pytest

from agentforge.ui.components import (
    SEVERITY_COLORS,
    coverage_heatmap,
    defense_delta_chart,
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


@pytest.mark.unit
def test_defense_delta_chart_reverses_to_chronological_order() -> None:
    """`defense_delta_chart` takes API-shaped (newest-first) snapshots and
    returns them oldest-first so the chart's x-axis grows left-to-right
    (sub-plan Next03 §3.6)."""
    # API returns newest-first per `routes_delta::trend()`. The shaper
    # reverses to oldest-first for chart-consumption.
    api_payload = [
        {
            "snapshot_at": "2026-05-15T12:00:00Z",
            "aggregate_pass_rate": 0.9,
            "target_fingerprint": "fp-c",
        },
        {
            "snapshot_at": "2026-05-14T12:00:00Z",
            "aggregate_pass_rate": 0.8,
            "target_fingerprint": "fp-b",
        },
        {
            "snapshot_at": "2026-05-13T12:00:00Z",
            "aggregate_pass_rate": 0.7,
            "target_fingerprint": "fp-a",
        },
    ]
    series = defense_delta_chart(api_payload)
    assert [s["snapshot_at"] for s in series] == [
        "2026-05-13T12:00:00Z",
        "2026-05-14T12:00:00Z",
        "2026-05-15T12:00:00Z",
    ]
    assert [s["aggregate_pass_rate"] for s in series] == [0.7, 0.8, 0.9]
