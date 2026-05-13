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


# --- Sub-plan Next05 §2: DB-backed lineage tree ---------------------------


def _seed_lineage_chain(session) -> tuple[str, str, str]:
    """Insert a 3-row lineage chain: root → child1 → grandchild.
    Returns (root_attack_id, child_attack_id, grandchild_attack_id)."""
    import json
    from datetime import UTC, datetime

    from agentforge.memory.models import AttackJob, AttackTrace
    from tests.unit.api.conftest import seed_run

    seed_run(session, "run-lineage")
    base = datetime.now(UTC).replace(tzinfo=None)
    root_aid = "aid-root"
    child_aid = "aid-child"
    grand_aid = "aid-grandchild"
    rows = [
        ("job-root", root_aid, None, ["seed_baseline"]),
        ("job-child", child_aid, root_aid, ["role_wrap.doctor"]),
        ("job-grand", grand_aid, child_aid, ["role_wrap.doctor", "encoders.base64"]),
    ]
    for i, (jid, aid, parent_aid, mutators) in enumerate(rows):
        session.add(
            AttackJob(
                id=jid,
                run_id="run-lineage",
                category="prompt_injection",
                strategy="single_turn",
                seed_id="seed_x",
                status="completed",
                created_at=base,
            )
        )
        session.add(
            AttackTrace(
                id=f"trace-{i}",
                attack_job_id=jid,
                attack_id=aid,
                parent_attack_id=parent_aid,
                mutator_chain_json=json.dumps(mutators),
                latency_ms=100 + i,
            )
        )
    session.flush()
    return root_aid, child_aid, grand_aid


@pytest.mark.unit
def test_lineage_for_attack_walks_db_when_in_process_registry_empty(
    client: TestClient, seeded_session
) -> None:
    """`GET /v1/lineage/{attack_id}` falls back to a DB walk of
    `attack_traces.parent_attack_id` when the in-process registry has
    nothing for the id (sub-plan Next05 §2)."""
    set_lineage(AttackLineage())  # ensure in-process registry is empty
    root_aid, child_aid, grand_aid = _seed_lineage_chain(seeded_session)
    seeded_session.commit()

    r = client.get(f"/v1/lineage/{root_aid}")
    assert r.status_code == 200
    tree = r.json()
    assert tree["attack_id"] == root_aid
    assert len(tree["children"]) == 1
    assert tree["children"][0]["attack_id"] == child_aid
    assert len(tree["children"][0]["children"]) == 1
    assert tree["children"][0]["children"][0]["attack_id"] == grand_aid
    # mutator_chain round-trips from JSON.
    assert tree["children"][0]["children"][0]["mutator_chain"] == [
        "role_wrap.doctor",
        "encoders.base64",
    ]


@pytest.mark.unit
def test_lineage_for_attack_subtree_lookup_works(client: TestClient, seeded_session) -> None:
    """Looking up a non-root attack_id returns the subtree rooted at it
    (sub-plan Next05 §2)."""
    set_lineage(AttackLineage())
    _root, child_aid, grand_aid = _seed_lineage_chain(seeded_session)
    seeded_session.commit()

    r = client.get(f"/v1/lineage/{child_aid}")
    assert r.status_code == 200
    tree = r.json()
    assert tree["attack_id"] == child_aid
    assert len(tree["children"]) == 1
    assert tree["children"][0]["attack_id"] == grand_aid


@pytest.mark.unit
def test_lineage_for_attack_returns_404_when_neither_registry_nor_db_has_it(
    client: TestClient, seeded_session
) -> None:
    """If the in-process registry AND the DB both lack the attack_id, the
    endpoint returns 404 (sub-plan Next05 §2)."""
    set_lineage(AttackLineage())
    _seed_lineage_chain(seeded_session)
    seeded_session.commit()

    r = client.get("/v1/lineage/aid-does-not-exist")
    assert r.status_code == 404


@pytest.mark.unit
def test_lineage_recent_uses_attack_id_when_present(client: TestClient, seeded_session) -> None:
    """`/v1/lineage/recent.rows[*].attack_id` returns the agent-level id
    (`attack_traces.attack_id`) when set, falls back to the trace row PK
    when not (pre-Next05-migration rows). Sub-plan Next05 §2."""
    _seed_lineage_chain(seeded_session)
    seeded_session.commit()

    rows = client.get("/v1/lineage/recent").json()["rows"]
    aids = {r["attack_id"] for r in rows}
    # All 3 rows have attack_id populated → endpoint returns them, not the
    # trace PKs (`trace-0`, `trace-1`, `trace-2`).
    assert aids == {"aid-root", "aid-child", "aid-grandchild"}
