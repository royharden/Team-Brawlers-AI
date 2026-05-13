"""Tests for /v1/regression — master plan §4 / §13."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import seed_regression_case, seed_vuln_report


@pytest.mark.unit
def test_list_regression_cases(client: TestClient, seeded_session) -> None:
    seed_vuln_report(seeded_session, vr_id="VR-RC-1")
    seed_regression_case(seeded_session, case_id="rc-a", vr_id="VR-RC-1")
    seeded_session.commit()

    r = client.get("/v1/regression/cases")
    assert r.status_code == 200
    body = r.json()
    assert len(body["cases"]) == 1
    assert body["cases"][0]["vr_id"] == "VR-RC-1"
    assert body["cases"][0]["what_bug_this_catches"]


@pytest.mark.unit
def test_latest_regression_results(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    fpath = results_dir / "regression_20260101T000000Z.jsonl"
    rows = [
        {"case_id": "rc-a", "outcome": "passed"},
        {"case_id": "rc-b", "outcome": "failed"},
    ]
    fpath.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    import agentforge.api.routes_regression as mod

    monkeypatch.setattr(mod, "_RESULTS_DIR", results_dir)

    r = client.get("/v1/regression/results/latest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 2
    assert body["rows"][0]["case_id"] == "rc-a"
    assert body["rows"][1]["outcome"] == "failed"
