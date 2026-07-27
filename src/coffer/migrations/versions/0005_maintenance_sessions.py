"""Add bounded live-comparison maintenance sessions.

Revision ID: 0005_maintenance_sessions
Revises: 0004_inventory_import
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_maintenance_sessions"
down_revision: Union[str, Sequence[str], None] = "0004_inventory_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "maintenance_comparison_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("inventory_digest", sa.String(length=71), nullable=False),
        sa.Column("workload_id", sa.String(length=128), nullable=False),
        sa.Column("writer_exclusion_ref", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(state = 'approved' AND closed_at IS NULL) OR "
            "(state IN ('completed', 'revoked') AND closed_at IS NOT NULL)",
            name="ck_maintenance_comparison_session_lifecycle",
        ),
        sa.CheckConstraint(
            "state IN ('approved', 'completed', 'revoked')",
            name="ck_maintenance_comparison_session_state",
        ),
        sa.CheckConstraint(
            "expires_at > approved_at",
            name="ck_maintenance_comparison_session_window",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_digest"],
            ["quota_inventory_imports.inventory_digest"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            name="uq_maintenance_comparison_session_request",
        ),
    )
    op.create_index(
        "ix_maintenance_comparison_sessions_state_expires",
        "maintenance_comparison_sessions",
        ["state", "expires_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "maintenance comparison session downgrade requires an online "
            "session check"
        )
    connection = op.get_bind()
    retained = connection.execute(
        sa.text("SELECT COUNT(*) FROM maintenance_comparison_sessions")
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "cannot downgrade retained maintenance comparison sessions"
        )
    op.drop_index(
        "ix_maintenance_comparison_sessions_state_expires",
        table_name="maintenance_comparison_sessions",
    )
    op.drop_table("maintenance_comparison_sessions")
