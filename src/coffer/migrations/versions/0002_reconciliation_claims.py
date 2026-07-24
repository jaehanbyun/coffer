"""Add fenced reconciliation claims.

Revision ID: 0002_reconciliation_claims
Revises: 0001_quota_ledger
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_reconciliation_claims"
down_revision: Union[str, Sequence[str], None] = "0001_quota_ledger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quota_reconciliation_claims",
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > claimed_at",
            name="ck_quota_reconciliation_claim_window",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["quota_reservations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("reservation_id"),
        sa.UniqueConstraint(
            "claim_token", name="uq_quota_reconciliation_claim_token"
        ),
    )
    op.create_index(
        "ix_quota_reconciliation_claims_expires",
        "quota_reconciliation_claims",
        ["expires_at", "reservation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quota_reconciliation_claims_expires",
        table_name="quota_reconciliation_claims",
    )
    op.drop_table("quota_reconciliation_claims")
