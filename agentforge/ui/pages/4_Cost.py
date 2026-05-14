"""Cost page — master plan §15.

Today's spend by role + the four-scale projection table + a short explainer
pulled from the headline section of ``COST_ANALYSIS.md``. Next06 §2 adds a
refusal-rate trend chart + per-mutator/category breakdown so the operator
sees defensive regressions visually (a chart trending UP as hardening
lands is the most compelling 30 seconds of the demo).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from agentforge.ui.api_client import AgentForgeClient
from agentforge.ui.components import cost_table

COST_EXPLAINER = """
**What changes at each scale**

- **100 runs** — in-process SQLite, single-process orchestrator. Bottleneck is
  developer iteration, not infra.
- **1K runs** — Langfuse tracing overhead becomes visible (~5%). BudgetGuard
  cost-without-signal halt becomes load-bearing.
- **10K runs** — Postgres migration required (SQLite single-writer ceiling).
  Worker pool replaces synchronous step loop. ~$50/mo infra.
- **100K runs** — Queueing layer, per-target sharding, External-Judge batching
  (5 rubrics per call → ~30% cost reduction in that role). ~$300/mo infra.
"""


def render() -> None:
    st.title("Cost")
    client = AgentForgeClient()

    try:
        today = client.cost_today()
    except Exception as exc:
        st.error(f"cost today unavailable: {exc}")
        today = {}

    st.subheader("Today")
    c1, c2, c3 = st.columns(3)
    c1.metric("Spend (USD)", today.get("spend_usd", "0"))
    c2.metric("Calls", today.get("n_calls", 0))

    # Next06 §3: detector selector — `deterministic` (free regex scan) vs
    # `llm` (Haiku-backed classifier, catches non-canonical refusals at
    # ~1 Haiku call per attack). Persists via session_state so a refresh
    # doesn't reset the choice.
    detector = st.radio(
        "Refusal detector",
        options=["deterministic", "llm"],
        index=0,
        horizontal=True,
        help=(
            "Deterministic = free regex marker scan. "
            "LLM = Haiku classifier (Next06 §3) — catches 'I'd rather not' / "
            "'that's not something I can help with' style refusals the regex "
            "misses. Burns ~1 Haiku call per scanned attack."
        ),
        key="cost_refusal_detector",
    )

    # Next06 §2: pull refusal-rate aggregate + 24h trend in a single call
    # so the metric chip and the chart below share the same scan window.
    refusal: dict = {}
    since_iso = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    try:
        refusal = client.refusal_rate(last=1000, since=since_iso, buckets=12, detector=detector)
    except Exception as exc:
        c3.error(f"refusal-rate unavailable: {exc}")

    rate = float(refusal.get("refusal_rate") or 0.0)
    n_scanned = int(refusal.get("n_attacks_scanned") or 0)
    c3.metric(
        "Target refusal rate (24h)",
        f"{rate:.0%}",
        help=f"Over the last {n_scanned} attacks in the past 24 hours. Higher = stronger defense.",
    )

    by_role = today.get("by_role") or {}
    if by_role:
        st.write(by_role)
    else:
        st.caption("No cost-ledger entries today yet.")

    # Next06 §2: refusal-rate trend chart — a line climbing as the operator
    # hardens defenses is the most compelling 30 seconds of the demo.
    trend_rows = refusal.get("trend") or []
    if trend_rows:
        st.subheader("Refusal-rate trend (past 24h)")
        trend_df = pd.DataFrame(
            [
                {
                    "bucket_start": row.get("bucket_start"),
                    "refusal_rate": float(row.get("refusal_rate") or 0.0),
                    "n_attacks": int(row.get("n_attacks") or 0),
                }
                for row in trend_rows
            ]
        )
        if not trend_df.empty:
            trend_df["bucket_start"] = pd.to_datetime(trend_df["bucket_start"])
            st.line_chart(
                trend_df.set_index("bucket_start")[["refusal_rate"]],
                height=200,
            )
            st.caption(
                "Each point = refusal rate for that ~2-hour bucket. "
                "Flat zero = no activity in that window."
            )

    # Next06 §2 (closes AgDR-0029 #4): per-mutator + per-category breakdown.
    by_mutator = refusal.get("by_mutator") or {}
    by_category = refusal.get("by_category") or {}
    if by_mutator or by_category:
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**Refusal rate by mutator** (last 24h)")
            if by_mutator:
                mut_df = pd.DataFrame(
                    [
                        {"mutator": m, "refusal_rate": float(r)}
                        for m, r in sorted(by_mutator.items(), key=lambda kv: kv[1], reverse=True)
                    ]
                )
                st.dataframe(mut_df, hide_index=True, use_container_width=True)
            else:
                st.caption("No mutator data yet — fire an attack to populate.")
        with cB:
            st.markdown("**Refusal rate by category** (last 24h)")
            if by_category:
                cat_df = pd.DataFrame(
                    [
                        {"category": c, "refusal_rate": float(r)}
                        for c, r in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
                    ]
                )
                st.dataframe(cat_df, hide_index=True, use_container_width=True)
            else:
                st.caption("No category data yet — fire an attack to populate.")

    st.subheader("Projections")
    try:
        projections = client.cost_projections()
    except Exception as exc:
        st.error(f"projections unavailable: {exc}")
        projections = {}
    rows = cost_table(projections)
    if rows:
        st.dataframe(rows)
        if projections.get("pricing_retrieved_on"):
            st.caption(
                f"Pricing retrieved {projections['pricing_retrieved_on']} · "
                f"actual dev spend so far: {projections.get('actual_dev_spend_usd', '0.00')}"
            )
    else:
        st.info("Projections temporarily unavailable — check `/v1/cost/projections` log.")

    st.markdown(COST_EXPLAINER)


render()
