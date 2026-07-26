"""Bind reconciliation claims to reservation versions.

Revision ID: 0006_claim_version_binding
Revises: 0005_maintenance_comparison_sessions
Create Date: 2026-07-26
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_claim_version_binding"
down_revision: Union[str, Sequence[str], None] = (
    "0005_maintenance_comparison_sessions"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("quota_reconciliation_claims") as batch:
        batch.add_column(
            sa.Column(
                "reservation_version",
                sa.BigInteger(),
                nullable=True,
            )
        )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE quota_reconciliation_claims "
            "SET reservation_version = ("
            "SELECT quota_reservations.version "
            "FROM quota_reservations "
            "WHERE quota_reservations.id = "
            "quota_reconciliation_claims.reservation_id)"
        )
    )
    missing = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM quota_reconciliation_claims "
            "WHERE reservation_version IS NULL OR reservation_version <= 0"
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(
            "reconciliation claim version backfill is incomplete"
        )
    with op.batch_alter_table("quota_reconciliation_claims") as batch:
        batch.alter_column(
            "reservation_version",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch.create_check_constraint(
            "ck_quota_reconciliation_claim_version",
            "reservation_version > 0",
        )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "claim version downgrade requires an online claim check"
        )
    retained = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM quota_reconciliation_claims")
    ).scalar_one()
    if retained:
        raise RuntimeError(
            "cannot downgrade active reconciliation claim versions"
        )
    with op.batch_alter_table("quota_reconciliation_claims") as batch:
        batch.drop_constraint(
            "ck_quota_reconciliation_claim_version",
            type_="check",
        )
        batch.drop_column("reservation_version")
