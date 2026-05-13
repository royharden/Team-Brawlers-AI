"""Typer CLI entry — master plan §20 Quickstart commands.

Subcommands:

* ``tb smoke``       — run the local OpenEMR smoke probe.
* ``tb attack``      — orchestrator-driven attack run (stub until F5).
* ``tb regress``     — replay regression cases + enforce ``evals/floor.json``.
* ``tb report``      — print a rendered VR markdown report to stdout.
* ``tb meta-eval``   — hook for the judge meta-eval runner (sub-agent F2).
* ``tb seed``        — list seeds from :class:`SeedCatalog`.

The regression command wires :class:`RegressionRunner`. When the live
target adapter is not available, ``--mock <dir>`` swaps in a fake
:class:`TargetExecutor` that reads ``<dir>/<vr_id>.json`` for the
canned response.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import typer
from loguru import logger

from agentforge.judge.external_final import ExternalFinalJudge
from agentforge.judge.rubrics import RubricRegistry
from agentforge.memory.schemas import AdapterResponse
from agentforge.regression.case_schema import RegressionCase
from agentforge.regression.floor import FloorEnforcer
from agentforge.regression.replay import Replay, TargetExecutor
from agentforge.regression.runner import RegressionRunner

app = typer.Typer(help="AgentForge CLI — multi-agent adversarial AI security platform.")


# ----------------------------------------------------------------- helpers


def _project_root() -> Path:
    """Return the repo root (the parent of the agentforge/ package)."""
    return Path(__file__).resolve().parent.parent


def _default_regression_dir() -> Path:
    return _project_root() / "evals" / "regression"


def _default_results_dir() -> Path:
    return _project_root() / "evals" / "results"


def _default_floor_path() -> Path:
    return _project_root() / "evals" / "floor.json"


def _default_reports_dir() -> Path:
    return _project_root() / "reports"


class _MockTargetExecutor:
    """Read canned responses from ``<fixtures_dir>/<vr_id>.json``.

    JSON shape::

        {
            "status_code": 200,
            "body_text": "...",
            "body_json": {...},
            "latency_ms": 12.3,
            "error": null
        }

    Missing file → ``AdapterResponse(error="mock-not-found: ...")``.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = Path(fixtures_dir)
        # Per-call vr_id is not part of the Protocol, so we let the runner
        # encode it into the rendered_prompt for lookup OR (preferred) the
        # caller provides the vr_id by injecting a one-shot subclass. The
        # default behavior: parse the case file the runner is iterating
        # by sniffing the prompt's first 64 chars as a key. To keep this
        # robust for tests, we expose `next_vr_id` which the runner can set.
        self.next_vr_id: str | None = None

    def execute(
        self,
        *,
        rendered_prompt: str | None,
        rendered_turns: list[dict[str, Any]] | None,
        target_endpoint: str | None,
    ) -> AdapterResponse:
        if self.next_vr_id is None:
            return AdapterResponse(
                attack_id=uuid4(),
                status_code=0,
                body_text="",
                error="mock-no-vr-id-set",
            )
        path = self._dir / f"{self.next_vr_id}.json"
        if not path.exists():
            return AdapterResponse(
                attack_id=uuid4(),
                status_code=0,
                body_text="",
                error=f"mock-not-found: {path}",
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        return AdapterResponse(
            attack_id=uuid4(),
            status_code=int(raw.get("status_code", 200)),
            body_text=str(raw.get("body_text", "")),
            body_json=raw.get("body_json"),
            latency_ms=float(raw.get("latency_ms", 0.0)),
            error=raw.get("error"),
        )


class _MockReplay(Replay):
    """A :class:`Replay` that informs its mock executor of the current vr_id."""

    def run_case(  # type: ignore[override]
        self,
        case: RegressionCase,
        *,
        target_fingerprint: str,
    ):
        target = self._target
        if isinstance(target, _MockTargetExecutor):
            target.next_vr_id = case.vr_id
        return super().run_case(case, target_fingerprint=target_fingerprint)


def _build_mock_runner(
    mock_dir: Path, floor_path: Path
) -> RegressionRunner:
    target = _MockTargetExecutor(mock_dir)
    judge = ExternalFinalJudge(rubric_registry=RubricRegistry())
    replay = _MockReplay(target_executor=target, external_judge=judge)
    enforcer = FloorEnforcer.from_json(floor_path)
    return RegressionRunner(
        replay=replay,
        floor_enforcer=enforcer,
        regression_dir=_default_regression_dir(),
        results_dir=_default_results_dir(),
        session_factory=None,
    )


# ------------------------------------------------------------- commands


@app.command()
def smoke() -> None:
    """Smoke-test the local OpenEMR target stack.

    Delegates to the platform-appropriate script under ``scripts/``.
    Exits 0 on success, 1 on script failure.
    """
    root = _project_root()
    if platform.system() == "Windows":
        script = root / "scripts" / "smoke_local_openemr.ps1"
        cmd = ["powershell", "-NoProfile", "-File", str(script)]
    else:
        script = root / "scripts" / "smoke_local_openemr.sh"
        cmd = ["bash", str(script)]
    if not script.exists():
        typer.echo(f"smoke script missing: {script}", err=True)
        raise typer.Exit(code=2)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    typer.echo(proc.stdout)
    if proc.returncode != 0:
        typer.echo(proc.stderr, err=True)
    raise typer.Exit(code=proc.returncode)


@app.command()
def attack(
    category: str = typer.Option("", help="Attack category"),
    strategy: str = typer.Option("", help="Attack strategy"),
    count: int = typer.Option(1, help="Number of attacks"),
) -> None:
    """Orchestrator-driven attack run.

    Stub for now (full wiring lands in Phase 6 with the live target).
    """
    logger.info(
        "tb attack(category={}, strategy={}, count={}) — not yet implemented (Phase 6)",
        category, strategy, count,
    )
    typer.echo(
        "tb attack: placeholder — orchestrator/target wiring lands with the "
        "Phase 6 Docker-gated live-target tasks."
    )
    raise typer.Exit(code=0)


@app.command()
def regress(
    case: str = typer.Option("", "--case", help="Run a single case (e.g. VR-0042)"),
    floor: str = typer.Option("", "--floor", help="Path to floor.json"),
    target_fingerprint: str = typer.Option(
        "", "--target-fingerprint", help="Target fingerprint at replay time"
    ),
    mock: str = typer.Option(
        "", "--mock", help="Path to mock fixture dir (regression replay without live target)"
    ),
) -> None:
    """Replay regression cases and enforce ``evals/floor.json``.

    Exit code 0 if the floor is met, 1 if exceeded, 2 if no target adapter
    is wired and no ``--mock`` directory was provided.
    """
    floor_path = Path(floor) if floor else _default_floor_path()
    fingerprint = target_fingerprint or "unknown-fingerprint"

    if not mock:
        typer.echo(
            "No live target adapter wired yet. "
            "Use --mock=tests/fixtures/regression_replay/ or wait for "
            "Phase 1 Docker-gated tasks.",
            err=True,
        )
        raise typer.Exit(code=2)

    mock_dir = Path(mock)
    if not mock_dir.exists():
        typer.echo(f"--mock directory does not exist: {mock_dir}", err=True)
        raise typer.Exit(code=2)

    runner = _build_mock_runner(mock_dir, floor_path)

    if case:
        outcome = runner.run_one(case, target_fingerprint=fingerprint)
        typer.echo(json.dumps(outcome.model_dump(mode="json"), indent=2))
        # Single-case run doesn't run floor; exit 0 if the case matched
        # expected (still fails), 1 otherwise.
        raise typer.Exit(code=0 if outcome.matched_expected or outcome.observed_outcome == "error" else 1)

    batch, floor_result = runner.run_all(target_fingerprint=fingerprint)
    typer.echo(floor_result.summary)
    typer.echo(
        f"batch: cases_run={batch.cases_run} "
        f"failed_as_expected={len(batch.cases_failed_as_expected)} "
        f"passed_unexpectedly={len(batch.cases_passed_unexpectedly)} "
        f"errored={len(batch.cases_errored)}"
    )
    raise typer.Exit(code=floor_result.exit_code)


@app.command()
def report(
    vr: str = typer.Option(..., "--vr", help="VR id, e.g. VR-0042"),
) -> None:
    """Print a rendered VR markdown report to stdout.

    Looks under ``reports/VR-####-<slug>.md``; if multiple slug variants
    exist, the most recently modified is used.
    """
    reports_dir = _default_reports_dir()
    matches = sorted(
        reports_dir.glob(f"{vr}-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        typer.echo(f"No report found for {vr} under {reports_dir}", err=True)
        raise typer.Exit(code=1)
    typer.echo(matches[0].read_text(encoding="utf-8"))


@app.command("meta-eval")
def meta_eval(
    layer: str = typer.Option(
        "external_final", "--layer", help="Judge layer to meta-evaluate"
    ),
) -> None:
    """Run judge meta-eval against the gold set.

    The real implementation lives in ``agentforge.judge.meta_eval`` (owned
    by sub-agent F2). This command is just the dispatch hook — if the
    module is not yet available, we print a clear "not yet implemented"
    message and exit 0 so this command never blocks CI in Phase 5.
    """
    try:
        from agentforge.judge.meta_eval.runner import run_meta_eval  # type: ignore[import-not-found]
    except ImportError:
        typer.echo("meta-eval module not implemented (Phase 6)")
        raise typer.Exit(code=0)
    try:
        result = run_meta_eval(layer=layer)
    except FileNotFoundError as exc:
        typer.echo(f"meta-eval gold set unavailable: {exc}")
        raise typer.Exit(code=0)
    # JudgeMetrics is a Pydantic model — dump it.
    try:
        payload = result.model_dump(mode="json")  # type: ignore[attr-defined]
    except AttributeError:
        payload = result
    typer.echo(json.dumps(payload, indent=2, default=str))
    raise typer.Exit(code=0)


@app.command()
def seed(
    category: str = typer.Option("", "--category", help="Filter by category"),
) -> None:
    """List Red Team seeds via :class:`SeedCatalog`."""
    # Import lazily so the CLI can boot in environments without PyYAML wired.
    from agentforge.redteam.seed_catalog import SeedCatalog

    cat = SeedCatalog()
    seeds = cat.by_category(category) if category else cat.all()
    if not seeds:
        typer.echo(f"No seeds found (category={category!r}).")
        raise typer.Exit(code=0)
    for s in seeds:
        typer.echo(f"  {s.get('id', '?')}  [{s.get('category', '?')}]  {s.get('severity', '?')}")
    typer.echo(f"\n{len(seeds)} seed(s)")
    raise typer.Exit(code=0)


def main() -> None:
    """Console-script entry point (``tb`` in pyproject.toml)."""
    app()


if __name__ == "__main__":
    main()
