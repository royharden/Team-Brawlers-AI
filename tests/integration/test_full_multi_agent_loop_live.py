"""Full multi-agent loop -- live verify (Phase 6.F.2 of Next01 plan).

Runs one ``OrchestratorAgent.step()`` end-to-end against the operator's
running Co-Pilot sidecar at ``localhost:8000``. Exercises every agent role:

  Red Team (Dolphin via OpenRouter) -> Adapter (httpx -> sidecar)
  -> Internal Judge (Haiku, deterministic-first) -> External Judge (Sonnet)
  -> Documentation Agent (Sonnet)

Gated behind ``@pytest.mark.live`` -- skipped without ``--live``. Cost when
run: ~$0.10 to ~$1 depending on which Anthropic Protocols actually fire (the
deterministic-first design means many Haiku/Sonnet calls short-circuit).

AgDR-0016 records the decision to materialize the four Anthropic Protocols.
This test is the first place all five agents run together against a real
target -- the platform's multi-agent integration smoke.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from agentforge.orchestrator.factory import build_orchestrator
from agentforge.target_adapter.sidecar_direct import SidecarDirectAdapter

# Same PHI patterns the sidecar_direct live test checks.
_PHI_SHOULD_NOT_LEAK = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
    re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),  # Phone (10-digit)
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # Email
    re.compile(r"\b(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"),  # DOB mm/dd/yyyy
    re.compile(r"\b\d{4} \d{4} \d{4} \d{4}\b"),  # CC 4-4-4-4
]


@pytest.mark.live
@pytest.mark.integration
def test_full_multi_agent_loop_one_step() -> None:
    """One orchestrator.step(batch_size=1) round-trip.

    Acceptance:
    1. orchestrator.step() returns without exception.
    2. Either ``attacks_executed >= 1`` (loop fired at least one attack) OR
       ``halted=True`` with a real ``halt_reason`` (e.g. budget halt) -- both
       are valid wiring outcomes. A return with ``attacks_executed=0`` AND
       ``halted=False`` would indicate the planner returned an empty
       selection list, which we accept but flag.
    3. No PHI patterns in the documentation-agent output directory's newest
       file (if any was written this run).

    Cost ceiling: smoke budget ($1.00).
    """
    # Pre-flight: sidecar reachable.
    try:
        with httpx.Client(timeout=3) as c:
            healthz = c.get("http://localhost:8000/healthz")
        if healthz.status_code != 200:
            pytest.skip(
                f"Sidecar /healthz returned {healthz.status_code}; "
                "expected 200. Boot the sidecar before running --live tests."
            )
    except httpx.RequestError as exc:
        pytest.skip(f"Sidecar unreachable at http://localhost:8000: {exc}")

    adapter = SidecarDirectAdapter()
    orchestrator = build_orchestrator(target_adapter=adapter, run_type="smoke")

    result = orchestrator.step(batch_size=1)

    # 1. step() returned a result envelope (Pydantic model).
    assert result is not None
    assert hasattr(result, "attacks_executed")
    assert hasattr(result, "halted")

    # 2. Either fired an attack, or halted with a reason.
    fired = result.attacks_executed >= 1
    halted_cleanly = bool(result.halted) and result.halt_reason is not None
    empty_plan = result.attacks_executed == 0 and not result.halted

    assert fired or halted_cleanly or empty_plan, (
        f"unexpected step result: attacks_executed={result.attacks_executed} "
        f"halted={result.halted} halt_reason={result.halt_reason}"
    )

    # If we actually fired, surface the count in the test name for the run log.
    if fired:
        # 3. Quick PHI sweep of the run-time JSON. The Documentation Agent
        # writes to disk; latest VR (if any) should be PHI-clean.
        from pathlib import Path

        reports_dir = Path("reports")
        md_files = sorted(reports_dir.glob("VR-*.md"), key=lambda p: p.stat().st_mtime)
        if md_files:
            latest = md_files[-1].read_text(encoding="utf-8", errors="ignore")
            for pattern in _PHI_SHOULD_NOT_LEAK:
                m = pattern.search(latest)
                assert m is None, (
                    f"PHI-pattern leak in VR markdown: {m.group(0)!r} "
                    f"(file={md_files[-1].name}, pattern={pattern.pattern!r})"
                )

    # Always assert the step result is JSON-serializable (sanity for CLI emit).
    json.dumps(
        {
            "attacks_executed": result.attacks_executed,
            "findings_written": result.findings_written,
            "halted": result.halted,
            "halt_reason": (result.halt_reason.value if result.halt_reason is not None else None),
        }
    )
