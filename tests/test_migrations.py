from __future__ import annotations

from datetime import UTC, datetime
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, insert, text

from coffer.db import (
    RepositorySchemaNotReady,
    RepositoryStore,
    metadata as repository_metadata,
    repositories,
)
from coffer.quota import QuotaSchemaNotReady, QuotaStore
from coffer.schema import CURRENT_SCHEMA_REVISION


ROOT = Path(__file__).resolve().parents[1]


def migration_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_production_store_requires_the_versioned_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missing.sqlite'}"

    with pytest.raises(QuotaSchemaNotReady, match="migration is required"):
        QuotaStore(database_url)
    with pytest.raises(RepositorySchemaNotReady, match="migration is required"):
        RepositoryStore(database_url)


def test_explicit_test_bootstrap_does_not_claim_an_alembic_revision(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fixture.sqlite'}"
    fixture_store = QuotaStore(database_url, bootstrap_schema=True)
    fixture_store.set_limit("project-a", 1024)
    fixture_repositories = RepositoryStore(database_url, bootstrap_schema=True)
    fixture_repositories.create("project-a", "fixture")

    with pytest.raises(QuotaSchemaNotReady, match="no Alembic revision"):
        QuotaStore(database_url)
    with pytest.raises(RepositorySchemaNotReady, match="no Alembic revision"):
        RepositoryStore(database_url)


def test_alembic_adopts_exact_legacy_repository_rows(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.sqlite'}"
    engine = create_engine(database_url)
    repository_metadata.create_all(engine)
    created_at = datetime(2026, 7, 23, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(repositories).values(
                id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                project_id="11111111-1111-4111-8111-111111111111",
                name="legacy",
                immutable_tags=True,
                created_at=created_at,
            )
        )

    config = migration_config(database_url)
    command.upgrade(config, "head")
    command.check(config)

    store = RepositoryStore(database_url)
    adopted = store.get_by_name(
        "11111111-1111-4111-8111-111111111111", "legacy"
    )
    assert adopted is not None
    assert adopted.id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert adopted.immutable_tags
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == CURRENT_SCHEMA_REVISION


@pytest.mark.parametrize(
    "drift", ("columns", "primary_key", "uniqueness", "boolean_type")
)
def test_alembic_rejects_drifted_legacy_repository_schema(
    tmp_path: Path,
    drift: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'drift-{drift}.sqlite'}"
    engine = create_engine(database_url)
    extra_column = ", unexpected VARCHAR(8)" if drift == "columns" else ""
    primary_key = "project_id" if drift == "primary_key" else "id"
    immutable_type = "BIGINT" if drift == "boolean_type" else "BOOLEAN"
    uniqueness = (
        ""
        if drift == "uniqueness"
        else ", CONSTRAINT uq_repository_project_name UNIQUE (project_id, name)"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE repositories ("
            "id VARCHAR(36) NOT NULL, "
            "project_id VARCHAR(64) NOT NULL, "
            "name VARCHAR(255) NOT NULL, "
            f"immutable_tags {immutable_type} NOT NULL, "
            "created_at DATETIME NOT NULL"
            f"{extra_column}, PRIMARY KEY ({primary_key}){uniqueness})"
        )

    with pytest.raises(RuntimeError, match="does not match"):
        command.upgrade(migration_config(database_url), "head")

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "0002_reconciliation_claims"


def test_repository_adoption_requires_online_migration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_url = f"sqlite:///{tmp_path / 'offline.sqlite'}"

    with pytest.raises(RuntimeError, match="online migration"):
        command.upgrade(migration_config(database_url), "head", sql=True)

    capsys.readouterr()


def test_alembic_upgrade_is_repeatable_and_downgrade_is_bounded(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migrated.sqlite'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    store = QuotaStore(database_url)
    assert store.set_limit("project-a", 4096).limit_bytes == 4096
    repository_store = RepositoryStore(database_url)
    repository = repository_store.create("project-a", "durable")

    schema = inspect(create_engine(database_url))
    assert set(schema.get_table_names()) == {
        "alembic_version",
        "project_quotas",
        "quota_descriptors",
        "quota_manifests",
        "quota_reconciliation_claims",
        "quota_reservation_descriptors",
        "quota_reservations",
        "repositories",
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
        "alembic_version",
        "repositories",
    }
    with pytest.raises(RepositorySchemaNotReady, match="revision"):
        RepositoryStore(database_url)
    retained = RepositoryStore(database_url, bootstrap_schema=True).get(
        "project-a", repository.id
    )
    assert retained is not None
    assert retained.to_dict() == repository.to_dict()

    command.upgrade(config, "head")
    command.check(config)
    readopted = RepositoryStore(database_url).get("project-a", repository.id)
    assert readopted is not None
    assert readopted.to_dict() == repository.to_dict()


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
