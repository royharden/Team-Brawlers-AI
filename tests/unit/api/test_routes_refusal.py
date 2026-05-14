"""Tests for /v1/refusal-rate — sub-plan Next05 §5 + Next06 §2."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agentforge.memory.models import AttackJob, AttackTrace
from tests.unit.api.conftest import seed_run


def _seed(
    session,
    *,
    n_total: int,
    n_refusals: int,
    category: str = "prompt_injection",
    strategy: str = "single_turn",
    job_prefix: str = "j",
    trace_prefix: str = "t",
    mutator_chain: list[str] | None = None,
    base_offset: timedelta = timedelta(0),
) -> None:
    """Insert n_total jobs+traces; the first n_refusals carry refusal-text bodies.

    `mutator_chain` populates `attack_traces.mutator_chain_json` for the
    per-mutator breakdown (Next06 §2 / AgDR-0029 #4).
    `base_offset` shifts created_at timestamps backward in time — lets
    `since=` and `buckets=` tests seed traces across the window.
    """
    seed_run(session, run_id=f"run-{job_prefix}", status="completed")
    base = datetime.now(UTC).replace(tzinfo=None) - base_offset
    chain_json = json.dumps(mutator_chain or [])
    for i in range(n_total):
        jid = f"{job_prefix}-{i:03d}"
        tid = f"{trace_prefix}-{i:03d}"
        session.add(
            AttackJob(
                id=jid,
                run_id=f"run-{job_prefix}",
                category=category,
                strategy=strategy,
                status="completed",
                created_at=base + timedelta(seconds=i),
            )
        )
        body = (
            "I cannot help with that request."
            if i < n_refusals
            else "Here is your medication review for patient John Doe."
        )
        session.add(
            AttackTrace(
                id=tid,
                attack_job_id=jid,
                latency_ms=100,
                target_response_json=json.dumps({"body_text_preview": body}),
                mutator_chain_json=chain_json,
            )
        )


@pytest.mark.unit
def test_refusal_rate_empty_db_returns_zero(client: TestClient) -> None:
    """Empty DB → 0 attacks scanned, 0% refusal rate, no crash."""
    r = client.get("/v1/refusal-rate")
    assert r.status_code == 200
    body = r.json()
    assert body["n_attacks_scanned"] == 0
    assert body["n_refusals"] == 0
    assert body["refusal_rate"] == 0.0


@pytest.mark.unit
def test_refusal_rate_aggregates_correctly(client: TestClient, seeded_session) -> None:
    """3 of 10 traces refuse → refusal_rate=0.3 (sub-plan Next05 §5)."""
    _seed(seeded_session, n_total=10, n_refusals=3)
    seeded_session.commit()

    r = client.get("/v1/refusal-rate")
    assert r.status_code == 200
    body = r.json()
    assert body["n_attacks_scanned"] == 10
    assert body["n_refusals"] == 3
    assert body["refusal_rate"] == pytest.approx(0.3)
    # All 10 are prompt_injection/single_turn so the by-category map should
    # have one entry at 0.3.
    assert body["by_category"]["prompt_injection"] == pytest.approx(0.3)
    assert body["by_strategy"]["single_turn"] == pytest.approx(0.3)


@pytest.mark.unit
def test_refusal_rate_breaks_down_by_category(client: TestClient, seeded_session) -> None:
    """Two categories with different refusal rates surface separately
    (sub-plan Next05 §5)."""
    _seed(
        seeded_session,
        n_total=4,
        n_refusals=4,
        category="prompt_injection",
        job_prefix="pi",
        trace_prefix="pi",
    )
    _seed(
        seeded_session,
        n_total=4,
        n_refusals=0,
        category="data_exfiltration",
        job_prefix="dx",
        trace_prefix="dx",
    )
    seeded_session.commit()

    body = client.get("/v1/refusal-rate").json()
    assert body["n_attacks_scanned"] == 8
    assert body["n_refusals"] == 4
    assert body["refusal_rate"] == pytest.approx(0.5)
    assert body["by_category"]["prompt_injection"] == pytest.approx(1.0)
    assert body["by_category"]["data_exfiltration"] == pytest.approx(0.0)


@pytest.mark.unit
def test_refusal_rate_respects_last_param(client: TestClient, seeded_session) -> None:
    """`?last=N` caps the slice — only the most-recent N traces are scanned."""
    _seed(seeded_session, n_total=20, n_refusals=20)
    seeded_session.commit()

    body = client.get("/v1/refusal-rate", params={"last": 5}).json()
    assert body["n_attacks_scanned"] == 5
    assert body["n_refusals"] == 5
    assert body["refusal_rate"] == 1.0


@pytest.mark.unit
def test_refusal_rate_handles_malformed_target_response_json(
    client: TestClient, seeded_session
) -> None:
    """A malformed `target_response_json` value is treated as non-refusal —
    no crash (sub-plan Next05 §5)."""
    seed_run(seeded_session, "run-mal")
    seeded_session.add(
        AttackJob(
            id="job-mal",
            run_id="run-mal",
            category="prompt_injection",
            strategy="single_turn",
            status="completed",
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    seeded_session.add(
        AttackTrace(
            id="trace-mal",
            attack_job_id="job-mal",
            latency_ms=100,
            target_response_json="this is not valid json {{{",
        )
    )
    seeded_session.commit()

    body = client.get("/v1/refusal-rate").json()
    assert body["n_attacks_scanned"] == 1
    assert body["n_refusals"] == 0


# --------------------------------------------------------------------------- Next06 §2


@pytest.mark.unit
def test_refusal_rate_by_mutator_breaks_down_individual_mutators(
    client: TestClient, seeded_session
) -> None:
    """3 refusals all carrying mutator_chain=[base64_encoder, trust_mutator]
    → both mutators show 1.0 refusal rate, even though each appears in
    every refusal trace (per-mutator, NOT per-chain — AgDR-0029 #4)."""
    _seed(
        seeded_session,
        n_total=3,
        n_refusals=3,
        mutator_chain=["base64_encoder", "trust_mutator"],
        job_prefix="m1",
        trace_prefix="m1",
    )
    seeded_session.commit()

    body = client.get("/v1/refusal-rate").json()
    assert body["by_mutator"]["base64_encoder"] == pytest.approx(1.0)
    assert body["by_mutator"]["trust_mutator"] == pytest.approx(1.0)


@pytest.mark.unit
def test_refusal_rate_by_mutator_handles_disjoint_chains(
    client: TestClient, seeded_session
) -> None:
    """Two seed groups with different mutator chains and different
    refusal rates → each mutator's row reports its own group's rate."""
    _seed(
        seeded_session,
        n_total=4,
        n_refusals=4,
        mutator_chain=["base64_encoder"],
        job_prefix="g1",
        trace_prefix="g1",
    )
    _seed(
        seeded_session,
        n_total=4,
        n_refusals=0,
        mutator_chain=["leetspeak_encoder"],
        job_prefix="g2",
        trace_prefix="g2",
    )
    seeded_session.commit()

    body = client.get("/v1/refusal-rate").json()
    assert body["by_mutator"]["base64_encoder"] == pytest.approx(1.0)
    assert body["by_mutator"]["leetspeak_encoder"] == pytest.approx(0.0)


@pytest.mark.unit
def test_refusal_rate_since_filter_excludes_older_traces(
    client: TestClient, seeded_session
) -> None:
    """`?since=` drops traces older than the cutoff (Next06 §2 + AgDR-0029 #1)."""
    # 5 OLD refusals from 48h ago — should be filtered out.
    _seed(
        seeded_session,
        n_total=5,
        n_refusals=5,
        base_offset=timedelta(hours=48),
        job_prefix="old",
        trace_prefix="old",
    )
    # 3 NEW refusals + 7 NEW non-refusals — should all be counted.
    _seed(
        seeded_session,
        n_total=10,
        n_refusals=3,
        base_offset=timedelta(minutes=5),
        job_prefix="new",
        trace_prefix="new",
    )
    seeded_session.commit()

    since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    body = client.get("/v1/refusal-rate", params={"since": since, "last": 1000}).json()
    assert body["n_attacks_scanned"] == 10
    assert body["n_refusals"] == 3
    assert body["refusal_rate"] == pytest.approx(0.3)


@pytest.mark.unit
def test_refusal_rate_since_rejects_bad_iso_string(client: TestClient) -> None:
    """A non-ISO `since` returns 400 with a helpful detail."""
    r = client.get("/v1/refusal-rate", params={"since": "yesterday"})
    assert r.status_code == 400
    assert "ISO-8601" in r.json()["detail"]


@pytest.mark.unit
def test_refusal_rate_buckets_returns_trend_array(client: TestClient, seeded_session) -> None:
    """`?buckets=N` returns a trend list of N buckets each with refusal_rate."""
    _seed(seeded_session, n_total=10, n_refusals=5)
    seeded_session.commit()

    body = client.get("/v1/refusal-rate", params={"buckets": 6, "last": 100}).json()
    assert body["trend"] is not None
    assert len(body["trend"]) == 6
    for bucket in body["trend"]:
        assert "bucket_start" in bucket
        assert "bucket_end" in bucket
        assert 0.0 <= bucket["refusal_rate"] <= 1.0


@pytest.mark.unit
def test_refusal_rate_response_carries_detector_label(client: TestClient) -> None:
    """The response advertises which detector ran. Default is deterministic;
    Next06 §3 will add `detector=llm` for the Haiku-backed classifier."""
    body = client.get("/v1/refusal-rate").json()
    assert body["detector"] == "deterministic"
