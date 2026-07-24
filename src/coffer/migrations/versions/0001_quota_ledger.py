"""Create the versioned quota ledger.

Revision ID: 0001_quota_ledger
Revises:
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_quota_ledger"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_quotas",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("limit_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("limit_bytes >= 0", name="ck_project_quota_limit"),
        sa.CheckConstraint("reserved_bytes >= 0", name="ck_project_quota_reserved"),
        sa.CheckConstraint("used_bytes >= 0", name="ck_project_quota_used"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "quota_descriptors",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("reference_count", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("reference_count > 0", name="ck_quota_descriptor_refs"),
        sa.CheckConstraint("size >= 0", name="ck_quota_descriptor_size"),
        sa.PrimaryKeyConstraint("project_id", "digest"),
    )
    op.create_table(
        "quota_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_digest", sa.String(length=71), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("delta_bytes >= 0", name="ck_quota_reservation_delta"),
        sa.CheckConstraint(
            "state IN ('pending', 'release_pending', 'committed', 'released')",
            name="ck_quota_reservation_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_quota_reservation_version"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project_quotas.project_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "repository_id",
            "manifest_digest",
            name="uq_quota_reservation_manifest",
        ),
        sa.UniqueConstraint(
            "project_id",
            "repository_id",
            "manifest_digest",
            "request_id",
            name="uq_quota_reservation_request",
        ),
    )
    op.create_index(
        "ix_quota_reservations_project_state",
        "quota_reservations",
        ["project_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_quota_reservations_reconcile",
        "quota_reservations",
        ["state", "updated_at", "id"],
        unique=False,
    )
    op.create_table(
        "quota_reservation_descriptors",
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "size >= 0", name="ck_quota_reservation_descriptor_size"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["quota_reservations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("reservation_id", "digest"),
    )
    op.create_table(
        "quota_manifests",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('committed', 'released')", name="ck_quota_manifest_state"
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["quota_reservations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("project_id", "repository_id", "digest"),
    )
    op.create_index(
        "ix_quota_manifests_project_digest_state",
        "quota_manifests",
        ["project_id", "digest", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quota_manifests_project_digest_state", table_name="quota_manifests"
    )
    op.drop_table("quota_manifests")
    op.drop_table("quota_reservation_descriptors")
    op.drop_index(
        "ix_quota_reservations_reconcile", table_name="quota_reservations"
    )
    op.drop_index(
        "ix_quota_reservations_project_state", table_name="quota_reservations"
    )
    op.drop_table("quota_reservations")
    op.drop_table("quota_descriptors")
    op.drop_table("project_quotas")
