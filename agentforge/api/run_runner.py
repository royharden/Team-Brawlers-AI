"""Background-thread runner for `POST /v1/runs/start` — Next05 §1.

Spawns the orchestrator's `step()` + `end_run()` sequence in a daemon
thread so the HTTP request returns immediately with a `run_id`. Tracks
in-flight state in a module-level dict that both the polling endpoint
(`GET /v1/runs/{run_id}/state`) and the SSE endpoint
(`GET /v1/runs/{run_id}/stream`) read from.

Concurrency model: one daemon thread per requested run. The orchestrator
is independently safe — each construction gets its own session factory
session per persistence call (AgDR-0017). We cap concurrency at the API
layer (max one active run at a time per process) to keep the LLM-call
load predictable; further runs queue or 429 depending on the operator's
policy. Today we 429.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel

from agentforge.orchestrator.factory import build_orchestrator
from agentforge.target_adapter.sidecar_direct import SidecarDirectAdapter

# --------------------------------------------------------------------------- state


class RunState(BaseModel):
    """Snapshot of one in-flight or recently-finished background run."""

    run_id: str
    status: str = "pending"  # pending | running | completed | failed | halted
    run_type: str = "smoke"
    count: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attacks_executed: int = 0
    findings_written: int = 0
    halted: bool = False
    halt_reason: str | None = None
    error: str | None = None


_lock = threading.Lock()
_active_runs: dict[str, RunState] = {}


def get_run_state(run_id: str) -> RunState | None:
    """Read a run's current state from the in-memory tracker."""
    with _lock:
        state = _active_runs.get(run_id)
    return state.model_copy() if state is not None else None


def list_active_run_ids() -> list[str]:
    """Return run_ids that are currently `running` (not yet finished)."""
    with _lock:
        return [rid for rid, st in _active_runs.items() if st.status == "running"]


def _set(state: RunState) -> None:
    with _lock:
        _active_runs[state.run_id] = state


def _patch(run_id: str, **fields: Any) -> RunState | None:
    with _lock:
        state = _active_runs.get(run_id)
        if state is None:
            return None
        updated = state.model_copy(update=fields)
        _active_runs[run_id] = updated
        return updated


# --------------------------------------------------------------------------- runner


def _run_thread(run_id: str, run_type: str, count: int) -> None:
    """Background body. Builds the orchestrator, runs one step(), end_run()s.

    Catches any exception and stamps `status="failed"` + `error=...` so the
    UI's polling loop sees the terminal state.
    """
    _patch(run_id, status="running", started_at=datetime.now(UTC))
    try:
        # SidecarDirectAdapter() reads sidecar URL + secret from MainConfig.
        # Adapter `execute` signature is `Any` for flexibility but the orchestrator
        # protocol declares MutatedAttack — same shape as cli.py's call.
        orchestrator = build_orchestrator(
            SidecarDirectAdapter(),  # type: ignore[arg-type]
            run_type=run_type,  # type: ignore[arg-type]
            run_id=run_id,
        )
        result = orchestrator.step(batch_size=count)
        status = "halted" if result.halted else "completed"
        halt_reason = result.halt_reason.value if result.halt_reason else None
        orchestrator.end_run(status=status, halt_reason=halt_reason)
        _patch(
            run_id,
            status=status,
            attacks_executed=result.attacks_executed,
            findings_written=result.findings_written,
            halted=result.halted,
            halt_reason=halt_reason,
            finished_at=datetime.now(UTC),
        )
    except Exception as exc:
        logger.exception("Background run {} failed: {}", run_id, exc)
        _patch(
            run_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now(UTC),
        )


def start_background_run(run_type: str = "smoke", count: int = 1) -> RunState:
    """Spawn a daemon thread that runs `orchestrator.step(batch_size=count)`.

    Returns the initial `RunState` (status="pending"); the thread updates it
    in place. Refuses to start if another run is already `running` (returns
    a state with `error="already_running"` — caller handles 429).
    """
    if list_active_run_ids():
        # Caller will 429 on this — keep concurrency at 1 to keep LLM-call
        # load predictable for the demo.
        return RunState(
            run_id="",
            status="failed",
            run_type=run_type,
            count=count,
            error="another run is already in flight",
        )
    run_id = str(uuid.uuid4())
    state = RunState(run_id=run_id, status="pending", run_type=run_type, count=count)
    _set(state)
    thread = threading.Thread(
        target=_run_thread,
        args=(run_id, run_type, count),
        daemon=True,
        name=f"run-{run_id[:8]}",
    )
    thread.start()
    return state


def _stream_event_for_state(state: RunState) -> str:
    """Format one SSE `data:` event payload for the given RunState."""
    return f"data: {state.model_dump_json()}\n\n"


def stream_run_events(run_id: str, *, poll_interval_s: float = 1.0):
    """Generator yielding SSE events for one run.

    Stops when the run reaches a terminal state (completed/failed/halted)
    AND one extra tick has been emitted so consumers get the final state.
    Yields a heartbeat comment every 15s if status hasn't changed (keeps
    proxies from killing the connection).
    """
    last_serialized: str | None = None
    last_heartbeat = time.monotonic()
    terminal_emitted = False
    terminal_states = {"completed", "failed", "halted"}

    while True:
        state = get_run_state(run_id)
        if state is None:
            yield ("event: error\n" f'data: {{"error": "run_id not tracked: {run_id}"}}\n\n')
            return
        serialized = state.model_dump_json()
        if serialized != last_serialized:
            yield _stream_event_for_state(state)
            last_serialized = serialized
            last_heartbeat = time.monotonic()
        elif time.monotonic() - last_heartbeat > 15:
            yield ": keep-alive\n\n"
            last_heartbeat = time.monotonic()

        if state.status in terminal_states:
            if terminal_emitted:
                return
            terminal_emitted = True
        time.sleep(poll_interval_s)


__all__ = [
    "RunState",
    "get_run_state",
    "list_active_run_ids",
    "start_background_run",
    "stream_run_events",
]
