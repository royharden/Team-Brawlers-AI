"""SQLAlchemy declarative models — master plan §5.2.

Minimum viable column set for every Phase-1 table. SQLAlchemy 2.0 typed
`Mapped[...]` syntax throughout. Numeric/decimal columns use `Numeric` with
explicit precision; JSON-shaped payloads are stored as `Text` (JSON-encoded by
the repo layer) for SQLite portability. CHECK constraints enforced inline
where the testing-discipline contract requires it (e.g. `regression_cases.
what_bug_this_catches`).

WORM rule on `flight_events`: append-only. Enforced at the repo layer (no
UPDATE/DELETE in `FlightEventRepo`); the schema does not try to express it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Timezone-aware UTC default used by every `created_at` column."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all AgentForge tables."""


# --- Runs ---------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_type: Mapped[str] = mapped_column(String(32), default="exploratory")
    status: Mapped[str] = mapped_column(String(32), default="running")
    model_resolution_json: Mapped[str] = mapped_column(Text, default="{}")
    total_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), default=Decimal("0")
    )
    halt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# --- Attack jobs / traces -----------------------------------------------------


class AttackJob(Base):
    __tablename__ = "attack_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    category: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(64))
    seed_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class AttackTrace(Base):
    __tablename__ = "attack_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attack_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attack_jobs.id")
    )
    mutator_chain_json: Mapped[str] = mapped_column(Text, default="[]")
    rendered_prompt: Mapped[str] = mapped_column(Text, default="")
    rendered_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_request_json: Mapped[str] = mapped_column(Text, default="{}")
    target_response_json: Mapped[str] = mapped_column(Text, default="{}")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    target_error: Mapped[str | None] = mapped_column(Text, nullable=True)


# --- Verdicts -----------------------------------------------------------------


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attack_trace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attack_traces.id")
    )
    # Stored as TEXT enum (sqlite-portable). Allowed: internal_progress|external_final.
    layer: Mapped[str] = mapped_column(String(32))
    rubric_results_json: Mapped[str] = mapped_column(Text, default="[]")
    outcome: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(128), default="")
    judge_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "layer IN ('internal_progress','external_final')",
            name="ck_verdicts_layer",
        ),
    )


# --- Vulnerability classes / reports -----------------------------------------


class VulnerabilityClass(Base):
    __tablename__ = "vulnerability_classes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dedupe_key_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    category: Mapped[str] = mapped_column(String(64))
    target_endpoint: Mapped[str] = mapped_column(String(64))
    normalized_objective: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    status: Mapped[str] = mapped_column(String(32), default="open")


class VulnReport(Base):
    __tablename__ = "vuln_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vr_id: Mapped[str] = mapped_column(String(32), unique=True)
    vulnerability_class_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("vulnerability_classes.id")
    )
    severity: Mapped[str] = mapped_column(String(16))
    defcon: Mapped[int] = mapped_column(Integer, default=3)
    safety_score_0_100: Mapped[int] = mapped_column(Integer, default=0)
    owasp_llm10_json: Mapped[str] = mapped_column(Text, default="[]")
    owasp_agentic_json: Mapped[str] = mapped_column(Text, default="[]")
    avid_json: Mapped[str] = mapped_column(Text, default="[]")
    nist_ai_rmf_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), default="open")
    fix_status: Mapped[str] = mapped_column(String(32), default="unfixed")
    target_fingerprint_at_discovery: Mapped[str] = mapped_column(String(64))
    written_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    content_markdown: Mapped[str] = mapped_column(Text, default="")
    content_html: Mapped[str] = mapped_column(Text, default="")


# --- Regression cases ---------------------------------------------------------


class RegressionCase(Base):
    __tablename__ = "regression_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vr_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("vuln_reports.vr_id"), unique=True
    )
    # Testing-discipline contract: every regression case must say what it
    # catches, in plain English, with non-empty length.
    what_bug_this_catches: Mapped[str] = mapped_column(Text, nullable=False)
    case_json: Mapped[str] = mapped_column(Text, default="{}")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(what_bug_this_catches) > 0",
            name="ck_regression_cases_what_bug_nonempty",
        ),
    )


# --- Cost ledger --------------------------------------------------------------


class CostLedgerEntry(Base):
    __tablename__ = "cost_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    agent_role: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --- Coverage matrix ----------------------------------------------------------


class CoverageCellRow(Base):
    __tablename__ = "coverage_cells"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    passes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_pass_rate: Mapped[float] = mapped_column(Float, default=0.0)


# --- Defense delta ------------------------------------------------------------


class DefenseDeltaSnapshot(Base):
    __tablename__ = "defense_delta_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    aggregate_pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    by_cell_json: Mapped[str] = mapped_column(Text, default="{}")


# --- Inter-agent envelope -----------------------------------------------------


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    from_agent: Mapped[str] = mapped_column(String(64))
    to_agent: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[str] = mapped_column(Text)
    hmac_signature: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


# --- WORM flight events -------------------------------------------------------


class FlightEvent(Base):
    """Append-only event log. The repo layer rejects UPDATE/DELETE."""

    __tablename__ = "flight_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    agent_role: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


__all__ = [
    "Base",
    "Run",
    "AttackJob",
    "AttackTrace",
    "Verdict",
    "VulnerabilityClass",
    "VulnReport",
    "RegressionCase",
    "CostLedgerEntry",
    "CoverageCellRow",
    "DefenseDeltaSnapshot",
    "AgentMessage",
    "FlightEvent",
]
