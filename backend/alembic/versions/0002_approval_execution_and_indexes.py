"""approval execution timestamp and lookup indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22 22:54:22

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

INDEXES = [
    ("agent_runs", "ix_agent_runs_work_item", ["work_item_id"]),
    ("artifact_versions", "ix_artifact_versions_artifact", ["artifact_id"]),
    ("notifications", "ix_notifications_task", ["task_id"]),
    ("related_plan_to_task", "ix_related_plan_to_task_plan", ["execution_plan_id"]),
    ("review_task_results", "ix_review_task_results_task", ["task_id"]),
    ("scheduled_actions", "ix_scheduled_actions_task", ["task_id"]),
    ("task_artifacts", "ix_task_artifacts_plan", ["execution_plan_id"]),
    ("task_versions", "ix_task_versions_task", ["task_id"]),
    ("work_item_dependencies", "ix_work_item_dependencies_prereq", ["depends_on_work_item_id"]),
    ("approval_requests", "ix_approval_requests_connection", ["connection_id"]),
]


def upgrade() -> None:
    with op.batch_alter_table("approval_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("executed_at", sa.String(), nullable=True))
    for table, name, columns in INDEXES:
        op.create_index(name, table, columns, unique=False, if_not_exists=True)


def downgrade() -> None:
    for table, name, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
    with op.batch_alter_table("approval_requests", schema=None) as batch_op:
        batch_op.drop_column("executed_at")
