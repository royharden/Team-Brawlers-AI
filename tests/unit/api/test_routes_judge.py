"""Tests for /v1/judge/recompute — sub-plan Next03 §3.4.

The route delegates to ``agentforge.judge.meta_eval.runner.run_meta_eval``.
We mock the runner so the route tests stay hermetic — the runner itself
is covered by ``tests/unit/judge/meta_eval/test_runner.py``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agentforge.judge.meta_eval.metrics import JudgeMetrics


def _stub_metrics(layer: str = "external_final") -> JudgeMetrics:
    """Build a JudgeMetrics with non-default values so we can detect round-trip."""
    return JudgeMetrics(
        layer=layer,  # type: ignore[arg-type]
        n=4,
        n_correct=3,
        n_false_positive=1,
        n_false_negative=0,
        n_abstain=0,
        precision=0.75,
        recall=0.80,
        f1=0.77,
        krippendorff_alpha=0.71,
        floor_met={"precision": True, "recall": True, "f1": True},
    )


@pytest.mark.unit
def test_judge_recompute_calls_runner_and_returns_metrics(client: TestClient) -> None:
    """`POST /v1/judge/recompute` calls run_meta_eval(layer=...) and returns the
    serialized metrics (sub-plan Next03 §3.4)."""
    with patch(
        "agentforge.judge.meta_eval.runner.run_meta_eval",
        return_value=_stub_metrics(),
    ) as run_mock:
        r = client.post("/v1/judge/recompute")
    assert r.status_code == 200
    body = r.json()
    assert body["layer"] == "external_final"
    assert body["metrics"]["precision"] == pytest.approx(0.75, abs=1e-6)
    assert body["metrics"]["floor_met"]["precision"] is True
    run_mock.assert_called_once()
    # Default layer is external_final.
    kwargs = run_mock.call_args.kwargs
    assert kwargs.get("layer") == "external_final"


@pytest.mark.unit
def test_judge_recompute_honors_layer_query_param(client: TestClient) -> None:
    """`?layer=internal_progress` is forwarded to the runner (sub-plan Next03 §3.4)."""
    metrics = _stub_metrics(layer="internal_progress")
    with patch(
        "agentforge.judge.meta_eval.runner.run_meta_eval",
        return_value=metrics,
    ) as run_mock:
        r = client.post("/v1/judge/recompute", params={"layer": "internal_progress"})
    assert r.status_code == 200
    assert r.json()["layer"] == "internal_progress"
    assert run_mock.call_args.kwargs.get("layer") == "internal_progress"


@pytest.mark.unit
def test_judge_recompute_invalid_layer_rejected(client: TestClient) -> None:
    """The Literal-typed `layer` query parameter rejects unknown values
    (FastAPI returns 422). Defends the route from typos that would otherwise
    silently default."""
    r = client.post("/v1/judge/recompute", params={"layer": "bogus_layer"})
    assert r.status_code == 422


@pytest.mark.unit
def test_judge_recompute_500_on_runner_exception(client: TestClient) -> None:
    """Runner exceptions surface as a 500 with the underlying detail (sub-plan
    Next03 §3.4)."""
    with patch(
        "agentforge.judge.meta_eval.runner.run_meta_eval",
        side_effect=RuntimeError("boom"),
    ):
        r = client.post("/v1/judge/recompute")
    assert r.status_code == 500
    assert "boom" in r.json()["detail"]
