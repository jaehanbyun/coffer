from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect

from coffer.quota import QuotaSchemaNotReady, QuotaStore


ROOT = Path(__file__).resolve().parents[1]


def migration_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_production_store_requires_the_versioned_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing.sqlite'}"

    with pytest.raises(QuotaSchemaNotReady, match="migration is required"):
        QuotaStore(database_url)


def test_explicit_test_bootstrap_does_not_claim_an_alembic_revision(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fixture.sqlite'}"
    fixture_store = QuotaStore(database_url, bootstrap_schema=True)
    fixture_store.set_limit("project-a", 1024)

    with pytest.raises(QuotaSchemaNotReady, match="no Alembic revision"):
        QuotaStore(database_url)


def test_alembic_upgrade_is_repeatable_and_downgrade_is_bounded(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migrated.sqlite'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    store = QuotaStore(database_url)
    assert store.set_limit("project-a", 4096).limit_bytes == 4096

    schema = inspect(create_engine(database_url))
    assert set(schema.get_table_names()) == {
        "alembic_version",
        "project_quotas",
        "quota_descriptors",
        "quota_manifests",
        "quota_reconciliation_claims",
        "quota_reservation_descriptors",
        "quota_reservations",
    }
    assert {
        index["name"] for index in schema.get_indexes("quota_reservations")
    } == {
        "ix_quota_reservations_project_state",
        "ix_quota_reservations_reconcile",
    }
    assert {
        index["name"]
        for index in schema.get_indexes("quota_reconciliation_claims")
    } == {"ix_quota_reconciliation_claims_expires"}
    assert {
        constraint["name"]
        for constraint in schema.get_unique_constraints(
            "quota_reconciliation_claims"
        )
    } == {"uq_quota_reconciliation_claim_token"}
    assert {
        constraint["name"]
        for constraint in schema.get_check_constraints(
            "quota_reconciliation_claims"
        )
    } == {"ck_quota_reconciliation_claim_window"}
    claim_foreign_keys = schema.get_foreign_keys("quota_reconciliation_claims")
    assert len(claim_foreign_keys) == 1
    assert claim_foreign_keys[0]["referred_table"] == "quota_reservations"
    assert claim_foreign_keys[0]["options"] == {"ondelete": "CASCADE"}

    command.downgrade(config, "base")
    assert set(inspect(create_engine(database_url)).get_table_names()) == {
        "alembic_version"
    }


def test_alembic_logging_preserves_existing_application_loggers(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'logging.sqlite'}"
    logger = logging.getLogger("coffer.migration_logging_regression")
    original_disabled = logger.disabled
    logger.disabled = False
    try:
        command.upgrade(migration_config(database_url), "head")

        assert not logger.disabled
    finally:
        logger.disabled = original_disabled
