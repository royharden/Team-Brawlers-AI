"""SQLAlchemy declarative models — master plan §5.2. Minimum viable columns."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all AgentForge tables."""


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    run_type: Mapped[str] = mapped_column(String(32), default="exploratory")
    target_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    model_resolution_json: Mapped[str] = mapped_column(Text, default="{}")


class AttackJob(Base):
    __tablename__ = "attack_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    category: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued")


class AttackTrace(Base):
    __tablename__ = "attack_traces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attack_job_id: Mapped[str] = mapped_column(String(36), ForeignKey("attack_jobs.id"))
    rendered_prompt: Mapped[str] = mapped_column(Text, default="")
    response_text: Mapped[str] = mapped_column(Text, default="")
    parent_attack_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Verdict(Base):
    __tablename__ = "verdicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attack_trace_id: Mapped[str] = mapped_column(String(36), ForeignKey("attack_traces.id"))
    layer: Mapped[str] = mapped_column(String(32))
    rubric_id: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class VulnerabilityClass(Base):
    __tablename__ = "vulnerability_classes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True)


class VulnReport(Base):
    __tablename__ = "vuln_reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    vulnerability_class_id: Mapped[str] = mapped_column(String(64), ForeignKey("vulnerability_classes.id"))
    severity: Mapped[str] = mapped_column(String(16))
    defcon: Mapped[int] = mapped_column(Integer, default=3)
    safety_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="open")


class RegressionCase(Base):
    __tablename__ = "regression_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vr_id: Mapped[str] = mapped_column(String(32), ForeignKey("vuln_reports.id"))
    what_bug_this_catches: Mapped[str] = mapped_column(Text)


class CostLedgerEntry(Base):
    __tablename__ = "cost_ledger"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))


class CoverageCellRow(Base):
    __tablename__ = "coverage_cells"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    category: Mapped[str] = mapped_column(String(64))
    strategy: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)


class DefenseDeltaSnapshot(Base):
    __tablename__ = "defense_delta_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_fingerprint: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=0.0)


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    from_agent: Mapped[str] = mapped_column(String(64))
    to_agent: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(16))
    payload_json: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(128))


class FlightEvent(Base):
    __tablename__ = "flight_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
