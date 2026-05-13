"""Tests for /v1/lineage — master plan §4 / §8.2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agentforge.api.routes_lineage import set_lineage
from agentforge.memory.models import AttackJob, AttackTrace
from agentforge.memory.schemas import MutatedAttack
from agentforge.redteam.lineage import AttackLineage


def _build_lineage() -> AttackLineage:
    lin = AttackLineage()
    root = MutatedAttack(
        attack_id="root-1",
        parent_attack_id=None,
        seed_id="seed-a",
        category="prompt_injection",
        strategy="single_turn",
        mutator_chain=[],
        rendered_prompt="r",
    )
    child = MutatedAttack(
        attack_id="child-1",
        parent_attack_id="root-1",
        seed_id="seed-a",
        category="prompt_injection",
        strategy="single_turn",
        mutator_chain=["paraphrase"],
        rendered_prompt="r2",
    )
    lin.record(root)
    lin.record(child)
    return lin


@pytest.mark.unit
def test_lineage_tree(client: TestClient) -> None:
    """`/v1/lineage/{attack_id}` returns the nested tree rooted at the requested attack."""
    set_lineage(_build_lineage())
    try:
        r = client.get("/v1/lineage/root-1")
        assert r.status_code == 200
        body = r.json()
        assert body["attack_id"] == "root-1"
        assert len(body["children"]) == 1
        assert body["children"][0]["attack_id"] == "child-1"
    finally:
        set_lineage(AttackLineage())


@pytest.mark.unit
def test_lineage_404_for_unknown(client: TestClient) -> None:
    """Unknown attack_id returns 404 (no silent empty tree)."""
    set_lineage(AttackLineage())  # empty
    r = client.get("/v1/lineage/no-such-attack")
    assert r.status_code == 404


# --- /v1/lineage/recent (sub-plan Next03 §3.5) -----------------------------


def _seed_run_and_jobs(session, n: int) -> list[tuple[str, str]]:
    """Insert one Run + n (AttackJob, AttackTrace) pairs with monotonically
    increasing created_at. Returns the list of (job_id, trace_id) tuples."""
    from tests.unit.api.conftest import seed_run

    seed_run(session, "run-x", status="running")
    out: list[tuple[str, str]] = []
    base = datetime.now(UTC).replace(tzinfo=None)
    for i in range(n):
        job_id = f"job-{i:03d}"
        trace_id = f"trace-{i:03d}"
        session.add(
            AttackJob(
                id=job_id,
                run_id="run-x",
                category=("prompt_injection" if i % 2 == 0 else "tool_misuse"),
                strategy=("single_turn" if i % 2 == 0 else "indirect_pdf"),
                status="completed",
                created_at=base + timedelta(seconds=i),
            )
        )
        session.add(
            AttackTrace(
                id=trace_id,
                attack_job_id=job_id,
                latency_ms=100 + i,
            )
        )
        out.append((job_id, trace_id))
    session.flush()
    return out


@pytest.mark.unit
def test_lineage_recent_returns_most_recent_first(client: TestClient, seeded_session) -> None:
    """`GET /v1/lineage/recent` orders rows by attack_jobs.created_at DESC
    (sub-plan Next03 §3.5)."""
    pairs = _seed_run_and_jobs(seeded_session, n=3)
    seeded_session.commit()

    r = client.get("/v1/lineage/recent")
    assert r.status_code == 200
    rows = r.json()["rows"]
    assert len(rows) == 3
    # Newest-first: pair index 2 first, 1 next, 0 last.
    assert rows[0]["attack_id"] == pairs[2][1]
    assert rows[1]["attack_id"] == pairs[1][1]
    assert rows[2]["attack_id"] == pairs[0][1]


@pytest.mark.unit
def test_lineage_recent_respects_limit(client: TestClient, seeded_session) -> None:
    """`?limit=N` caps the response (sub-plan Next03 §3.5)."""
    _seed_run_and_jobs(seeded_session, n=12)
    seeded_session.commit()

    r = client.get("/v1/lineage/recent", params={"limit": 5})
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 5


@pytest.mark.unit
def test_lineage_recent_joins_category_and_strategy(client: TestClient, seeded_session) -> None:
    """The join populates category + strategy from attack_jobs (sub-plan Next03 §3.5)."""
    _seed_run_and_jobs(seeded_session, n=2)
    seeded_session.commit()

    rows = client.get("/v1/lineage/recent").json()["rows"]
    # i=0 → prompt_injection/single_turn; i=1 → tool_misuse/indirect_pdf
    cats = {r["category"] for r in rows}
    strats = {r["strategy"] for r in rows}
    assert cats == {"prompt_injection", "tool_misuse"}
    assert strats == {"single_turn", "indirect_pdf"}
    # Latency surfaces from attack_traces.
    assert any(r["latency_ms"] >= 100 for r in rows)
