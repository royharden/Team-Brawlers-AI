"""Tests for /v1/delta — master plan §4 / §12."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import seed_delta_snapshot


@pytest.mark.unit
def test_delta_trend_respects_last_param(
    client: TestClient, seeded_session
) -> None:
    for i in range(6):
        seed_delta_snapshot(
            seeded_session,
            fingerprint=f"fp-{i}",
            aggregate=0.5 + i * 0.05,
        )
    seeded_session.commit()

    r = client.get("/v1/delta/trend", params={"last": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body["snapshots"]) == 3


@pytest.mark.unit
def test_delta_snapshot_fetch_by_fingerprint(
    client: TestClient, seeded_session
) -> None:
    seed_delta_snapshot(
        seeded_session,
        fingerprint="fp-xyz",
        aggregate=0.42,
        by_cell={"prompt_injection:single_turn": 0.5},
    )
    seeded_session.commit()

    r = client.get("/v1/delta/snapshot/fp-xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["target_fingerprint"] == "fp-xyz"
    assert body["aggregate_pass_rate"] == pytest.approx(0.42)
    assert body["by_cell"]["prompt_injection:single_turn"] == 0.5


@pytest.mark.unit
def test_delta_snapshot_404(client: TestClient) -> None:
    r = client.get("/v1/delta/snapshot/unknown-fp")
    assert r.status_code == 404
