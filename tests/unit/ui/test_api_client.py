"""Tests for the Streamlit-side HTTP client — master plan §4.

Every method must hit the right path on the FastAPI server. The client must
NOT reach into ``agentforge.memory.*``; that invariant is checked separately
in ``test_no_db_imports.py``.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from agentforge.ui.api_client import AgentForgeClient

BASE_URL = "http://test.local"


@pytest.mark.unit
@respx.mock
def test_healthz_hits_correct_path() -> None:
    """`AgentForgeClient.healthz()` GETs `/healthz`."""
    route = respx.get(f"{BASE_URL}/healthz").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    client = AgentForgeClient(base_url=BASE_URL)
    assert client.healthz() == {"status": "ok"}
    assert route.called


@pytest.mark.unit
@respx.mock
def test_dashboard_runs_reports_paths() -> None:
    """UI client hits the correct paths for dashboard / runs / reports endpoints (respx-mocked)."""
    respx.get(f"{BASE_URL}/v1/dashboard").mock(
        return_value=httpx.Response(200, json={"totals": {"runs": 0}})
    )
    respx.get(f"{BASE_URL}/v1/runs").mock(
        return_value=httpx.Response(200, json={"runs": [], "total": 0})
    )
    respx.get(f"{BASE_URL}/v1/runs/abc").mock(
        return_value=httpx.Response(200, json={"run": {"id": "abc"}})
    )
    respx.get(f"{BASE_URL}/v1/reports").mock(return_value=httpx.Response(200, json={"reports": []}))
    respx.get(f"{BASE_URL}/v1/reports/VR-1").mock(
        return_value=httpx.Response(200, json={"vr_id": "VR-1"})
    )
    respx.get(f"{BASE_URL}/v1/reports/VR-1.md").mock(
        return_value=httpx.Response(200, text="# body")
    )

    c = AgentForgeClient(base_url=BASE_URL)
    assert c.get_dashboard()["totals"]["runs"] == 0
    assert c.list_runs()["total"] == 0
    assert c.get_run("abc")["run"]["id"] == "abc"
    assert c.list_reports()["reports"] == []
    assert c.get_report("VR-1")["vr_id"] == "VR-1"
    assert "body" in c.get_report_markdown("VR-1")


@pytest.mark.unit
@respx.mock
def test_approval_post_methods_hit_correct_paths() -> None:
    """`AgentForgeClient.approve / reject / dismiss` POST to
    `/v1/approval/{vr_id}/{action}?reviewer=...` (sub-plan Next04)."""
    for action in ("approve", "reject", "dismiss"):
        respx.post(f"{BASE_URL}/v1/approval/VR-1/{action}").mock(
            return_value=httpx.Response(200, json={"vr_id": "VR-1"})
        )
    c = AgentForgeClient(base_url=BASE_URL)
    assert c.approve("VR-1")["vr_id"] == "VR-1"
    assert c.reject("VR-1")["vr_id"] == "VR-1"
    assert c.dismiss("VR-1", reviewer="bob")["vr_id"] == "VR-1"


@pytest.mark.unit
@respx.mock
def test_lineage_recent_hits_correct_path() -> None:
    """`AgentForgeClient.lineage_recent(limit)` GETs `/v1/lineage/recent?limit=N`
    (sub-plan Next03 §3.5)."""
    payload = {"rows": [{"attack_id": "aid", "category": "prompt_injection"}]}
    route = respx.get(f"{BASE_URL}/v1/lineage/recent").mock(
        return_value=httpx.Response(200, json=payload)
    )
    c = AgentForgeClient(base_url=BASE_URL)
    out = c.lineage_recent(limit=25)
    assert out == payload
    assert route.called
    assert route.calls.last.request.url.params["limit"] == "25"


@pytest.mark.unit
@respx.mock
def test_recompute_judge_meta_hits_correct_path() -> None:
    """`AgentForgeClient.recompute_judge_meta()` POSTs `/v1/judge/recompute?layer=...`
    and round-trips the metrics payload (sub-plan Next03 §3.4)."""
    payload = {"layer": "external_final", "metrics": {"precision": 0.9}}
    route = respx.post(f"{BASE_URL}/v1/judge/recompute").mock(
        return_value=httpx.Response(200, json=payload)
    )
    c = AgentForgeClient(base_url=BASE_URL)
    out = c.recompute_judge_meta()
    assert out == payload
    assert route.called
    # Verify the layer query-param was sent.
    assert route.calls.last.request.url.params["layer"] == "external_final"


@pytest.mark.unit
@respx.mock
def test_get_coverage_cells_hits_correct_path() -> None:
    """`AgentForgeClient.get_coverage_cells()` GETs `/v1/coverage/cells` and
    round-trips the payload (sub-plan Next03 §3.1)."""
    payload = {
        "cells": [{"category": "prompt_injection", "strategy": "single_turn", "attempts": 3}],
        "total_cells": 72,
        "covered_cells": 1,
    }
    route = respx.get(f"{BASE_URL}/v1/coverage/cells").mock(
        return_value=httpx.Response(200, json=payload)
    )
    c = AgentForgeClient(base_url=BASE_URL)
    assert c.get_coverage_cells() == payload
    assert route.called


@pytest.mark.unit
@respx.mock
def test_cost_regression_lineage_delta_approval_paths() -> None:
    """UI client hits the correct paths for cost / regression / lineage / delta / approval endpoints (respx-mocked)."""
    respx.get(f"{BASE_URL}/v1/cost/today").mock(
        return_value=httpx.Response(200, json={"spend_usd": "0"})
    )
    respx.get(f"{BASE_URL}/v1/cost/projections").mock(
        return_value=httpx.Response(200, json={"scales": []})
    )
    respx.get(f"{BASE_URL}/v1/regression/cases").mock(
        return_value=httpx.Response(200, json={"cases": []})
    )
    respx.get(f"{BASE_URL}/v1/regression/results/latest").mock(
        return_value=httpx.Response(200, json={"rows": []})
    )
    respx.get(f"{BASE_URL}/v1/lineage/aid").mock(
        return_value=httpx.Response(200, json={"attack_id": "aid"})
    )
    respx.get(f"{BASE_URL}/v1/delta/trend").mock(
        return_value=httpx.Response(200, json={"snapshots": []})
    )
    respx.get(f"{BASE_URL}/v1/delta/snapshot/fp").mock(
        return_value=httpx.Response(200, json={"target_fingerprint": "fp"})
    )
    respx.get(f"{BASE_URL}/v1/approval/queue").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    c = AgentForgeClient(base_url=BASE_URL)
    assert c.cost_today()["spend_usd"] == "0"
    assert c.cost_projections()["scales"] == []
    assert c.list_regression_cases()["cases"] == []
    assert c.latest_regression_results()["rows"] == []
    assert c.lineage("aid")["attack_id"] == "aid"
    assert c.delta_trend()["snapshots"] == []
    assert c.delta_snapshot("fp")["target_fingerprint"] == "fp"
    assert c.approval_queue()["items"] == []
