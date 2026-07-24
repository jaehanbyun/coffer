"""Add the immutable baseline inventory-import marker.

Revision ID: 0004_inventory_import
Revises: 0003_repository_metadata
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_inventory_import"
down_revision: Union[str, Sequence[str], None] = "0003_repository_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quota_inventory_imports",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("inventory_digest", sa.String(length=71), nullable=False),
        sa.Column("project_count", sa.BigInteger(), nullable=False),
        sa.Column("repository_count", sa.BigInteger(), nullable=False),
        sa.Column("manifest_count", sa.BigInteger(), nullable=False),
        sa.Column("descriptor_count", sa.BigInteger(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "descriptor_count >= 0", name="ck_quota_inventory_import_descriptors"
        ),
        sa.CheckConstraint(
            "manifest_count >= 0", name="ck_quota_inventory_import_manifests"
        ),
        sa.CheckConstraint(
            "project_count >= 0", name="ck_quota_inventory_import_projects"
        ),
        sa.CheckConstraint(
            "repository_count >= 0",
            name="ck_quota_inventory_import_repositories",
        ),
        sa.CheckConstraint(
            "scope = 'baseline'", name="ck_quota_inventory_import_scope"
        ),
        sa.PrimaryKeyConstraint("scope"),
        sa.UniqueConstraint(
            "inventory_digest", name="uq_quota_inventory_import_digest"
        ),
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "inventory import downgrade requires an online marker check"
        )
    connection = op.get_bind()
    committed = connection.execute(
        sa.text("SELECT COUNT(*) FROM quota_inventory_imports")
    ).scalar_one()
    if committed:
        raise RuntimeError(
            "cannot downgrade a committed baseline inventory import"
        )
    op.drop_table("quota_inventory_imports")
