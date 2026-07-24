from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from oslo_config import cfg
from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError, OperationalError, SQLAlchemyError

from coffer.config import parse_config, setup_logging
from coffer.db import metadata as repository_metadata
from coffer.quota import quota_metadata
from coffer.schema import SchemaNotReady, require_current_schema


LOG = logging.getLogger(__name__)
EXIT_OK = 0
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78


class BootstrapSchemaError(SchemaNotReady):
    pass


def migration_path() -> Path:
    return Path(__file__).with_name("migrations")


def upgrade_schema(database_url: str) -> None:
    if not database_url or not database_url.strip():
        raise ValueError("database connection is required")
    script_location = migration_path()
    if not (script_location / "env.py").is_file():
        raise ValueError("installed migration environment is incomplete")

    engine = create_engine(database_url)
    try:
        alembic_config = Config()
        alembic_config.set_main_option("script_location", str(script_location))
        with engine.connect() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")
        require_current_schema(
            engine,
            expected_tables=(
                set(repository_metadata.tables) | set(quota_metadata.tables)
            ),
            component="bootstrap",
            error_type=BootstrapSchemaError,
        )
    finally:
        engine.dispose()


def run_with_config(conf: cfg.ConfigOpts) -> int:
    try:
        upgrade_schema(conf.database.connection)
    except (ArgumentError, CommandError, BootstrapSchemaError, RuntimeError, ValueError):
        LOG.error("bootstrap failed result=invalid_configuration")
        return EXIT_CONFIG
    except (OperationalError, SQLAlchemyError, OSError):
        LOG.error("bootstrap failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    except Exception:
        LOG.error("bootstrap failed result=dependency_unavailable")
        return EXIT_TEMPFAIL
    LOG.info("bootstrap completed schema=current")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    try:
        conf = parse_config(args=argv)
    except SystemExit as exc:
        if exc.code in (None, EXIT_OK):
            raise
        print(
            "bootstrap failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    except cfg.Error:
        print(
            "bootstrap failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    try:
        setup_logging(conf)
    except (cfg.Error, OSError, ValueError):
        print(
            "bootstrap failed result=invalid_configuration",
            file=sys.stderr,
        )
        return EXIT_CONFIG
    return run_with_config(conf)
