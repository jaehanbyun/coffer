from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


CURRENT_SCHEMA_REVISION = "0004_inventory_import"


class SchemaNotReady(Exception):
    pass


def require_current_schema(
    engine: Engine,
    *,
    expected_tables: Collection[str],
    component: str,
    error_type: type[SchemaNotReady],
) -> None:
    try:
        actual_tables = set(inspect(engine).get_table_names())
        missing = sorted(set(expected_tables) - actual_tables)
        if missing:
            raise error_type(
                f"{component} schema migration is required; missing tables: "
                + ", ".join(missing)
            )
        if "alembic_version" not in actual_tables:
            raise error_type(
                f"{component} schema has no Alembic revision; migration is required"
            )
        with engine.connect() as connection:
            revisions = tuple(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
    except SchemaNotReady:
        raise
    except SQLAlchemyError as exc:
        raise error_type(
            f"{component} schema revision could not be verified"
        ) from exc
    if revisions != (CURRENT_SCHEMA_REVISION,):
        raise error_type(
            f"{component} schema revision does not match the application"
        )
