"""Background-thread runner for `POST /v1/runs/start` — Next05 §1 + Next06 §5.

Spawns the orchestrator's `step()` + `end_run()` sequence in a daemon
thread so the HTTP request returns immediately with a `run_id`. Tracks
in-flight state in a module-level dict that both the polling endpoint
(`GET /v1/runs/{run_id}/state`) and the SSE endpoint
(`GET /v1/runs/{run_id}/stream`) read from.

Concurrency model (Next06 §5 — closes AgDR-0025 follow-on #2):
  - ``BUDGET_MAX_CONCURRENT_RUNS`` (default 1) caps how many runs may
    execute the orchestrator step loop in parallel; a module-level
    ``threading.Semaphore`` enforces it.
  - ``BUDGET_MAX_QUEUED_RUNS`` (default 4) caps how many additional
    starts may sit in ``status="pending"`` waiting on a slot before
    ``start_background_run`` refuses with an explicit error.
  - The thread spawns immediately on every accepted start; it sits in
    ``pending`` until the semaphore acquire returns, then transitions
    to ``running``. This keeps the SSE / polling endpoint responsive
    for queued runs from the moment the API returns the run_id.

Persistence safety: each orchestrator construction gets its own session
factory session per call (AgDR-0017). Two parallel step loops do NOT
share a session — the SQLite write-side serializes anyway, so the
practical concurrency cap on a SQLite backend is small even though the
API allows higher values.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel

from agentforge.config import get_settings
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

# Next06 §5: concurrency gate. Lazy-initialized on first start so the
# module import doesn't touch settings (and tests can override
# BUDGET_MAX_CONCURRENT_RUNS via env before any run fires).
_sem_lock = threading.Lock()
_semaphore: threading.Semaphore | None = None
_semaphore_limit: int = 0


def _get_semaphore() -> threading.Semaphore:
    """Lazy singleton sized from ``BudgetConfig.max_concurrent_runs``.

    If the limit changes between calls (e.g. operator hot-reloads the
    env), the semaphore is rebuilt. Existing waiters on the old
    semaphore complete on their original limit — the new one takes
    over for fresh starts.
    """
    global _semaphore, _semaphore_limit
    cfg = get_settings()
    limit = max(1, int(cfg.budget.max_concurrent_runs))
    with _sem_lock:
        if _semaphore is None or _semaphore_limit != limit:
            _semaphore = threading.Semaphore(limit)
            _semaphore_limit = limit
    return _semaphore


def reset_semaphore_for_tests() -> None:
    """Drop the cached semaphore so the next call picks up an env change.

    Used only by tests that mutate ``BUDGET_MAX_CONCURRENT_RUNS`` via
    monkeypatch; production code should never call this.
    """
    global _semaphore, _semaphore_limit
    with _sem_lock:
        _semaphore = None
        _semaphore_limit = 0


def get_run_state(run_id: str) -> RunState | None:
    """Read a run's current state from the in-memory tracker."""
    with _lock:
        state = _active_runs.get(run_id)
    return state.model_copy() if state is not None else None


def list_active_run_ids() -> list[str]:
    """Return run_ids that are currently `running` (not yet finished)."""
    with _lock:
        return [rid for rid, st in _active_runs.items() if st.status == "running"]


def list_non_terminal_run_ids() -> list[str]:
    """Return run_ids with status in {pending, running} — the queue depth."""
    with _lock:
        return [rid for rid, st in _active_runs.items() if st.status in {"pending", "running"}]


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
    """Background body. Acquires a concurrency slot, builds the orchestrator,
    runs one step(), end_run()s.

    Sits in ``status="pending"`` until ``semaphore.acquire()`` returns
    (i.e. another run finished and freed a slot), then transitions to
    ``running``. Catches any exception and stamps ``status="failed"``
    so the UI's polling loop always sees a terminal state.
    """
    sem = _get_semaphore()
    sem.acquire()
    try:
        _patch(run_id, status="running", started_at=datetime.now(UTC))
        try:
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
    finally:
        sem.release()


def start_background_run(run_type: str = "smoke", count: int = 1) -> RunState:
    """Spawn a daemon thread that runs ``orchestrator.step(batch_size=count)``.

    Returns the initial ``RunState`` (``status="pending"``); the thread
    transitions to ``running`` once a concurrency slot opens. Refuses
    only when the configured queue depth
    (``max_concurrent_runs + max_queued_runs``) is exceeded, returning
    a state with ``error="queue depth reached: ..."`` so the API can
    map to 429.
    """
    cfg = get_settings()
    max_in_flight = max(1, int(cfg.budget.max_concurrent_runs)) + max(
        0, int(cfg.budget.max_queued_runs)
    )
    in_flight = len(list_non_terminal_run_ids())
    if in_flight >= max_in_flight:
        return RunState(
            run_id="",
            status="failed",
            run_type=run_type,
            count=count,
            error=(
                f"queue depth reached: {in_flight} runs pending/running, " f"max={max_in_flight}"
            ),
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
    "list_non_terminal_run_ids",
    "reset_semaphore_for_tests",
    "start_background_run",
    "stream_run_events",
]
