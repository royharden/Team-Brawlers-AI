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


# --------------------------------------------------------------------------- Next06 §5


@pytest.mark.unit
def test_list_non_terminal_run_ids_includes_pending_and_running() -> None:
    """`list_non_terminal_run_ids` is the queue-depth counter — it
    surfaces both `pending` (queued, waiting on semaphore) and `running`
    states, but NOT terminal ones."""
    run_runner._set(run_runner.RunState(run_id="r-pend", status="pending"))
    run_runner._set(run_runner.RunState(run_id="r-run", status="running"))
    run_runner._set(run_runner.RunState(run_id="r-done", status="completed"))
    run_runner._set(run_runner.RunState(run_id="r-fail", status="failed"))
    run_runner._set(run_runner.RunState(run_id="r-halt", status="halted"))
    queue = run_runner.list_non_terminal_run_ids()
    assert sorted(queue) == ["r-pend", "r-run"]


@pytest.mark.unit
def test_start_background_run_refuses_when_queue_depth_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When `pending+running` count reaches `max_concurrent + max_queued`,
    the next start returns `error="queue depth reached: ..."`."""
    monkeypatch.setattr(
        run_runner,
        "list_non_terminal_run_ids",
        lambda: ["r1", "r2", "r3", "r4", "r5"],  # 5 already in flight
    )

    class _StubCfg:
        class budget:
            max_concurrent_runs = 1
            max_queued_runs = 4  # total cap = 5; already at limit

    monkeypatch.setattr(run_runner, "get_settings", lambda: _StubCfg())

    state = run_runner.start_background_run("smoke", 1)
    assert state.run_id == ""
    assert state.status == "failed"
    assert state.error is not None
    assert state.error.startswith("queue depth reached")


@pytest.mark.unit
def test_start_background_run_accepts_when_queue_has_slack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4 in flight with limit=5 → accept the 5th, spawn the thread."""

    class _StubCfg:
        class budget:
            max_concurrent_runs = 2
            max_queued_runs = 3  # total = 5; 4 in flight is OK

    monkeypatch.setattr(run_runner, "get_settings", lambda: _StubCfg())
    monkeypatch.setattr(
        run_runner,
        "list_non_terminal_run_ids",
        lambda: ["r1", "r2", "r3", "r4"],
    )
    # Don't actually run the orchestrator — replace the thread body.
    spawned: list[str] = []

    def _stub_thread(target, args, daemon, name):
        spawned.append(args[0])

        class _T:
            def start(self_inner) -> None:
                pass

        return _T()

    monkeypatch.setattr(run_runner.threading, "Thread", _stub_thread)

    state = run_runner.start_background_run("smoke", 1)
    assert state.run_id  # non-empty
    assert state.status == "pending"
    assert state.run_id in spawned


@pytest.mark.unit
def test_semaphore_picks_up_max_concurrent_runs_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_get_semaphore` builds a Semaphore of size `max_concurrent_runs`
    and rebuilds when the limit changes."""

    class _Cfg1:
        class budget:
            max_concurrent_runs = 1

    class _Cfg3:
        class budget:
            max_concurrent_runs = 3

    run_runner.reset_semaphore_for_tests()
    monkeypatch.setattr(run_runner, "get_settings", lambda: _Cfg1())
    sem1 = run_runner._get_semaphore()
    assert run_runner._semaphore_limit == 1
    assert sem1 is run_runner._get_semaphore()  # cached

    monkeypatch.setattr(run_runner, "get_settings", lambda: _Cfg3())
    sem3 = run_runner._get_semaphore()
    assert run_runner._semaphore_limit == 3
    assert sem3 is not sem1  # rebuilt when limit changed


@pytest.mark.unit
def test_run_thread_acquires_and_releases_semaphore_around_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thread body acquires the sem, runs the orchestrator step,
    and releases on the finally — even when step() raises."""

    class _Cfg:
        class budget:
            max_concurrent_runs = 1

    run_runner.reset_semaphore_for_tests()
    monkeypatch.setattr(run_runner, "get_settings", lambda: _Cfg())

    class _Counter:
        acquires = 0
        releases = 0

    class _CountingSem:
        def acquire(self_inner) -> None:
            _Counter.acquires += 1

        def release(self_inner) -> None:
            _Counter.releases += 1

    monkeypatch.setattr(run_runner, "_get_semaphore", lambda: _CountingSem())

    # Force the orchestrator construction path to raise so we exercise
    # the exception branch — sem must still release.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated factory failure")

    monkeypatch.setattr(run_runner, "build_orchestrator", _boom)
    run_runner._set(run_runner.RunState(run_id="rid-thread", status="pending"))

    run_runner._run_thread("rid-thread", "smoke", 1)

    assert _Counter.acquires == 1
    assert _Counter.releases == 1
    final = run_runner.get_run_state("rid-thread")
    assert final is not None
    assert final.status == "failed"
    assert "simulated factory failure" in (final.error or "")
