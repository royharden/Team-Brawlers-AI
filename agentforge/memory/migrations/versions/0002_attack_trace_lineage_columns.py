"""attack_traces lineage columns — sub-plan Next05 §2 (DB-backed lineage tree).

Revision ID: 0002_attack_trace_lineage_columns
Revises: 0001_initial_schema
Create Date: 2026-05-15 08:00:00.000000

Adds two nullable columns to ``attack_traces``:

- ``attack_id``: the in-process MutatedAttack.attack_id UUID. Today the
  trace row's primary-key ``id`` is generated locally during persistence,
  with no link back to the agent-level attack_id. This column closes that
  gap so DB queries can match on agent-level ids.

- ``parent_attack_id``: nullable; non-NULL when this attack was an
  escalation (tree-of-attacks) refinement of an earlier attack. The
  AttackLineage page rebuilds parent/child relationships by walking this
  column.

Both columns are nullable so the migration is forward-only without a
destructive backfill — pre-Next05 rows simply have NULL lineage data and
won't be reachable via the lineage endpoints (the in-process registry
remains the fast path for the current process; the DB columns make
post-restart lookup possible going forward).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_attack_trace_lineage_columns"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attack_traces") as batch:
        batch.add_column(sa.Column("attack_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("parent_attack_id", sa.String(length=36), nullable=True))
        batch.create_index("ix_attack_traces_attack_id", ["attack_id"])
        batch.create_index("ix_attack_traces_parent_attack_id", ["parent_attack_id"])


def downgrade() -> None:
    with op.batch_alter_table("attack_traces") as batch:
        batch.drop_index("ix_attack_traces_parent_attack_id")
        batch.drop_index("ix_attack_traces_attack_id")
        batch.drop_column("parent_attack_id")
        batch.drop_column("attack_id")
