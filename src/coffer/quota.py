from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import re
import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    delete,
    insert,
    select,
    update,
    create_engine,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool


SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_LOGICAL_BYTES = 2**63 - 1
MAX_DESCRIPTOR_COUNT = 4096
PENDING_STATES = ("pending", "release_pending")

OCI_IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_IMAGE_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_IMAGE_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_MANIFEST_LIST = (
    "application/vnd.docker.distribution.manifest.list.v2+json"
)
IMAGE_MEDIA_TYPES = frozenset({OCI_IMAGE_MANIFEST, DOCKER_IMAGE_MANIFEST})
INDEX_MEDIA_TYPES = frozenset({OCI_IMAGE_INDEX, DOCKER_MANIFEST_LIST})

quota_metadata = MetaData()
project_quotas = Table(
    "project_quotas",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("limit_bytes", BigInteger, nullable=False),
    Column("used_bytes", BigInteger, nullable=False, default=0),
    Column("reserved_bytes", BigInteger, nullable=False, default=0),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
quota_descriptors = Table(
    "quota_descriptors",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("digest", String(71), primary_key=True),
    Column("size", BigInteger, nullable=False),
    Column("reference_count", BigInteger, nullable=False),
)
quota_reservations = Table(
    "quota_reservations",
    quota_metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("repository_id", String(36), nullable=False),
    Column("manifest_digest", String(71), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("state", String(24), nullable=False),
    Column("delta_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "project_id",
        "repository_id",
        "manifest_digest",
        name="uq_quota_reservation_manifest",
    ),
    UniqueConstraint(
        "project_id",
        "repository_id",
        "manifest_digest",
        "request_id",
        name="uq_quota_reservation_request",
    ),
)
quota_reservation_descriptors = Table(
    "quota_reservation_descriptors",
    quota_metadata,
    Column("reservation_id", String(36), primary_key=True),
    Column("digest", String(71), primary_key=True),
    Column("size", BigInteger, nullable=False),
)
quota_manifests = Table(
    "quota_manifests",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("repository_id", String(36), primary_key=True),
    Column("digest", String(71), primary_key=True),
    Column("reservation_id", String(36), nullable=False),
    Column("state", String(24), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class InvalidManifest(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class QuotaNotConfigured(Exception):
    pass


class ReservationNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Descriptor:
    digest: str
    size: int

    def __post_init__(self) -> None:
        if SHA256_DIGEST.fullmatch(self.digest) is None:
            raise InvalidManifest("descriptor digest must be canonical sha256")
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_LOGICAL_BYTES
        ):
            raise InvalidManifest(
                "descriptor size must fit a non-negative signed 64-bit integer"
            )


@dataclass(frozen=True, slots=True)
class ParsedManifest:
    digest: str
    size: int
    descriptors: tuple[Descriptor, ...]
    child_manifests: tuple[Descriptor, ...]


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    project_id: str
    repository_id: str
    manifest_digest: str
    request_id: str
    state: str
    delta_bytes: int

    @classmethod
    def from_row(cls, row: object) -> Reservation:
        mapping = row._mapping  # type: ignore[attr-defined]
        return cls(
            id=mapping["id"],
            project_id=mapping["project_id"],
            repository_id=mapping["repository_id"],
            manifest_digest=mapping["manifest_digest"],
            request_id=mapping["request_id"],
            state=mapping["state"],
            delta_bytes=mapping["delta_bytes"],
        )


@dataclass(frozen=True, slots=True)
class QuotaUsage:
    project_id: str
    limit_bytes: int
    used_bytes: int
    reserved_bytes: int


def _descriptor(value: object) -> Descriptor:
    if not isinstance(value, dict):
        raise InvalidManifest("descriptor must be an object")
    digest = value.get("digest")
    size = value.get("size")
    if not isinstance(digest, str):
        raise InvalidManifest("descriptor digest is required")
    return Descriptor(digest, size)  # type: ignore[arg-type]


def parse_manifest(body: bytes, *, media_type: str | None = None) -> ParsedManifest:
    if not body:
        raise InvalidManifest("manifest body is empty")
    if len(body) > MAX_MANIFEST_BYTES:
        raise InvalidManifest("manifest body exceeds the configured maximum")
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidManifest("manifest body is not valid JSON") from exc
    if not isinstance(document, dict) or document.get("schemaVersion") != 2:
        raise InvalidManifest("manifest must be a schemaVersion 2 object")

    document_media_type = document.get("mediaType")
    if not isinstance(document_media_type, str):
        raise InvalidManifest("manifest mediaType is required")
    requested_media_type = (
        media_type.split(";", 1)[0].strip().lower()
        if media_type is not None
        else document_media_type
    )
    if requested_media_type != document_media_type:
        raise InvalidManifest("Content-Type does not match manifest mediaType")
    if requested_media_type not in IMAGE_MEDIA_TYPES | INDEX_MEDIA_TYPES:
        raise InvalidManifest("manifest mediaType is not supported by quota admission")

    digest = f"sha256:{hashlib.sha256(body).hexdigest()}"
    own = Descriptor(digest, len(body))
    child_manifests: tuple[Descriptor, ...] = ()
    if requested_media_type in INDEX_MEDIA_TYPES:
        if "config" in document or "layers" in document:
            raise InvalidManifest("index must not contain image-manifest fields")
        raw_children = document.get("manifests")
        if not isinstance(raw_children, list) or not raw_children:
            raise InvalidManifest("index manifests must contain child descriptors")
        if len(raw_children) + 1 > MAX_DESCRIPTOR_COUNT:
            raise InvalidManifest("manifest descriptor count exceeds the maximum")
        child_manifests = tuple(_descriptor(value) for value in raw_children)
        candidates = (own, *child_manifests)
    else:
        if "manifests" in document:
            raise InvalidManifest("image manifest must not contain index fields")
        config = _descriptor(document.get("config"))
        raw_layers = document.get("layers")
        if not isinstance(raw_layers, list):
            raise InvalidManifest("image manifests must contain a layer list")
        if len(raw_layers) + 2 > MAX_DESCRIPTOR_COUNT:
            raise InvalidManifest("manifest descriptor count exceeds the maximum")
        candidates = (own, config, *(_descriptor(value) for value in raw_layers))

    unique: dict[str, Descriptor] = {}
    for descriptor in candidates:
        existing = unique.get(descriptor.digest)
        if existing is not None and existing.size != descriptor.size:
            raise InvalidManifest("one digest has conflicting descriptor sizes")
        unique[descriptor.digest] = descriptor
    if len(unique) > MAX_DESCRIPTOR_COUNT:
        raise InvalidManifest("manifest descriptor count exceeds the maximum")
    return ParsedManifest(
        digest=digest,
        size=len(body),
        descriptors=tuple(sorted(unique.values(), key=lambda item: item.digest)),
        child_manifests=child_manifests,
    )


class QuotaStore:
    def __init__(self, connection: str) -> None:
        engine_options: dict[str, object] = {"pool_pre_ping": True}
        if connection.startswith("sqlite:"):
            engine_options["connect_args"] = {
                "check_same_thread": False,
                "timeout": 30,
            }
            if connection in {"sqlite://", "sqlite:///:memory:"}:
                engine_options["poolclass"] = StaticPool
        self._engine: Engine = create_engine(connection, **engine_options)
        quota_metadata.create_all(self._engine)

    @contextmanager
    def _writer(self) -> Iterator[Connection]:
        sqlite = self._engine.dialect.name == "sqlite"
        connection = self._engine.connect()
        transaction = None
        try:
            if sqlite:
                connection = connection.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                transaction = connection.begin()
            yield connection
            if sqlite:
                connection.exec_driver_sql("COMMIT")
            else:
                transaction.commit()
        except BaseException:
            if sqlite:
                connection.exec_driver_sql("ROLLBACK")
            elif transaction is not None:
                transaction.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _reader(self) -> Iterator[Connection]:
        with self._engine.connect() as connection:
            yield connection

    def set_limit(self, project_id: str, limit_bytes: int) -> QuotaUsage:
        if (
            isinstance(limit_bytes, bool)
            or not isinstance(limit_bytes, int)
            or not 0 <= limit_bytes <= MAX_LOGICAL_BYTES
        ):
            raise ValueError(
                "quota limit must fit a non-negative signed 64-bit integer"
            )
        now = datetime.now(UTC)
        with self._writer() as conn:
            row = conn.execute(
                select(project_quotas)
                .where(project_quotas.c.project_id == project_id)
                .with_for_update()
            ).first()
            if row is None:
                conn.execute(
                    insert(project_quotas).values(
                        project_id=project_id,
                        limit_bytes=limit_bytes,
                        used_bytes=0,
                        reserved_bytes=0,
                        updated_at=now,
                    )
                )
            else:
                current = row._mapping  # type: ignore[attr-defined]
                if current["used_bytes"] + current["reserved_bytes"] > limit_bytes:
                    raise QuotaExceeded("new limit is below current charged usage")
                conn.execute(
                    update(project_quotas)
                    .where(project_quotas.c.project_id == project_id)
                    .values(limit_bytes=limit_bytes, updated_at=now)
                )
        return self.usage(project_id)

    def usage(self, project_id: str) -> QuotaUsage:
        with self._reader() as conn:
            row = conn.execute(
                select(project_quotas).where(
                    project_quotas.c.project_id == project_id
                )
            ).first()
        if row is None:
            raise QuotaNotConfigured(project_id)
        value = row._mapping  # type: ignore[attr-defined]
        return QuotaUsage(
            project_id=project_id,
            limit_bytes=value["limit_bytes"],
            used_bytes=value["used_bytes"],
            reserved_bytes=value["reserved_bytes"],
        )

    @staticmethod
    def _reservation_descriptors(conn: object, reservation_id: str) -> list[Descriptor]:
        rows = conn.execute(  # type: ignore[attr-defined]
            select(quota_reservation_descriptors).where(
                quota_reservation_descriptors.c.reservation_id == reservation_id
            )
        )
        return [Descriptor(row.digest, row.size) for row in rows]

    def _recompute(self, conn: object, project_id: str) -> tuple[int, int]:
        committed_rows = conn.execute(  # type: ignore[attr-defined]
            select(quota_descriptors.c.digest, quota_descriptors.c.size).where(
                quota_descriptors.c.project_id == project_id,
                quota_descriptors.c.reference_count > 0,
            )
        ).all()
        seen = {row.digest for row in committed_rows}
        used = sum(row.size for row in committed_rows)
        reserved = 0
        pending_rows = conn.execute(  # type: ignore[attr-defined]
            select(quota_reservations)
            .where(
                quota_reservations.c.project_id == project_id,
                quota_reservations.c.state.in_(PENDING_STATES),
            )
            .order_by(quota_reservations.c.created_at, quota_reservations.c.id)
        ).all()
        for row in pending_rows:
            descriptors = self._reservation_descriptors(conn, row.id)
            delta = sum(item.size for item in descriptors if item.digest not in seen)
            if delta > MAX_LOGICAL_BYTES:
                raise QuotaExceeded(
                    "manifest logical usage exceeds the SQL integer bound"
                )
            seen.update(item.digest for item in descriptors)
            reserved += delta
            conn.execute(  # type: ignore[attr-defined]
                update(quota_reservations)
                .where(quota_reservations.c.id == row.id)
                .values(delta_bytes=delta, updated_at=datetime.now(UTC))
            )
        if used > MAX_LOGICAL_BYTES or reserved > MAX_LOGICAL_BYTES:
            raise QuotaExceeded("project logical usage exceeds the SQL integer bound")
        conn.execute(  # type: ignore[attr-defined]
            update(project_quotas)
            .where(project_quotas.c.project_id == project_id)
            .values(
                used_bytes=used,
                reserved_bytes=reserved,
                updated_at=datetime.now(UTC),
            )
        )
        return used, reserved

    def reserve(
        self,
        *,
        project_id: str,
        repository_id: str,
        manifest_digest: str,
        request_id: str,
        descriptors: tuple[Descriptor, ...],
    ) -> Reservation:
        if SHA256_DIGEST.fullmatch(manifest_digest) is None:
            raise InvalidManifest("manifest digest must be canonical sha256")
        if not request_id or len(request_id) > 128:
            raise ValueError("request_id must contain 1 to 128 characters")
        unique: dict[str, Descriptor] = {}
        for descriptor in descriptors:
            existing = unique.get(descriptor.digest)
            if existing is not None and existing.size != descriptor.size:
                raise InvalidManifest("one digest has conflicting descriptor sizes")
            unique[descriptor.digest] = descriptor
        if manifest_digest not in unique:
            raise InvalidManifest("manifest self descriptor is required")

        now = datetime.now(UTC)
        with self._writer() as conn:
            quota_row = conn.execute(
                select(project_quotas)
                .where(project_quotas.c.project_id == project_id)
                .with_for_update()
            ).first()
            if quota_row is None:
                raise QuotaNotConfigured(project_id)
            target = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.project_id == project_id,
                    quota_reservations.c.repository_id == repository_id,
                    quota_reservations.c.manifest_digest == manifest_digest,
                )
            ).first()
            if target is not None and target.state in {"pending", "committed"}:
                return Reservation.from_row(target)
            if target is not None and target.state == "release_pending":
                conn.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == target.id)
                    .values(
                        request_id=request_id,
                        state="pending",
                        updated_at=now,
                    )
                )
                self._recompute(conn, project_id)
                retried = conn.execute(
                    select(quota_reservations).where(
                        quota_reservations.c.id == target.id
                    )
                ).one()
                return Reservation.from_row(retried)

            reservation_id = target.id if target is not None else str(uuid.uuid4())
            if target is None:
                conn.execute(
                    insert(quota_reservations).values(
                        id=reservation_id,
                        project_id=project_id,
                        repository_id=repository_id,
                        manifest_digest=manifest_digest,
                        request_id=request_id,
                        state="pending",
                        delta_bytes=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    delete(quota_reservation_descriptors).where(
                        quota_reservation_descriptors.c.reservation_id
                        == reservation_id
                    )
                )
                conn.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == reservation_id)
                    .values(
                        request_id=request_id,
                        state="pending",
                        delta_bytes=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            conn.execute(
                insert(quota_reservation_descriptors),
                [
                    {
                        "reservation_id": reservation_id,
                        "digest": item.digest,
                        "size": item.size,
                    }
                    for item in unique.values()
                ],
            )
            used, reserved = self._recompute(conn, project_id)
            limit_bytes = quota_row._mapping["limit_bytes"]  # type: ignore[attr-defined]
            if used + reserved > limit_bytes:
                raise QuotaExceeded("project logical quota would be exceeded")
            row = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            return Reservation.from_row(row)

    def _get_locked(self, conn: object, reservation_id: str) -> object:
        candidate = conn.execute(  # type: ignore[attr-defined]
            select(quota_reservations).where(
                quota_reservations.c.id == reservation_id
            )
        ).first()
        if candidate is None:
            raise ReservationNotFound(reservation_id)
        quota = conn.execute(  # type: ignore[attr-defined]
            select(project_quotas)
            .where(project_quotas.c.project_id == candidate.project_id)
            .with_for_update()
        ).first()
        if quota is None:
            raise QuotaNotConfigured(candidate.project_id)
        row = conn.execute(  # type: ignore[attr-defined]
            select(quota_reservations)
            .where(quota_reservations.c.id == reservation_id)
            .with_for_update()
        ).first()
        if row is None:
            raise ReservationNotFound(reservation_id)
        return row

    def commit(self, reservation_id: str) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            if row.state == "committed":
                return Reservation.from_row(row)
            if row.state != "pending":
                raise ValueError("only a pending reservation can be committed")
            descriptors = self._reservation_descriptors(conn, reservation_id)
            for descriptor in descriptors:
                existing = conn.execute(
                    select(quota_descriptors).where(
                        quota_descriptors.c.project_id == row.project_id,
                        quota_descriptors.c.digest == descriptor.digest,
                    )
                ).first()
                if existing is None:
                    conn.execute(
                        insert(quota_descriptors).values(
                            project_id=row.project_id,
                            digest=descriptor.digest,
                            size=descriptor.size,
                            reference_count=1,
                        )
                    )
                else:
                    if existing.size != descriptor.size:
                        raise InvalidManifest("committed descriptor size changed")
                    conn.execute(
                        update(quota_descriptors)
                        .where(
                            quota_descriptors.c.project_id == row.project_id,
                            quota_descriptors.c.digest == descriptor.digest,
                        )
                        .values(reference_count=existing.reference_count + 1)
                    )
            now = datetime.now(UTC)
            conn.execute(
                update(quota_reservations)
                .where(quota_reservations.c.id == reservation_id)
                .values(state="committed", delta_bytes=0, updated_at=now)
            )
            existing_manifest = conn.execute(
                select(quota_manifests).where(
                    quota_manifests.c.project_id == row.project_id,
                    quota_manifests.c.repository_id == row.repository_id,
                    quota_manifests.c.digest == row.manifest_digest,
                )
            ).first()
            if existing_manifest is None:
                conn.execute(
                    insert(quota_manifests).values(
                        project_id=row.project_id,
                        repository_id=row.repository_id,
                        digest=row.manifest_digest,
                        reservation_id=reservation_id,
                        state="committed",
                        updated_at=now,
                    )
                )
            else:
                conn.execute(
                    update(quota_manifests)
                    .where(
                        quota_manifests.c.project_id == row.project_id,
                        quota_manifests.c.repository_id == row.repository_id,
                        quota_manifests.c.digest == row.manifest_digest,
                    )
                    .values(
                        reservation_id=reservation_id,
                        state="committed",
                        updated_at=now,
                    )
                )
            self._recompute(conn, row.project_id)
            committed = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            return Reservation.from_row(committed)

    def mark_release_pending(self, reservation_id: str) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            if row.state in {"committed", "released", "release_pending"}:
                return Reservation.from_row(row)
            conn.execute(
                update(quota_reservations)
                .where(quota_reservations.c.id == reservation_id)
                .values(state="release_pending", updated_at=datetime.now(UTC))
            )
            self._recompute(conn, row.project_id)
            result = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            return Reservation.from_row(result)

    def reconcile_absent(self, reservation_id: str) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            if row.state == "released":
                return Reservation.from_row(row)
            if row.state not in {"pending", "release_pending", "committed"}:
                raise ValueError("reservation cannot be released")
            committed_manifest = conn.execute(
                select(quota_manifests).where(
                    quota_manifests.c.reservation_id == reservation_id,
                    quota_manifests.c.state == "committed",
                )
            ).first()
            if committed_manifest is not None:
                for descriptor in self._reservation_descriptors(conn, reservation_id):
                    existing = conn.execute(
                        select(quota_descriptors).where(
                            quota_descriptors.c.project_id == row.project_id,
                            quota_descriptors.c.digest == descriptor.digest,
                        )
                    ).one()
                    if existing.reference_count <= 1:
                        conn.execute(
                            delete(quota_descriptors).where(
                                quota_descriptors.c.project_id == row.project_id,
                                quota_descriptors.c.digest == descriptor.digest,
                            )
                        )
                    else:
                        conn.execute(
                            update(quota_descriptors)
                            .where(
                                quota_descriptors.c.project_id == row.project_id,
                                quota_descriptors.c.digest == descriptor.digest,
                            )
                            .values(reference_count=existing.reference_count - 1)
                        )
            now = datetime.now(UTC)
            conn.execute(
                update(quota_reservations)
                .where(quota_reservations.c.id == reservation_id)
                .values(state="released", delta_bytes=0, updated_at=now)
            )
            conn.execute(
                update(quota_manifests)
                .where(quota_manifests.c.reservation_id == reservation_id)
                .values(state="released", updated_at=now)
            )
            self._recompute(conn, row.project_id)
            result = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            return Reservation.from_row(result)

    def manifest_graph(self, project_id: str, digest: str) -> tuple[Descriptor, ...] | None:
        with self._reader() as conn:
            manifest = conn.execute(
                select(quota_manifests).where(
                    quota_manifests.c.project_id == project_id,
                    quota_manifests.c.digest == digest,
                    quota_manifests.c.state == "committed",
                )
            ).first()
            if manifest is None:
                return None
            return tuple(
                self._reservation_descriptors(conn, manifest.reservation_id)
            )
