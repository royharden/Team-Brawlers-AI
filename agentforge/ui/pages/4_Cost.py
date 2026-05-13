"""Cost page — master plan §15.

Today's spend by role + the four-scale projection table + a short explainer
pulled from the headline section of ``COST_ANALYSIS.md``.
"""

from __future__ import annotations

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
    # Sub-plan Next05 §5: target-refusal rate over the last 100 attacks.
    # High refusal rate = the Co-Pilot's defenses are landing.
    try:
        refusal = client.refusal_rate(last=100)
        rate = float(refusal.get("refusal_rate") or 0.0)
        n_scanned = int(refusal.get("n_attacks_scanned") or 0)
        c3.metric(
            "Target refusal rate",
            f"{rate:.0%}",
            help=f"Over the last {n_scanned} persisted attacks. Higher = stronger defense.",
        )
    except Exception as exc:
        c3.error(f"refusal-rate unavailable: {exc}")

    by_role = today.get("by_role") or {}
    if by_role:
        st.write(by_role)
    else:
        st.caption("No cost-ledger entries today yet.")

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
