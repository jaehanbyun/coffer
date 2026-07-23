"""Create or adopt repository control metadata.

Revision ID: 0003_repository_metadata
Revises: 0002_reconciliation_claims
Create Date: 2026-07-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "0003_repository_metadata"
down_revision: Union[str, Sequence[str], None] = "0002_reconciliation_claims"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EXPECTED_COLUMNS = {
    "id": (sa.String, 36, False),
    "project_id": (sa.String, 64, False),
    "name": (sa.String, 255, False),
    "immutable_tags": (sa.Boolean, None, False),
    "created_at": (sa.DateTime, None, False),
}


def _legacy_table_is_compatible(inspector: Inspector) -> bool:
    columns = {
        column["name"]: column
        for column in inspector.get_columns("repositories")
    }
    if set(columns) != set(_EXPECTED_COLUMNS):
        return False
    for name, (type_class, length, nullable) in _EXPECTED_COLUMNS.items():
        column = columns[name]
        mysql_boolean = (
            name == "immutable_tags"
            and inspector.bind.dialect.name in {"mysql", "mariadb"}
            and type(column["type"]).__name__ == "TINYINT"
            and getattr(column["type"], "display_width", None) == 1
        )
        if not isinstance(column["type"], type_class) and not mysql_boolean:
            return False
        if length is not None and getattr(column["type"], "length", None) != length:
            return False
        if column["nullable"] is not nullable:
            return False

    primary_key = inspector.get_pk_constraint("repositories")
    if tuple(primary_key.get("constrained_columns") or ()) != ("id",):
        return False
    unique_constraints = {
        (constraint.get("name"), tuple(constraint.get("column_names") or ()))
        for constraint in inspector.get_unique_constraints("repositories")
    }
    return unique_constraints == {
        ("uq_repository_project_name", ("project_id", "name"))
    }


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "repository metadata adoption requires an online migration"
        )
    inspector = sa.inspect(op.get_bind())
    if "repositories" in inspector.get_table_names():
        if not _legacy_table_is_compatible(inspector):
            raise RuntimeError(
                "existing repositories table does not match the control schema"
            )
        return

    op.create_table(
        "repositories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("immutable_tags", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_repository_project_name"
        ),
    )


def downgrade() -> None:
    # The upgrade may have adopted a pre-existing table. Retaining repository
    # identity is safer than an irreversible guess about its provenance.
    pass
