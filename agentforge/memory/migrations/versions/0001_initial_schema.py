"""initial schema — master plan §5.2

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-13 00:00:00.000000

Creates every Phase-1 table:
runs, attack_jobs, attack_traces, verdicts, vulnerability_classes, vuln_reports,
regression_cases, cost_ledger, coverage_cells, defense_delta_snapshots,
agent_messages, flight_events.

CHECK constraint on `regression_cases.what_bug_this_catches` enforces the
testing-discipline contract at the schema level (non-empty string).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("run_type", sa.String(length=32), nullable=False, server_default="exploratory"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("model_resolution_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("total_cost_usd", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("halt_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "attack_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("seed_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "attack_traces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "attack_job_id",
            sa.String(length=36),
            sa.ForeignKey("attack_jobs.id"),
            nullable=False,
        ),
        sa.Column("mutator_chain_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("rendered_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("rendered_document", sa.Text(), nullable=True),
        sa.Column("target_request_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("target_response_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_error", sa.Text(), nullable=True),
    )

    op.create_table(
        "verdicts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "attack_trace_id",
            sa.String(length=36),
            sa.ForeignKey("attack_traces.id"),
            nullable=False,
        ),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("rubric_results_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("judge_run_id", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "layer IN ('internal_progress','external_final')",
            name="ck_verdicts_layer",
        ),
    )

    op.create_table(
        "vulnerability_classes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("dedupe_key_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("target_endpoint", sa.String(length=64), nullable=False),
        sa.Column("normalized_objective", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
    )

    op.create_table(
        "vuln_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vr_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column(
            "vulnerability_class_id",
            sa.String(length=64),
            sa.ForeignKey("vulnerability_classes.id"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("defcon", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("safety_score_0_100", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owasp_llm10_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("owasp_agentic_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("avid_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("nist_ai_rmf_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("fix_status", sa.String(length=32), nullable=False, server_default="unfixed"),
        sa.Column("target_fingerprint_at_discovery", sa.String(length=64), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=True),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_html", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "regression_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "vr_id",
            sa.String(length=32),
            sa.ForeignKey("vuln_reports.vr_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("what_bug_this_catches", sa.Text(), nullable=False),
        sa.Column("case_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_outcome", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "length(what_bug_this_catches) > 0",
            name="ck_regression_cases_what_bug_nonempty",
        ),
    )

    op.create_table(
        "cost_ledger",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("agent_role", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(14, 6), nullable=False, server_default="0"),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "coverage_cells",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_pass_rate", sa.Float(), nullable=False, server_default="0.0"),
    )

    op.create_table(
        "defense_delta_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(), nullable=True),
        sa.Column("aggregate_pass_rate", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("by_cell_json", sa.Text(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("from_agent", sa.String(length=64), nullable=False),
        sa.Column("to_agent", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("hmac_signature", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "flight_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("agent_role", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    # Drop in reverse FK order.
    op.drop_table("flight_events")
    op.drop_table("agent_messages")
    op.drop_table("defense_delta_snapshots")
    op.drop_table("coverage_cells")
    op.drop_table("cost_ledger")
    op.drop_table("regression_cases")
    op.drop_table("vuln_reports")
    op.drop_table("vulnerability_classes")
    op.drop_table("verdicts")
    op.drop_table("attack_traces")
    op.drop_table("attack_jobs")
    op.drop_table("runs")
