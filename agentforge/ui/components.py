"""Shared Streamlit components — master plan §4 / §12.

These helpers return plain Python data structures (dicts / lists / DataFrames)
or render via the ``st`` module. Tests target the *data shaping* paths and
do not require a live Streamlit runtime.
"""

from __future__ import annotations

from typing import Any

# Local copy of the 8x9 axis labels — mirrors
# ``agentforge.orchestrator.coverage.CATEGORIES`` / ``STRATEGIES`` so the UI
# layer stays free of indirect ``agentforge.memory.*`` imports.
CATEGORIES: list[str] = [
    "prompt_injection",
    "data_exfiltration",
    "state_corruption",
    "tool_misuse",
    "denial_of_service",
    "identity_role",
    "clinical_integrity",
    "observability_leakage",
]

STRATEGIES: list[str] = [
    "single_turn",
    "crescendo",
    "tree_of_attacks",
    "linear_jailbreak",
    "bad_likert_judge",
    "role_play",
    "indirect_pdf",
    "indirect_intake",
    "fhir_smart",
]

# Severity → (background, text) hex pairs. Stable so tests can assert.
SEVERITY_COLORS: dict[str, tuple[str, str]] = {
    "critical": ("#7f1d1d", "#ffffff"),
    "high": ("#b91c1c", "#ffffff"),
    "medium": ("#b45309", "#ffffff"),
    "low": ("#15803d", "#ffffff"),
    "info": ("#1d4ed8", "#ffffff"),
    "unknown": ("#525252", "#ffffff"),
}


def header_banner(title: str, subtitle: str = "") -> None:
    """Render a consistent header across pages."""
    import streamlit as st  # local import keeps this module testable headless

    st.title(title)
    if subtitle:
        st.caption(subtitle)


# --- Coverage heatmap ---------------------------------------------------------


def _heatmap_grid(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the 8x9 grid + per-cell pass_rate map. Tested directly."""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for c in snapshot:
        key = (str(c.get("category")), str(c.get("strategy")))
        by_key[key] = c

    rows: list[list[float | None]] = []
    attempts_rows: list[list[int]] = []
    for cat in CATEGORIES:
        row: list[float | None] = []
        a_row: list[int] = []
        for strat in STRATEGIES:
            cell = by_key.get((cat, strat))
            if cell is None:
                row.append(None)
                a_row.append(0)
            else:
                attempts = int(cell.get("attempts") or 0)
                a_row.append(attempts)
                if attempts == 0:
                    row.append(None)
                else:
                    row.append(float(cell.get("last_pass_rate") or 0.0))
        rows.append(row)
        attempts_rows.append(a_row)

    return {
        "categories": list(CATEGORIES),
        "strategies": list(STRATEGIES),
        "pass_rate": rows,
        "attempts": attempts_rows,
    }


def coverage_heatmap(snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    """Render an 8x9 coverage heatmap. Returns the grid dict for testability."""
    grid = _heatmap_grid(snapshot)
    try:
        import streamlit as st
    except Exception:  # pragma: no cover — Streamlit unavailable in test ctx
        return grid

    # Best-effort render; never raise if streamlit is in a stripped harness.
    try:
        import streamlit as st

        st.dataframe(
            {
                strat: [grid["pass_rate"][i][j] for i in range(len(CATEGORIES))]
                for j, strat in enumerate(STRATEGIES)
            },
        )
    except Exception:  # pragma: no cover — best-effort UI render
        pass
    return grid


# --- Severity badge -----------------------------------------------------------


def severity_badge(severity: str) -> tuple[str, str]:
    """Return the (background, text) color pair for a severity label."""
    return SEVERITY_COLORS.get(str(severity).lower(), SEVERITY_COLORS["unknown"])


# --- Cost table ---------------------------------------------------------------


def cost_table(projections: dict[str, Any]) -> list[dict[str, Any]]:
    """Shape the projections payload into a four-row table-friendly list."""
    rows: list[dict[str, Any]] = []
    for s in projections.get("scales", []):
        rows.append(
            {
                "n_runs": s.get("n_runs"),
                "per_run_usd": s.get("per_run_usd"),
                "total_usd": s.get("total_usd"),
                "infra_monthly_usd": s.get("infra_monthly_usd"),
                "architecture_notes": s.get("architecture_notes", ""),
            }
        )
    return rows


# --- Defense delta chart ------------------------------------------------------


def defense_delta_chart(trend: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape the trend payload for a line graph. Returns the rendered series.

    Plot order: oldest-first (the API returns newest-first).
    """
    series: list[dict[str, Any]] = []
    for s in trend:
        series.append(
            {
                "snapshot_at": s.get("snapshot_at"),
                "aggregate_pass_rate": float(s.get("aggregate_pass_rate") or 0.0),
                "target_fingerprint": s.get("target_fingerprint"),
            }
        )
    series.reverse()
    try:
        import streamlit as st
    except Exception:  # pragma: no cover
        return series
    try:
        import streamlit as st

        st.line_chart({"aggregate_pass_rate": [r["aggregate_pass_rate"] for r in series]})
    except Exception:  # pragma: no cover
        pass
    return series


__all__ = [
    "SEVERITY_COLORS",
    "header_banner",
    "coverage_heatmap",
    "severity_badge",
    "cost_table",
    "defense_delta_chart",
]
