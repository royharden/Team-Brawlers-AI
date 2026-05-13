"""Sidecar-direct adapter -- POSTs an attack payload to the Co-Pilot sidecar.

The sidecar (``EMR-SO/openemr/agent/copilot-api``) exposes
``POST /v1/copilot/answer`` -- the same surface a clinician's PHP gateway hits.
Hitting it directly is the cleanest first wiring: it skips the OpenEMR PHP
login + CSRF + ``/brief.php`` POST chain that ``openemr_gateway`` would do.

Auth model
----------
The sidecar requires two HMAC headers (see ``EMR-SO/openemr/agent/copilot-api/app/auth.py``):

1. ``X-Copilot-Gateway-Secret`` -- HMAC-compared against the sidecar's
   ``COPILOT_OPENEMR_GATEWAY_SHARED_SECRET`` env var. We send this when our
   own ``SIDECAR_SHARED_SECRET`` env var is non-empty; otherwise we omit and
   trust the operator's local sidecar to have its gateway-secret disabled.
2. ``X-Copilot-Task-Token`` -- short-lived signed task token. Optional if the
   sidecar runs with ``COPILOT_REQUIRE_TASK_TOKEN=0`` (dev fallback). We do
   NOT mint a task token here -- if the sidecar requires it, the operator
   must run their sidecar with ``COPILOT_REQUIRE_TASK_TOKEN=0`` for local
   live-attack testing.

PHI safety
----------
The sidecar's ``VerifiedResponse.claims[].text`` field can contain anything
the LLM produced, including patient names / MRNs / DOBs / SSNs. We scrub the
JSON response through ``scrub_phi_in_obj`` before constructing the
``AdapterResponse`` that lands in ``attack_traces.target_response_json``.

AgDR-0015 (sidecar-direct-adapter-wiring) reserves the decision record.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
from typing import Any

import httpx
from loguru import logger

from agentforge.config import MainConfig, get_settings
from agentforge.observability.scrubber import scrub_phi_in_obj
from agentforge.target_adapter.allowlist import TargetNotAllowed, require_allowed
from agentforge.target_adapter.base import AdapterResponse, TargetAdapter

#: Synthetic patient anchor. The sidecar's task-token check (when enabled)
#: requires the request's ``patient_uuid_hash`` to match the token's bound
#: hash. Since we don't mint a task token, the value here is informational;
#: but we still keep it stable so traces are deduplicatable.
_SYNTHETIC_PATIENT_UUID = "00000000-0000-0000-0000-agentforge0001"
_SYNTHETIC_PATIENT_UUID_HASH = hashlib.sha256(_SYNTHETIC_PATIENT_UUID.encode("utf-8")).hexdigest()

#: Sidecar question field is capped at 500 chars (see copilot-api routes.py).
_SIDECAR_QUESTION_MAX = 500


class SidecarDirectAdapter(TargetAdapter):
    """Synchronous httpx adapter to the Co-Pilot sidecar."""

    name = "sidecar_direct"

    def __init__(
        self,
        settings: MainConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._url = self._settings.adapter.copilot_sidecar_url.rstrip("/") + "/v1/copilot/answer"
        self._timeout_s = max(1, self._settings.budget.per_attack_timeout_s)
        # `transport` is a test seam (httpx.MockTransport) and MUST stay None
        # in production. The orchestrator never passes it.
        self._transport = transport

    # ----------------------------------------------------------------- public

    def describe_action(self, attack: Any) -> str:
        return f"POST {self._url} (sidecar direct)"

    def execute(self, attack: Any) -> AdapterResponse:  # type: ignore[override]
        """Send the attack's rendered_prompt to the sidecar; return normalized response.

        The base class declares ``async def execute``; the orchestrator calls
        synchronously (``orchestrator.py:_safe_execute``), so the production
        contract is sync. We match the orchestrator.
        """
        # Allowlist gate -- fail fast before any network IO.
        try:
            require_allowed(self._url, settings=self._settings)
        except TargetNotAllowed as exc:
            return AdapterResponse(
                status_code=0,
                error=f"allowlist_reject: {exc}",
            )

        # Build the request body from the attack.
        body = self._build_request_body(attack)
        headers = self._build_headers()

        # Network call, timing wrap.
        t0 = time.perf_counter()
        client_kwargs: dict[str, Any] = {"timeout": self._timeout_s}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            with httpx.Client(**client_kwargs) as client:
                resp = client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning("Sidecar timeout after {:.0f}ms: {}", elapsed_ms, exc)
            return AdapterResponse(
                status_code=0,
                latency_ms=elapsed_ms,
                error=f"timeout: {exc}",
            )
        except httpx.RequestError as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning("Sidecar request error: {}", exc)
            return AdapterResponse(
                status_code=0,
                latency_ms=elapsed_ms,
                error=f"request_error: {exc}",
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Parse response body (may not be JSON on 4xx/5xx).
        body_json: dict[str, Any] | None = None
        body_text = resp.text
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                parsed = resp.json()
                if isinstance(parsed, dict):
                    body_json = parsed
            except (json.JSONDecodeError, ValueError):
                body_json = None

        # PHI scrub before persistence.
        if body_json is not None:
            body_json = scrub_phi_in_obj(body_json)
            # Re-render body_text from the scrubbed JSON so the trace's text
            # and json representations agree. json.dumps on a recursively-
            # scrubbed dict can in principle raise on non-serializable types
            # we did not anticipate; in that case keep the original body_text.
            with contextlib.suppress(TypeError, ValueError):
                body_text = json.dumps(body_json, ensure_ascii=False)
        else:
            # Non-JSON body: scrub the raw text.
            scrubbed = scrub_phi_in_obj(body_text)
            if isinstance(scrubbed, str):
                body_text = scrubbed

        error_msg: str | None = None
        if resp.status_code >= 400:
            error_msg = f"http_{resp.status_code}"

        # Filter response headers to ASCII-string values only (some HTTP
        # libraries hand back bytes for non-ASCII headers; AdapterResponse
        # is dict[str, str]).
        safe_headers = {k: v for k, v in resp.headers.items() if isinstance(v, str)}

        return AdapterResponse(
            status_code=resp.status_code,
            headers=safe_headers,
            body_text=body_text,
            body_json=body_json,
            latency_ms=elapsed_ms,
            cost_usd=0.0,  # Sidecar does not report cost in the response; estimated elsewhere.
            error=error_msg,
        )

    # ---------------------------------------------------------------- private

    def _build_request_body(self, attack: Any) -> dict[str, Any]:
        """Coerce a MutatedAttack (or duck-typed equivalent) into the sidecar's
        ``_CopilotAnswerRequest`` schema (copilot-api routes.py:284-299).
        """
        # rendered_prompt is the primary question text; fall back to seed_id
        # if a mutator chain didn't render text (e.g., document-only attacks).
        prompt = getattr(attack, "rendered_prompt", None) or getattr(
            attack, "seed_id", "agentforge-synthetic-attack"
        )
        if not isinstance(prompt, str):
            prompt = str(prompt)
        question = prompt[:_SIDECAR_QUESTION_MAX]

        attack_id = getattr(attack, "attack_id", None) or "agentforge-synthetic"
        if not isinstance(attack_id, str):
            attack_id = str(attack_id)

        return {
            "trace_id": attack_id,
            "patient_uuid_hash": _SYNTHETIC_PATIENT_UUID_HASH,
            "question": question,
            "use_case": "pre_room_brief",
            "documents": None,
            "packets": None,
        }

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        secret = self._settings.adapter.sidecar_shared_secret
        if secret:
            headers["X-Copilot-Gateway-Secret"] = secret
        return headers


__all__ = ["SidecarDirectAdapter"]
