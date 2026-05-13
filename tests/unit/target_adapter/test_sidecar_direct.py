"""SidecarDirectAdapter -- happy path, allowlist guard, error envelopes, PHI scrub.

All tests are hermetic: httpx.MockTransport is the wire, no real network IO.
The adapter accepts an optional `transport=` kwarg (test seam, never used in
production); the orchestrator constructs the adapter without it.

Live integration test lives in tests/integration/target_adapter/.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentforge.config import (
    AdapterConfig,
    BudgetConfig,
    MainConfig,
)
from agentforge.target_adapter.base import AdapterResponse
from agentforge.target_adapter.sidecar_direct import SidecarDirectAdapter


def _settings_with_url(url: str, *, secret: str = "") -> MainConfig:
    """Build a MainConfig whose adapter.copilot_sidecar_url points at `url`.

    We use ``model_construct`` to bypass pydantic env-loading; the test
    receives a fully wired config tree without reading the real .env.
    """
    cfg = MainConfig.model_construct(
        redteam_provider="openrouter",
        platform_db_url="sqlite:///:memory:",
        agent_message_signing_secret="test-secret",
        pricing_yml_freshness_days=30,
        anthropic=MainConfig.model_fields["anthropic"].default_factory(),  # type: ignore[misc]
        openrouter=MainConfig.model_fields["openrouter"].default_factory(),  # type: ignore[misc]
        fireworks=MainConfig.model_fields["fireworks"].default_factory(),  # type: ignore[misc]
        langfuse=MainConfig.model_fields["langfuse"].default_factory(),  # type: ignore[misc]
        budget=BudgetConfig.model_construct(per_attack_timeout_s=5),
        adapter=AdapterConfig.model_construct(
            copilot_sidecar_url=url,
            target_allowlist=["localhost", "127.0.0.1", "host.docker.internal"],
            sidecar_shared_secret=secret,
        ),
    )
    return cfg


class _FakeAttack:
    """Duck-typed MutatedAttack -- adapter only reads attack_id / seed_id / rendered_prompt."""

    def __init__(
        self,
        *,
        attack_id: str = "test-attack-uuid-0001",
        seed_id: str = "test_seed",
        rendered_prompt: str = "What labs did this patient have last visit?",
    ) -> None:
        self.attack_id = attack_id
        self.seed_id = seed_id
        self.rendered_prompt = rendered_prompt


def _make_adapter(
    url: str,
    handler: Any,
    *,
    secret: str = "",
) -> SidecarDirectAdapter:
    """Build an adapter wired to a MockTransport-backed httpx client."""
    transport = httpx.MockTransport(handler)
    settings = _settings_with_url(url, secret=secret)
    return SidecarDirectAdapter(settings=settings, transport=transport)


# --------------------------------------------------------------------------- happy path


@pytest.mark.unit
def test_happy_path_returns_normalized_response() -> None:
    """Sidecar returns 200 JSON; adapter returns AdapterResponse with parsed body."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(
            200,
            json={
                "answer_type": "patient_brief",
                "claims": [{"text": "Patient had recent CBC.", "claim_type": "lab"}],
                "trace_id": "test-attack-uuid-0001",
                "verifier_status": "passed",
                "selected_tools": [],
            },
        )

    adapter = _make_adapter("http://localhost:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert isinstance(result, AdapterResponse)
    assert result.status_code == 200
    assert result.error is None
    assert result.latency_ms >= 0
    assert result.body_json is not None
    assert result.body_json["verifier_status"] == "passed"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://localhost:8000/v1/copilot/answer"


@pytest.mark.unit
def test_happy_path_body_includes_required_sidecar_fields() -> None:
    """Request body matches the sidecar's _CopilotAnswerRequest schema."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"answer_type": "ok", "claims": []})

    adapter = _make_adapter("http://localhost:8000", handler)
    adapter.execute(_FakeAttack(rendered_prompt="diagnose this rash"))

    body = captured["body"]
    assert set(body.keys()) >= {
        "trace_id",
        "patient_uuid_hash",
        "question",
        "use_case",
        "documents",
        "packets",
    }
    assert body["question"] == "diagnose this rash"
    assert body["use_case"] == "pre_room_brief"
    assert len(body["patient_uuid_hash"]) == 64  # sha256 hex
    assert all(c in "0123456789abcdef" for c in body["patient_uuid_hash"])


@pytest.mark.unit
def test_long_prompt_truncated_to_500_chars() -> None:
    """Sidecar caps question at 500 chars; adapter truncates before sending."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"answer_type": "ok", "claims": []})

    adapter = _make_adapter("http://localhost:8000", handler)
    adapter.execute(_FakeAttack(rendered_prompt="A" * 1000))

    assert len(captured["body"]["question"]) == 500


# --------------------------------------------------------------------------- auth


@pytest.mark.unit
def test_shared_secret_header_sent_when_set() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"answer_type": "ok", "claims": []})

    adapter = _make_adapter("http://localhost:8000", handler, secret="hex-secret-abc")
    adapter.execute(_FakeAttack())

    # httpx lowercases header keys in the dict view.
    assert captured["headers"].get("x-copilot-gateway-secret") == "hex-secret-abc"


@pytest.mark.unit
def test_shared_secret_header_omitted_when_empty() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"answer_type": "ok", "claims": []})

    adapter = _make_adapter("http://localhost:8000", handler, secret="")
    adapter.execute(_FakeAttack())

    assert "x-copilot-gateway-secret" not in captured["headers"]


# --------------------------------------------------------------------------- allowlist guard


@pytest.mark.unit
def test_off_allowlist_host_rejected_before_network() -> None:
    """Adapter must reject before any HTTP. handler raises if called."""

    def handler(_: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("Network call should not happen for off-allowlist URL")

    adapter = _make_adapter("http://evil.example.com:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert result.status_code == 0
    assert result.error is not None
    assert "allowlist_reject" in result.error


# --------------------------------------------------------------------------- error envelopes


@pytest.mark.unit
def test_http_4xx_sets_error_field() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "gateway secret missing"})

    adapter = _make_adapter("http://localhost:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert result.status_code == 403
    assert result.error == "http_403"
    assert result.body_json is not None
    assert result.body_json.get("detail") == "gateway secret missing"


@pytest.mark.unit
def test_timeout_returns_timeout_envelope() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated read timeout")

    adapter = _make_adapter("http://localhost:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert result.status_code == 0
    assert result.error is not None
    assert "timeout" in result.error
    assert result.latency_ms >= 0


@pytest.mark.unit
def test_connection_refused_returns_request_error_envelope() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = _make_adapter("http://localhost:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert result.status_code == 0
    assert result.error is not None
    assert "request_error" in result.error


# --------------------------------------------------------------------------- PHI scrub


@pytest.mark.unit
def test_phi_in_response_body_scrubbed() -> None:
    """If the sidecar returns a string matching a PHI pattern (SSN), the adapter
    must scrub it from both body_text and body_json before constructing the
    trace.
    """
    leaky_ssn = "123-45-6789"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "answer_type": "patient_brief",
                "claims": [
                    {
                        "text": f"Patient SSN on file: {leaky_ssn}",
                        "claim_type": "demographic",
                    }
                ],
                "verifier_status": "passed",
            },
        )

    adapter = _make_adapter("http://localhost:8000", handler)
    result = adapter.execute(_FakeAttack())

    assert result.status_code == 200
    assert result.body_json is not None
    assert leaky_ssn not in result.body_text
    assert leaky_ssn not in json.dumps(result.body_json)


# --------------------------------------------------------------------------- describe_action


@pytest.mark.unit
def test_describe_action_includes_url() -> None:
    settings = _settings_with_url("http://localhost:8000")
    adapter = SidecarDirectAdapter(settings=settings)
    descr = adapter.describe_action(_FakeAttack())
    assert "http://localhost:8000/v1/copilot/answer" in descr
    assert "sidecar direct" in descr.lower()


# --------------------------------------------------------------------------- name attribute


@pytest.mark.unit
def test_adapter_name_is_sidecar_direct() -> None:
    assert SidecarDirectAdapter.name == "sidecar_direct"
