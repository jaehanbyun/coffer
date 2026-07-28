"""Add the user-facing registry artifact projection.

Revision ID: 0007_artifact_projection
Revises: 0006_claim_version_binding
Create Date: 2026-07-28
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_artifact_projection"
down_revision: Union[str, Sequence[str], None] = (
    "0006_claim_version_binding"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registry_artifacts",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("artifact_type", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('artifact', 'image', 'image_index')",
            name="ck_registry_artifact_kind",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_registry_artifact_size",
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "repository_id",
            "digest",
            name="pk_registry_artifacts",
        ),
    )
    op.create_index(
        "ix_registry_artifacts_repository_time",
        "registry_artifacts",
        ["project_id", "repository_id", "pushed_at", "digest"],
        unique=False,
    )
    op.create_table(
        "registry_tags",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "project_id",
            "repository_id",
            "name",
            name="pk_registry_tags",
        ),
    )
    op.create_index(
        "ix_registry_tags_repository_digest",
        "registry_tags",
        ["project_id", "repository_id", "digest", "name"],
        unique=False,
    )
    op.create_table(
        "registry_tag_claims",
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("repository_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > claimed_at",
            name="ck_registry_tag_claim_window",
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            "repository_id",
            "name",
            name="pk_registry_tag_claims",
        ),
    )
    op.create_index(
        "ix_registry_tag_claims_expires",
        "registry_tag_claims",
        ["expires_at", "project_id", "repository_id"],
        unique=False,
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "artifact projection downgrade requires an online emptiness check"
        )
    connection = op.get_bind()
    retained = sum(
        connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one()
        for table in (
            "registry_artifacts",
            "registry_tags",
            "registry_tag_claims",
        )
    )
    if retained:
        raise RuntimeError(
            "cannot downgrade a non-empty registry artifact projection"
        )
    op.drop_index(
        "ix_registry_tag_claims_expires",
        table_name="registry_tag_claims",
    )
    op.drop_table("registry_tag_claims")
    op.drop_index(
        "ix_registry_tags_repository_digest",
        table_name="registry_tags",
    )
    op.drop_table("registry_tags")
    op.drop_index(
        "ix_registry_artifacts_repository_time",
        table_name="registry_artifacts",
    )
    op.drop_table("registry_artifacts")
