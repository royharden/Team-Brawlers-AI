"""Typer CLI entry — master plan §20 Quickstart commands."""

from __future__ import annotations

import typer
from loguru import logger

app = typer.Typer(help="AgentForge CLI — multi-agent adversarial AI security platform.")


@app.command()
def smoke() -> None:
    """Smoke-test the target adapter end-to-end."""
    logger.info("`tb smoke` — not yet implemented (Phase 1)")
    raise typer.Exit(code=0)


@app.command()
def attack(category: str = typer.Option("", help="Attack category")) -> None:
    """Run a single category attack."""
    logger.info("`tb attack` ({}) — not yet implemented (Phase 2)", category)
    raise typer.Exit(code=0)


@app.command()
def regress(floor: str = typer.Option("evals/floor.json", help="Path to floor.json")) -> None:
    """Run the regression suite, enforcing the floor."""
    logger.info("`tb regress --floor {}` — not yet implemented (Phase 3)", floor)
    raise typer.Exit(code=0)


@app.command()
def report() -> None:
    """Render vulnerability reports."""
    logger.info("`tb report` — not yet implemented (Phase 3)")
    raise typer.Exit(code=0)


@app.command("meta-eval")
def meta_eval() -> None:
    """Run judge meta-eval against the gold set."""
    logger.info("`tb meta-eval` — not yet implemented (Phase 3)")
    raise typer.Exit(code=0)


@app.command()
def seed() -> None:
    """Seed synthetic test patients in the target."""
    logger.info("`tb seed` — not yet implemented (Phase 1)")
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
