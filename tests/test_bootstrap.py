from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from coffer.bootstrap import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_TEMPFAIL,
    migration_path,
    run_with_config,
)
from coffer.config import new_config
from coffer.schema import CURRENT_SCHEMA_REVISION


def config(database_url: str):
    conf = new_config()
    conf(args=[])
    conf.set_override("connection", database_url, group="database")
    return conf


def test_installed_migration_environment_is_package_local() -> None:
    path = migration_path()

    assert path.parent.name == "coffer"
    assert (path / "env.py").is_file()
    assert (path / "script.py.mako").is_file()
    assert sorted(item.name for item in (path / "versions").glob("000*.py")) == [
        "0001_quota_ledger.py",
        "0002_reconciliation_claims.py",
        "0003_repository_metadata.py",
        "0004_inventory_import.py",
    ]


def test_bootstrap_is_repeat_safe_and_validates_the_current_schema(
    tmp_path: Path,
    caplog,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'coffer.sqlite'}"
    caplog.set_level(logging.INFO)

    assert run_with_config(config(database_url)) == EXIT_OK
    assert run_with_config(config(database_url)) == EXIT_OK

    engine = create_engine(database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {
            "alembic_version",
            "project_quotas",
            "quota_descriptors",
            "quota_inventory_imports",
            "quota_manifests",
            "quota_reconciliation_claims",
            "quota_reservation_descriptors",
            "quota_reservations",
            "repositories",
        }
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == CURRENT_SCHEMA_REVISION
    finally:
        engine.dispose()
    assert caplog.text.count("bootstrap completed schema=current") == 2


def test_bootstrap_has_stable_secret_safe_failure_contracts(
    tmp_path: Path,
    caplog,
) -> None:
    caplog.set_level(logging.INFO)

    assert run_with_config(config("not-a-database-url")) == EXIT_CONFIG
    unavailable = (
        f"sqlite:///{tmp_path / 'missing-parent' / 'credential-secret.sqlite'}"
    )
    assert run_with_config(config(unavailable)) == EXIT_TEMPFAIL
    assert "credential-secret" not in caplog.text
    assert "not-a-database-url" not in caplog.text
    assert "invalid_configuration" in caplog.text
    assert "dependency_unavailable" in caplog.text
