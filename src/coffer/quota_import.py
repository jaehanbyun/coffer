from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.exc import ArgumentError, IntegrityError, SQLAlchemyError

from coffer.db import repositories as repository_table
from coffer.inventory import (
    INVENTORY_SCHEMA,
    MAX_INPUT_BYTES,
    MAX_MEDIA_TYPE_BYTES,
    MAX_RECORD_COUNT,
    MEDIA_TYPE,
    PINNED_DISTRIBUTION_VERSION,
    PINNED_ENUMERATOR,
)
from coffer.quota import (
    Descriptor,
    IMAGE_MEDIA_TYPES,
    INDEX_MEDIA_TYPES,
    MAX_DESCRIPTOR_COUNT,
    MAX_LOGICAL_BYTES,
    MAX_MANIFEST_BYTES,
    SHA256_DIGEST,
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
from coffer.tokens import PROJECT_ID


class InvalidInventoryArtifact(Exception):
    pass


class InventoryImportConflict(Exception):
    pass


class InventoryImportNotReady(Exception):
    pass


class InventoryImportFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class InventoryDescriptor:
    digest: str
    media_type: str
    size: int


@dataclass(frozen=True, slots=True)
class InventoryManifest:
    digest: str
    media_type: str
    size: int
    references: tuple[InventoryDescriptor, ...]


@dataclass(frozen=True, slots=True)
class InventoryRepository:
    project_id: str
    repository_id: str
    manifests: tuple[InventoryManifest, ...]


@dataclass(frozen=True, slots=True)
class InventoryProject:
    project_id: str
    descriptors: tuple[InventoryDescriptor, ...]
    logical_bytes: int


@dataclass(frozen=True, slots=True)
class InventorySummary:
    project_count: int
    repository_count: int
    manifest_count: int
    descriptor_count: int
    logical_bytes: int


@dataclass(frozen=True, slots=True)
class InventoryArtifact:
    digest: str
    projects: tuple[InventoryProject, ...]
    repositories: tuple[InventoryRepository, ...]
    summary: InventorySummary


@dataclass(frozen=True, slots=True)
class InventoryImportResult:
    status: str
    inventory_digest: str
    project_count: int
    repository_count: int
    manifest_count: int
    descriptor_count: int
    over_limit_project_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "descriptor_count": self.descriptor_count,
            "inventory_digest": self.inventory_digest,
            "manifest_count": self.manifest_count,
            "over_limit_project_count": self.over_limit_project_count,
            "project_count": self.project_count,
            "repository_count": self.repository_count,
            "status": self.status,
        }


def _fail(message: str) -> InvalidInventoryArtifact:
    return InvalidInventoryArtifact(message)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _fail(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail(f"{label} must be an array")
    return value


def _exact_keys(value: dict[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise _fail(f"{label} fields are invalid")


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_LOGICAL_BYTES,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _fail(f"{label} is outside its allowed integer range")
    return value


def _string(value: object, label: str, *, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode()) > maximum_bytes
    ):
        raise _fail(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    digest = _string(value, label, maximum_bytes=71)
    if SHA256_DIGEST.fullmatch(digest) is None:
        raise _fail(f"{label} must be canonical sha256")
    return digest


def _media_type(value: object, label: str) -> str:
    media_type = _string(value, label, maximum_bytes=MAX_MEDIA_TYPE_BYTES)
    if MEDIA_TYPE.fullmatch(media_type) is None:
        raise _fail(f"{label} is invalid")
    return media_type


def _project_id(value: object, label: str) -> str:
    project_id = _string(value, label, maximum_bytes=36)
    if PROJECT_ID.fullmatch(project_id) is None:
        raise _fail(f"{label} is not a canonical project UUID")
    return project_id


def _repository_id(value: object, label: str) -> str:
    repository_id = _string(value, label, maximum_bytes=36)
    try:
        if str(uuid.UUID(repository_id)) != repository_id:
            raise ValueError
    except ValueError as exc:
        raise _fail(f"{label} is not a canonical UUID") from exc
    return repository_id


def _parse_descriptor(value: object, label: str) -> InventoryDescriptor:
    raw = _object(value, label)
    _exact_keys(raw, {"digest", "media_type", "size"}, label)
    return InventoryDescriptor(
        digest=_digest(raw["digest"], f"{label}.digest"),
        media_type=_media_type(raw["media_type"], f"{label}.media_type"),
        size=_integer(raw["size"], f"{label}.size"),
    )


def _parse_manifest(value: object, label: str) -> InventoryManifest:
    raw = _object(value, label)
    _exact_keys(raw, {"digest", "media_type", "references", "size"}, label)
    digest = _digest(raw["digest"], f"{label}.digest")
    media_type = _media_type(raw["media_type"], f"{label}.media_type")
    if media_type not in IMAGE_MEDIA_TYPES | INDEX_MEDIA_TYPES:
        raise _fail(f"{label}.media_type is not supported")
    references_raw = _array(raw["references"], f"{label}.references")
    if len(references_raw) >= MAX_DESCRIPTOR_COUNT:
        raise _fail(f"{label} has too many references")
    references = tuple(
        _parse_descriptor(reference, f"{label}.references[{index}]")
        for index, reference in enumerate(references_raw)
    )
    if tuple(reference.digest for reference in references) != tuple(
        sorted({reference.digest for reference in references})
    ):
        raise _fail(f"{label}.references must be unique and digest-sorted")
    if media_type in INDEX_MEDIA_TYPES:
        if not references:
            raise _fail(f"{label} index has no child manifests")
        if any(
            reference.media_type not in IMAGE_MEDIA_TYPES | INDEX_MEDIA_TYPES
            for reference in references
        ):
            raise _fail(f"{label} index has an unsupported child media type")
    return InventoryManifest(
        digest=digest,
        media_type=media_type,
        references=references,
        size=_integer(
            raw["size"],
            f"{label}.size",
            minimum=1,
            maximum=MAX_MANIFEST_BYTES,
        ),
    )


def _parse_repository(value: object, label: str) -> InventoryRepository:
    raw = _object(value, label)
    _exact_keys(raw, {"manifests", "project_id", "repository_id"}, label)
    manifests_raw = _array(raw["manifests"], f"{label}.manifests")
    if len(manifests_raw) > MAX_RECORD_COUNT:
        raise _fail(f"{label} has too many manifests")
    manifests = tuple(
        _parse_manifest(manifest, f"{label}.manifests[{index}]")
        for index, manifest in enumerate(manifests_raw)
    )
    if tuple(manifest.digest for manifest in manifests) != tuple(
        sorted({manifest.digest for manifest in manifests})
    ):
        raise _fail(f"{label}.manifests must be unique and digest-sorted")
    by_digest = {manifest.digest: manifest for manifest in manifests}
    for manifest in manifests:
        if manifest.media_type not in INDEX_MEDIA_TYPES:
            continue
        for reference in manifest.references:
            child = by_digest.get(reference.digest)
            if child is None:
                raise _fail(f"{label} index child is not an enumerated manifest")
            if child.media_type != reference.media_type or child.size != reference.size:
                raise _fail(f"{label} index child descriptor facts do not match")
    return InventoryRepository(
        project_id=_project_id(raw["project_id"], f"{label}.project_id"),
        repository_id=_repository_id(
            raw["repository_id"], f"{label}.repository_id"
        ),
        manifests=manifests,
    )


def _parse_project(value: object, label: str) -> InventoryProject:
    raw = _object(value, label)
    _exact_keys(
        raw,
        {"descriptor_count", "descriptors", "logical_bytes", "project_id"},
        label,
    )
    descriptors_raw = _array(raw["descriptors"], f"{label}.descriptors")
    descriptors = tuple(
        _parse_descriptor(descriptor, f"{label}.descriptors[{index}]")
        for index, descriptor in enumerate(descriptors_raw)
    )
    if tuple(descriptor.digest for descriptor in descriptors) != tuple(
        sorted({descriptor.digest for descriptor in descriptors})
    ):
        raise _fail(f"{label}.descriptors must be unique and digest-sorted")
    descriptor_count = _integer(
        raw["descriptor_count"],
        f"{label}.descriptor_count",
        maximum=MAX_RECORD_COUNT,
    )
    if descriptor_count != len(descriptors):
        raise _fail(f"{label}.descriptor_count does not match")
    logical_bytes = sum(descriptor.size for descriptor in descriptors)
    if logical_bytes > MAX_LOGICAL_BYTES:
        raise _fail(f"{label}.logical_bytes exceeds the SQL bound")
    if _integer(raw["logical_bytes"], f"{label}.logical_bytes") != logical_bytes:
        raise _fail(f"{label}.logical_bytes does not match")
    return InventoryProject(
        project_id=_project_id(raw["project_id"], f"{label}.project_id"),
        descriptors=descriptors,
        logical_bytes=logical_bytes,
    )


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def parse_inventory_artifact(
    value: object,
    *,
    artifact_digest: str,
) -> InventoryArtifact:
    digest = _digest(artifact_digest, "artifact digest")
    raw = _object(value, "inventory")
    _exact_keys(
        raw,
        {"projects", "repositories", "schema", "source", "summary"},
        "inventory",
    )
    if raw["schema"] != INVENTORY_SCHEMA:
        raise _fail("inventory schema is unsupported")
    source = _object(raw["source"], "inventory.source")
    _exact_keys(
        source,
        {"distribution_version", "enumerator", "snapshot_scans"},
        "inventory.source",
    )
    if source["distribution_version"] != PINNED_DISTRIBUTION_VERSION:
        raise _fail("inventory Distribution version is not pinned")
    if source["enumerator"] != PINNED_ENUMERATOR:
        raise _fail("inventory enumerator is unsupported")
    if source["snapshot_scans"] != 2:
        raise _fail("inventory snapshot scan count is invalid")

    projects_raw = _array(raw["projects"], "inventory.projects")
    repositories_raw = _array(raw["repositories"], "inventory.repositories")
    if len(projects_raw) > MAX_RECORD_COUNT or len(repositories_raw) > MAX_RECORD_COUNT:
        raise _fail("inventory contains too many projects or repositories")
    projects = tuple(
        _parse_project(project, f"inventory.projects[{index}]")
        for index, project in enumerate(projects_raw)
    )
    if tuple(project.project_id for project in projects) != tuple(
        sorted({project.project_id for project in projects})
    ):
        raise _fail("inventory.projects must be unique and project-sorted")
    repositories = tuple(
        _parse_repository(repository, f"inventory.repositories[{index}]")
        for index, repository in enumerate(repositories_raw)
    )
    repository_keys = tuple(
        (repository.project_id, repository.repository_id)
        for repository in repositories
    )
    if repository_keys != tuple(sorted(set(repository_keys))):
        raise _fail("inventory.repositories must be unique and authority-sorted")
    repository_ids = [repository.repository_id for repository in repositories]
    if len(repository_ids) != len(set(repository_ids)):
        raise _fail("inventory repository IDs must be globally unique")
    if {repository.project_id for repository in repositories} != {
        project.project_id for project in projects
    }:
        raise _fail("inventory project summaries must match repository projects")

    recomputed: dict[str, dict[str, InventoryDescriptor]] = {
        project.project_id: {} for project in projects
    }
    for repository in repositories:
        if repository.project_id not in recomputed:
            raise _fail("inventory repository has no project summary")
        descriptors = recomputed[repository.project_id]
        for manifest in repository.manifests:
            for descriptor in (
                InventoryDescriptor(
                    manifest.digest, manifest.media_type, manifest.size
                ),
                *manifest.references,
            ):
                existing = descriptors.get(descriptor.digest)
                if existing is not None and existing != descriptor:
                    raise _fail("inventory has conflicting project descriptor facts")
                descriptors[descriptor.digest] = descriptor
    for project in projects:
        expected = tuple(
            descriptor
            for _, descriptor in sorted(recomputed[project.project_id].items())
        )
        if project.descriptors != expected:
            raise _fail("inventory project descriptors do not match repositories")

    summary_raw = _object(raw["summary"], "inventory.summary")
    _exact_keys(
        summary_raw,
        {
            "descriptor_count",
            "logical_bytes",
            "manifest_count",
            "project_count",
            "repository_count",
        },
        "inventory.summary",
    )
    summary = InventorySummary(
        project_count=len(projects),
        repository_count=len(repositories),
        manifest_count=sum(len(repository.manifests) for repository in repositories),
        descriptor_count=sum(len(project.descriptors) for project in projects),
        logical_bytes=sum(project.logical_bytes for project in projects),
    )
    for field in (
        "project_count",
        "repository_count",
        "manifest_count",
        "descriptor_count",
        "logical_bytes",
    ):
        maximum = (
            MAX_RECORD_COUNT * MAX_LOGICAL_BYTES
            if field == "logical_bytes"
            else MAX_RECORD_COUNT
        )
        actual = _integer(
            summary_raw[field],
            f"inventory.summary.{field}",
            maximum=maximum,
        )
        if actual != getattr(summary, field):
            raise _fail(f"inventory.summary.{field} does not match")
    return InventoryArtifact(
        digest=digest,
        projects=projects,
        repositories=repositories,
        summary=summary,
    )


def load_inventory_artifact(path: Path, *, expected_digest: str) -> InventoryArtifact:
    expected = _digest(expected_digest, "expected artifact digest")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise _fail(f"cannot read inventory input {path.name}") from exc
    if not 0 < len(payload) <= MAX_INPUT_BYTES:
        raise _fail(f"inventory input {path.name} is empty or too large")
    actual = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if actual != expected:
        raise _fail("inventory artifact digest does not match the expected digest")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"inventory input {path.name} is not valid JSON") from exc
    if payload != _canonical_bytes(value):
        raise _fail("inventory artifact is not canonical compact JSON")
    return parse_inventory_artifact(value, artifact_digest=actual)


_IMPORT_SCOPE = "baseline"
_MAX_TRANSACTION_ATTEMPTS = 3
_RESERVATION_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://github.com/jaehanbyun/coffer/quota-inventory",
)


def _reservation_id(
    artifact: InventoryArtifact,
    repository: InventoryRepository,
    manifest: InventoryManifest,
) -> str:
    return str(
        uuid.uuid5(
            _RESERVATION_NAMESPACE,
            "/".join(
                (
                    artifact.digest,
                    repository.project_id,
                    repository.repository_id,
                    manifest.digest,
                )
            ),
        )
    )


def _marker_result(
    connection: object,
    marker: object,
    artifact: InventoryArtifact,
    *,
    status: str,
) -> InventoryImportResult:
    values = marker._mapping  # type: ignore[attr-defined]
    expected = {
        "inventory_digest": artifact.digest,
        "project_count": artifact.summary.project_count,
        "repository_count": artifact.summary.repository_count,
        "manifest_count": artifact.summary.manifest_count,
        "descriptor_count": artifact.summary.descriptor_count,
    }
    if any(values[field] != value for field, value in expected.items()):
        raise InventoryImportConflict(
            "committed baseline marker does not match this inventory artifact"
        )
    project_ids = tuple(project.project_id for project in artifact.projects)
    over_limit = 0
    if project_ids:
        quota_rows = connection.execute(  # type: ignore[attr-defined]
            select(
                project_quotas.c.project_id,
                project_quotas.c.limit_bytes,
                project_quotas.c.used_bytes,
            ).where(
                project_quotas.c.project_id.in_(project_ids)
            )
        ).all()
        if {row.project_id for row in quota_rows} != set(project_ids):
            raise InventoryImportConflict(
                "committed baseline project quota state is incomplete"
            )
        over_limit = sum(row.used_bytes > row.limit_bytes for row in quota_rows)
    return InventoryImportResult(
        status=status,
        inventory_digest=artifact.digest,
        project_count=artifact.summary.project_count,
        repository_count=artifact.summary.repository_count,
        manifest_count=artifact.summary.manifest_count,
        descriptor_count=artifact.summary.descriptor_count,
        over_limit_project_count=over_limit,
    )


def _ledger_is_nonempty(connection: object) -> bool:
    for table in (
        quota_descriptors,
        quota_reservations,
        quota_reconciliation_claims,
        quota_reservation_descriptors,
        quota_manifests,
    ):
        count = connection.execute(  # type: ignore[attr-defined]
            select(func.count()).select_from(table)
        ).scalar_one()
        if count:
            return True
    return False


def _require_authority(
    connection: object,
    artifact: InventoryArtifact,
) -> dict[str, int]:
    if _ledger_is_nonempty(connection):
        raise InventoryImportConflict("quota ledger is not empty")
    drifted_usage = connection.execute(  # type: ignore[attr-defined]
        select(func.count())
        .select_from(project_quotas)
        .where(
            or_(
                project_quotas.c.used_bytes != 0,
                project_quotas.c.reserved_bytes != 0,
            )
        )
    ).scalar_one()
    if drifted_usage:
        raise InventoryImportConflict("empty ledger has nonzero quota usage")

    project_ids = tuple(project.project_id for project in artifact.projects)
    quota_limits: dict[str, int] = {}
    if project_ids:
        quota_rows = connection.execute(  # type: ignore[attr-defined]
            select(project_quotas)
            .where(project_quotas.c.project_id.in_(project_ids))
            .with_for_update()
        ).all()
        quota_limits = {row.project_id: row.limit_bytes for row in quota_rows}
        if set(quota_limits) != set(project_ids):
            raise InventoryImportNotReady(
                "every inventory project requires an existing quota"
            )

    repository_ids = tuple(
        repository.repository_id for repository in artifact.repositories
    )
    authority: dict[str, str] = {}
    if repository_ids:
        rows = connection.execute(  # type: ignore[attr-defined]
            select(repository_table.c.id, repository_table.c.project_id)
            .where(repository_table.c.id.in_(repository_ids))
            .with_for_update()
        ).all()
        authority = {row.id: row.project_id for row in rows}
    if len(authority) != len(repository_ids) or any(
        authority.get(repository.repository_id) != repository.project_id
        for repository in artifact.repositories
    ):
        raise InventoryImportNotReady(
            "inventory repository authority does not match the control schema"
        )
    return quota_limits


def _import_inventory_once(
    store: QuotaStore,
    artifact: InventoryArtifact,
    *,
    imported_at: datetime,
) -> InventoryImportResult:
    with store._writer() as connection:
        marker = connection.execute(
            select(quota_inventory_imports)
            .where(quota_inventory_imports.c.scope == _IMPORT_SCOPE)
            .with_for_update()
        ).first()
        if marker is not None:
            return _marker_result(
                connection, marker, artifact, status="already_imported"
            )

        connection.execute(
            insert(quota_inventory_imports).values(
                scope=_IMPORT_SCOPE,
                inventory_digest=artifact.digest,
                project_count=artifact.summary.project_count,
                repository_count=artifact.summary.repository_count,
                manifest_count=artifact.summary.manifest_count,
                descriptor_count=artifact.summary.descriptor_count,
                imported_at=imported_at,
            )
        )
        quota_limits = _require_authority(connection, artifact)

        reference_counts: dict[str, Counter[str]] = {
            project.project_id: Counter() for project in artifact.projects
        }
        request_id = f"inventory:{artifact.digest.removeprefix('sha256:')}"
        for repository in artifact.repositories:
            for manifest in repository.manifests:
                graph = {
                    descriptor.digest: Descriptor(descriptor.digest, descriptor.size)
                    for descriptor in manifest.references
                }
                own = Descriptor(manifest.digest, manifest.size)
                existing = graph.get(own.digest)
                if existing is not None and existing != own:
                    raise InvalidInventoryArtifact(
                        "manifest self descriptor conflicts with its references"
                    )
                graph[own.digest] = own
                reference_counts[repository.project_id].update(graph.keys())
                reservation_id = _reservation_id(artifact, repository, manifest)
                connection.execute(
                    insert(quota_reservations).values(
                        id=reservation_id,
                        project_id=repository.project_id,
                        repository_id=repository.repository_id,
                        manifest_digest=manifest.digest,
                        request_id=request_id,
                        state="committed",
                        version=1,
                        delta_bytes=0,
                        created_at=imported_at,
                        updated_at=imported_at,
                    )
                )
                if graph:
                    connection.execute(
                        insert(quota_reservation_descriptors),
                        [
                            {
                                "reservation_id": reservation_id,
                                "digest": descriptor.digest,
                                "size": descriptor.size,
                            }
                            for _, descriptor in sorted(graph.items())
                        ],
                    )
                connection.execute(
                    insert(quota_manifests).values(
                        project_id=repository.project_id,
                        repository_id=repository.repository_id,
                        digest=manifest.digest,
                        reservation_id=reservation_id,
                        state="committed",
                        updated_at=imported_at,
                    )
                )

        for project in artifact.projects:
            if project.descriptors:
                connection.execute(
                    insert(quota_descriptors),
                    [
                        {
                            "project_id": project.project_id,
                            "digest": descriptor.digest,
                            "size": descriptor.size,
                            "reference_count": reference_counts[
                                project.project_id
                            ][descriptor.digest],
                        }
                        for descriptor in project.descriptors
                    ],
                )
            connection.execute(
                update(project_quotas)
                .where(project_quotas.c.project_id == project.project_id)
                .values(
                    used_bytes=project.logical_bytes,
                    reserved_bytes=0,
                    updated_at=imported_at,
                )
            )

        over_limit = sum(
            project.logical_bytes > quota_limits[project.project_id]
            for project in artifact.projects
        )
        return InventoryImportResult(
            status="imported",
            inventory_digest=artifact.digest,
            project_count=artifact.summary.project_count,
            repository_count=artifact.summary.repository_count,
            manifest_count=artifact.summary.manifest_count,
            descriptor_count=artifact.summary.descriptor_count,
            over_limit_project_count=over_limit,
        )


def import_inventory(
    store: QuotaStore,
    artifact: InventoryArtifact,
    *,
    imported_at: datetime | None = None,
) -> InventoryImportResult:
    timestamp = imported_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("imported_at must be timezone-aware")
    timestamp = timestamp.astimezone(UTC)
    for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
        try:
            return _import_inventory_once(store, artifact, imported_at=timestamp)
        except IntegrityError as exc:
            marker_result = _result_after_transaction_error(store, artifact)
            if marker_result is not None:
                return marker_result
            raise InventoryImportFailed(
                "inventory import transaction failed without a committed marker"
            ) from exc
        except SQLAlchemyError as exc:
            marker_result = _result_after_transaction_error(store, artifact)
            if marker_result is not None:
                return marker_result
            if (
                _retryable_transaction_error(exc)
                and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
            ):
                continue
            raise InventoryImportFailed(
                "inventory import transaction failed"
            ) from exc
    raise AssertionError("bounded inventory import attempts were exhausted")


def _result_after_transaction_error(
    store: QuotaStore,
    artifact: InventoryArtifact,
) -> InventoryImportResult | None:
    try:
        with store._reader() as connection:
            marker = connection.execute(
                select(quota_inventory_imports).where(
                    quota_inventory_imports.c.scope == _IMPORT_SCOPE
                )
            ).first()
            if marker is None:
                return None
            return _marker_result(
                connection,
                marker,
                artifact,
                status="already_imported",
            )
    except SQLAlchemyError:
        return None


def _retryable_transaction_error(exc: SQLAlchemyError) -> bool:
    original = getattr(exc, "orig", None)
    arguments = getattr(original, "args", ())
    mysql_code = arguments[0] if arguments else None
    sqlstate = getattr(original, "sqlstate", None) or getattr(
        original, "pgcode", None
    )
    return mysql_code in {1205, 1213} or sqlstate in {"40001", "40P01"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import one verified inventory into an empty quota ledger"
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args(argv)
    database_url = os.environ.get("COFFER_DATABASE_URL")
    if not database_url:
        print(
            "inventory import configuration failed: COFFER_DATABASE_URL is required",
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
        result = import_inventory(store, artifact)
    except QuotaSchemaNotReady as exc:
        print(f"inventory import configuration failed: {exc}", file=sys.stderr)
        return 78
    except (
        InvalidInventoryArtifact,
        InventoryImportConflict,
        InventoryImportNotReady,
        InventoryImportFailed,
    ) as exc:
        print(f"inventory import failed: {exc}", file=sys.stderr)
        return 1
    except (ArgumentError, ImportError, SQLAlchemyError):
        print(
            "inventory import failed: database connection is invalid",
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
