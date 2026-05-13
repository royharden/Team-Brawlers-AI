"""Tests for `agentforge.api.run_runner` — sub-plan Next05 §1.

Covers the in-memory state tracker + the SSE generator. The thread that
calls `build_orchestrator` is monkeypatched in the route tests so we
don't actually fire LLMs here.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from agentforge.api import run_runner


@pytest.fixture(autouse=True)
def _reset_active_runs():
    with run_runner._lock:
        run_runner._active_runs.clear()
    yield
    with run_runner._lock:
        run_runner._active_runs.clear()


@pytest.mark.unit
def test_get_run_state_returns_none_for_unknown_run() -> None:
    assert run_runner.get_run_state("does-not-exist") is None


@pytest.mark.unit
def test_set_and_patch_round_trip() -> None:
    """`_set` records a state; `_patch` updates fields by name."""
    state = run_runner.RunState(run_id="rid-1", status="pending")
    run_runner._set(state)
    after = run_runner._patch("rid-1", status="running", attacks_executed=3)
    assert after is not None
    assert after.status == "running"
    assert after.attacks_executed == 3
    # Read-back via the public API.
    fetched = run_runner.get_run_state("rid-1")
    assert fetched is not None
    assert fetched.attacks_executed == 3


@pytest.mark.unit
def test_list_active_run_ids_filters_to_running() -> None:
    """`list_active_run_ids` returns only `status == "running"` ids."""
    run_runner._set(run_runner.RunState(run_id="r1", status="running"))
    run_runner._set(run_runner.RunState(run_id="r2", status="completed"))
    run_runner._set(run_runner.RunState(run_id="r3", status="pending"))
    active = run_runner.list_active_run_ids()
    assert active == ["r1"]


@pytest.mark.unit
def test_stream_run_events_yields_terminal_state_then_stops() -> None:
    """`stream_run_events` yields the current state, waits for terminal,
    yields once more, then stops."""
    run_runner._set(run_runner.RunState(run_id="rid-stream", status="running"))

    # Flip to "completed" from another thread after a tick so the generator
    # observes the transition.
    def _flip_to_completed() -> None:
        time.sleep(0.4)
        run_runner._patch(
            "rid-stream",
            status="completed",
            attacks_executed=1,
            findings_written=0,
        )

    threading.Thread(target=_flip_to_completed, daemon=True).start()

    events: list[str] = []
    gen = run_runner.stream_run_events("rid-stream", poll_interval_s=0.1)
    for ev in gen:
        events.append(ev)
        if len(events) >= 5:  # safety cap so a stuck test doesn't hang CI
            break

    assert events, "should yield at least one event"
    # First event = the initial running state.
    assert "running" in events[0]
    # Some later event = terminal (completed) state.
    assert any("completed" in e for e in events)
    # All events are SSE-formatted (`data: {...}\n\n`) or `: keep-alive`.
    for e in events:
        assert e.startswith("data: ") or e.startswith(": keep-alive")


@pytest.mark.unit
def test_stream_run_events_unknown_run_emits_error_event() -> None:
    """A request to stream an unknown run_id yields an `event: error` payload
    and stops immediately."""
    gen = run_runner.stream_run_events("nope", poll_interval_s=0.05)
    events = list(gen)
    assert len(events) == 1
    assert "event: error" in events[0]
    assert "nope" in events[0]


@pytest.mark.unit
def test_stream_event_serialization_round_trip() -> None:
    """Each `data:` event is a parseable JSON RunState."""
    state = run_runner.RunState(
        run_id="rid-x",
        status="running",
        attacks_executed=4,
        findings_written=1,
    )
    raw = run_runner._stream_event_for_state(state)
    assert raw.startswith("data: ")
    assert raw.endswith("\n\n")
    payload = raw[len("data: ") : -2]  # strip prefix + trailing newlines
    parsed = json.loads(payload)
    assert parsed["run_id"] == "rid-x"
    assert parsed["attacks_executed"] == 4
