"""Tests for /v1/refusal-rate — sub-plan Next05 §5."""

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
) -> None:
    """Insert n_total jobs+traces; the first n_refusals carry refusal-text bodies."""
    seed_run(session, run_id=f"run-{job_prefix}", status="completed")
    base = datetime.now(UTC).replace(tzinfo=None)
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
