"""Tests for /v1/reports — master plan §4 / §11."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.unit.api.conftest import seed_vuln_report


@pytest.mark.unit
def test_reports_list_filter_by_severity(client: TestClient, seeded_session) -> None:
    """`/v1/reports?severity=high` filters the response set."""
    seed_vuln_report(seeded_session, vr_id="VR-001", severity="high")
    seed_vuln_report(seeded_session, vr_id="VR-002", severity="low")
    seed_vuln_report(seeded_session, vr_id="VR-003", severity="high")
    seeded_session.commit()

    r = client.get("/v1/reports", params={"severity": "high"})
    assert r.status_code == 200
    body = r.json()
    ids = sorted(row["vr_id"] for row in body["reports"])
    assert ids == ["VR-001", "VR-003"]


@pytest.mark.unit
def test_report_detail_by_vr_id(client: TestClient, seeded_session) -> None:
    """`/v1/reports/{vr_id}` returns the VR + its markdown body."""
    seed_vuln_report(
        seeded_session,
        vr_id="VR-EXFIL-9",
        content_markdown="# Exfil 9\n\nBody.",
    )
    seeded_session.commit()

    r = client.get("/v1/reports/VR-EXFIL-9")
    assert r.status_code == 200
    body = r.json()
    assert body["vr_id"] == "VR-EXFIL-9"
    assert "Exfil 9" in body["content_markdown"]


@pytest.mark.unit
def test_report_markdown_endpoint(client: TestClient, seeded_session) -> None:
    """`/v1/reports/{vr_id}.md` returns raw markdown with text/plain content-type (route registered before `{vr_id}`)."""
    seed_vuln_report(
        seeded_session,
        vr_id="VR-MD-1",
        content_markdown="# raw markdown body",
    )
    seeded_session.commit()

    r = client.get("/v1/reports/VR-MD-1.md")
    assert r.status_code == 200
    assert "raw markdown body" in r.text
    assert r.headers["content-type"].startswith("text/plain")


@pytest.mark.unit
def test_report_detail_404(client: TestClient) -> None:
    """Unknown vr_id returns 404."""
    r = client.get("/v1/reports/does-not-exist")
    assert r.status_code == 404
