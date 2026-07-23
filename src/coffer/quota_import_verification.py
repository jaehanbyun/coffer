from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from coffer.db import repositories as repository_table
from coffer.quota import (
    QuotaSchemaNotReady,
    QuotaStore,
    project_quotas,
    quota_descriptors,
    quota_inventory_imports,
    quota_manifests,
    quota_reconciliation_claims,
    quota_reservation_descriptors,
    quota_reservations,
)
from coffer.quota_import import (
    INVENTORY_IMPORT_SCOPE,
    InvalidInventoryArtifact,
    InventoryArtifact,
    build_inventory_ledger_facts,
    load_inventory_artifact,
)
from coffer.tokens import REPOSITORY_NAME


class InventoryVerificationFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class InventoryVerificationResult:
    status: str
    inventory_digest: str
    project_count: int
    repository_count: int
    manifest_count: int
    descriptor_count: int
    reservation_descriptor_count: int
    over_limit_project_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "descriptor_count": self.descriptor_count,
            "inventory_digest": self.inventory_digest,
            "manifest_count": self.manifest_count,
            "over_limit_project_count": self.over_limit_project_count,
            "project_count": self.project_count,
            "repository_count": self.repository_count,
            "reservation_descriptor_count": self.reservation_descriptor_count,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class InventoryRepositoryRoute:
    repository_id: str
    canonical_name: str
    manifest_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InventoryVerificationSnapshot:
    result: InventoryVerificationResult
    repositories: tuple[InventoryRepositoryRoute, ...]


def _mismatch() -> InventoryVerificationFailed:
    return InventoryVerificationFailed(
        "imported quota ledger does not match the verified inventory"
    )


@contextmanager
def _read_only_snapshot(store: QuotaStore) -> Iterator[Connection]:
    connection = store._engine.connect()
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection = connection.execution_options(isolation_level="SERIALIZABLE")
    elif dialect == "postgresql":
        connection = connection.execution_options(
            isolation_level="REPEATABLE READ",
            postgresql_readonly=True,
        )
    else:
        connection = connection.execution_options(isolation_level="REPEATABLE READ")
    transaction = connection.begin()
    sqlite_read_only = False
    try:
        if dialect == "sqlite":
            connection.exec_driver_sql("PRAGMA query_only = ON")
            sqlite_read_only = True
            # Python's sqlite3 driver defers BEGIN for read-only statements.
            # Force the database snapshot before the first comparison SELECT.
            connection.exec_driver_sql("BEGIN")
        elif dialect in {"mysql", "mariadb"}:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        if sqlite_read_only:
            connection.exec_driver_sql("PRAGMA query_only = OFF")
        connection.close()


def verify_inventory_import_snapshot(
    store: QuotaStore,
    artifact: InventoryArtifact,
) -> InventoryVerificationSnapshot:
    facts = build_inventory_ledger_facts(artifact)
    with _read_only_snapshot(store) as connection:
        marker_rows = connection.execute(select(quota_inventory_imports)).all()
        if len(marker_rows) != 1:
            raise _mismatch()
        marker = marker_rows[0]._mapping  # type: ignore[attr-defined]
        expected_marker = {
            "scope": INVENTORY_IMPORT_SCOPE,
            "inventory_digest": artifact.digest,
            "project_count": artifact.summary.project_count,
            "repository_count": artifact.summary.repository_count,
            "manifest_count": artifact.summary.manifest_count,
            "descriptor_count": artifact.summary.descriptor_count,
        }
        if any(marker[field] != value for field, value in expected_marker.items()):
            raise _mismatch()
        imported_at = marker["imported_at"]

        repository_ids = tuple(
            repository.repository_id for repository in artifact.repositories
        )
        expected_authority = {
            (repository.repository_id, repository.project_id)
            for repository in artifact.repositories
        }
        actual_authority: set[tuple[str, str]] = set()
        authority_names: dict[str, str] = {}
        if repository_ids:
            authority_rows = connection.execute(
                select(
                    repository_table.c.id,
                    repository_table.c.project_id,
                    repository_table.c.name,
                ).where(repository_table.c.id.in_(repository_ids))
            ).all()
            actual_authority = {
                (row.id, row.project_id) for row in authority_rows
            }
            authority_names = {row.id: row.name for row in authority_rows}
        if actual_authority != expected_authority:
            raise _mismatch()
        routes: list[InventoryRepositoryRoute] = []
        for repository in artifact.repositories:
            repository_name = authority_names[repository.repository_id]
            canonical_name = f"p/{repository.project_id}/{repository_name}"
            if REPOSITORY_NAME.fullmatch(canonical_name) is None:
                raise _mismatch()
            routes.append(
                InventoryRepositoryRoute(
                    repository_id=repository.repository_id,
                    canonical_name=canonical_name,
                    manifest_digests=tuple(
                        manifest.digest for manifest in repository.manifests
                    ),
                )
            )

        quota_rows = connection.execute(select(project_quotas)).all()
        quotas = {row.project_id: row for row in quota_rows}
        expected_projects = {project.project_id: project for project in facts.projects}
        if not set(expected_projects).issubset(quotas):
            raise _mismatch()
        over_limit = 0
        for project_id, row in quotas.items():
            expected = expected_projects.get(project_id)
            if expected is None:
                if row.used_bytes != 0 or row.reserved_bytes != 0:
                    raise _mismatch()
                continue
            if (
                row.used_bytes != expected.logical_bytes
                or row.reserved_bytes != 0
                or row.updated_at != imported_at
            ):
                raise _mismatch()
            over_limit += row.used_bytes > row.limit_bytes

        expected_reservations = {
            (
                reservation.reservation_id,
                reservation.project_id,
                reservation.repository_id,
                reservation.manifest_digest,
                facts.request_id,
                "committed",
                1,
                0,
                imported_at,
                imported_at,
            )
            for reservation in facts.reservations
        }
        actual_reservations = {
            (
                row.id,
                row.project_id,
                row.repository_id,
                row.manifest_digest,
                row.request_id,
                row.state,
                row.version,
                row.delta_bytes,
                row.created_at,
                row.updated_at,
            )
            for row in connection.execute(select(quota_reservations))
        }
        if actual_reservations != expected_reservations:
            raise _mismatch()

        expected_edges = {
            (reservation.reservation_id, descriptor.digest, descriptor.size)
            for reservation in facts.reservations
            for descriptor in reservation.descriptors
        }
        actual_edges = {
            (row.reservation_id, row.digest, row.size)
            for row in connection.execute(select(quota_reservation_descriptors))
        }
        if actual_edges != expected_edges:
            raise _mismatch()

        expected_manifests = {
            (
                reservation.project_id,
                reservation.repository_id,
                reservation.manifest_digest,
                reservation.reservation_id,
                "committed",
                imported_at,
            )
            for reservation in facts.reservations
        }
        actual_manifests = {
            (
                row.project_id,
                row.repository_id,
                row.digest,
                row.reservation_id,
                row.state,
                row.updated_at,
            )
            for row in connection.execute(select(quota_manifests))
        }
        if actual_manifests != expected_manifests:
            raise _mismatch()

        expected_descriptors = {
            (
                project.project_id,
                descriptor.digest,
                descriptor.size,
                descriptor.reference_count,
            )
            for project in facts.projects
            for descriptor in project.descriptors
        }
        actual_descriptors = {
            (row.project_id, row.digest, row.size, row.reference_count)
            for row in connection.execute(select(quota_descriptors))
        }
        if actual_descriptors != expected_descriptors:
            raise _mismatch()

        if connection.execute(select(quota_reconciliation_claims)).first() is not None:
            raise _mismatch()

    result = InventoryVerificationResult(
        status="verified",
        inventory_digest=artifact.digest,
        project_count=artifact.summary.project_count,
        repository_count=artifact.summary.repository_count,
        manifest_count=artifact.summary.manifest_count,
        descriptor_count=artifact.summary.descriptor_count,
        reservation_descriptor_count=facts.reservation_descriptor_count,
        over_limit_project_count=over_limit,
    )
    return InventoryVerificationSnapshot(result, tuple(routes))


def verify_inventory_import(
    store: QuotaStore,
    artifact: InventoryArtifact,
) -> InventoryVerificationResult:
    return verify_inventory_import_snapshot(store, artifact).result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a verified inventory with the imported quota ledger"
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    database_url = os.environ.get("COFFER_DATABASE_URL")
    if not database_url:
        print(
            "inventory verification configuration failed: "
            "COFFER_DATABASE_URL is required",
            file=sys.stderr,
        )
        return 78

    store: QuotaStore | None = None
    try:
        artifact = load_inventory_artifact(
            args.inventory,
            expected_digest=args.expected_sha256,
        )
        store = QuotaStore(database_url)
        result = verify_inventory_import(store, artifact)
    except QuotaSchemaNotReady:
        print(
            "inventory verification configuration failed: schema migration is required",
            file=sys.stderr,
        )
        return 78
    except (InvalidInventoryArtifact, InventoryVerificationFailed) as exc:
        print(f"inventory verification failed: {exc}", file=sys.stderr)
        return 1
    except (ArgumentError, ImportError, SQLAlchemyError):
        print(
            "inventory verification failed: database connection is invalid",
            file=sys.stderr,
        )
        return 1
    finally:
        if store is not None:
            store._engine.dispose()
    print(json.dumps(result.to_dict(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
