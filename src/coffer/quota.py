from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
import hashlib
import json
import logging
import re
from typing import Concatenate, ParamSpec, TypeVar
import uuid

from sqlalchemy import (
    and_,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    func,
    Index,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    delete,
    insert,
    or_,
    select,
    update,
    create_engine,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from coffer.schema import SchemaNotReady, require_current_schema


SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_LOGICAL_BYTES = 2**63 - 1
MAX_DESCRIPTOR_COUNT = 4096
PENDING_STATES = ("pending", "release_pending")
RECONCILIATION_STATES = ("pending", "release_pending", "committed")
MAX_RECONCILIATION_BATCH = 1000
MAX_RECONCILIATION_LEASE_SECONDS = 3600
MAX_CONTROL_EVIDENCE_PENDING = 1000
MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS = 100_000
MAX_CONTROL_EVIDENCE_CLAIMS = 10_000
MIN_COMPARISON_SESSION_SECONDS = 60
MAX_COMPARISON_SESSION_SECONDS = 3600
OCI_IMAGE_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_IMAGE_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_IMAGE_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_MANIFEST_LIST = (
    "application/vnd.docker.distribution.manifest.list.v2+json"
)
IMAGE_MEDIA_TYPES = frozenset({OCI_IMAGE_MANIFEST, DOCKER_IMAGE_MANIFEST})
INDEX_MEDIA_TYPES = frozenset({OCI_IMAGE_INDEX, DOCKER_MANIFEST_LIST})
MAX_TRANSACTION_ATTEMPTS = 3
QUOTA_WRITE_OPERATIONS = frozenset(
    {"claim", "commit", "limit", "reconcile", "release", "reserve"}
)
QUOTA_TRANSACTION_RESULTS = frozenset(
    {"conflict_exhausted", "database_error", "rejected", "success"}
)

LOG = logging.getLogger(__name__)
P = ParamSpec("P")
R = TypeVar("R")

quota_metadata = MetaData()
project_quotas = Table(
    "project_quotas",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("limit_bytes", BigInteger, nullable=False),
    Column("used_bytes", BigInteger, nullable=False, default=0),
    Column("reserved_bytes", BigInteger, nullable=False, default=0),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("limit_bytes >= 0", name="ck_project_quota_limit"),
    CheckConstraint("used_bytes >= 0", name="ck_project_quota_used"),
    CheckConstraint("reserved_bytes >= 0", name="ck_project_quota_reserved"),
)
quota_descriptors = Table(
    "quota_descriptors",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("digest", String(71), primary_key=True),
    Column("size", BigInteger, nullable=False),
    Column("reference_count", BigInteger, nullable=False),
    CheckConstraint("size >= 0", name="ck_quota_descriptor_size"),
    CheckConstraint("reference_count > 0", name="ck_quota_descriptor_refs"),
)
quota_reservations = Table(
    "quota_reservations",
    quota_metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "project_id",
        String(64),
        ForeignKey("project_quotas.project_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("repository_id", String(36), nullable=False),
    Column("manifest_digest", String(71), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("state", String(24), nullable=False),
    Column("version", BigInteger, nullable=False),
    Column("delta_bytes", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "state IN ('pending', 'release_pending', 'committed', 'released')",
        name="ck_quota_reservation_state",
    ),
    CheckConstraint("version > 0", name="ck_quota_reservation_version"),
    CheckConstraint("delta_bytes >= 0", name="ck_quota_reservation_delta"),
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
Index(
    "ix_quota_reservations_reconcile",
    quota_reservations.c.state,
    quota_reservations.c.updated_at,
    quota_reservations.c.id,
)
Index(
    "ix_quota_reservations_project_state",
    quota_reservations.c.project_id,
    quota_reservations.c.state,
)
quota_reconciliation_claims = Table(
    "quota_reconciliation_claims",
    quota_metadata,
    Column(
        "reservation_id",
        String(36),
        ForeignKey("quota_reservations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("claim_token", String(36), nullable=False),
    Column("worker_id", String(128), nullable=False),
    Column("reservation_version", BigInteger, nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "reservation_version > 0",
        name="ck_quota_reconciliation_claim_version",
    ),
    CheckConstraint(
        "expires_at > claimed_at", name="ck_quota_reconciliation_claim_window"
    ),
    UniqueConstraint(
        "claim_token", name="uq_quota_reconciliation_claim_token"
    ),
)
Index(
    "ix_quota_reconciliation_claims_expires",
    quota_reconciliation_claims.c.expires_at,
    quota_reconciliation_claims.c.reservation_id,
)
quota_reservation_descriptors = Table(
    "quota_reservation_descriptors",
    quota_metadata,
    Column(
        "reservation_id",
        String(36),
        ForeignKey("quota_reservations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("digest", String(71), primary_key=True),
    Column("size", BigInteger, nullable=False),
    CheckConstraint("size >= 0", name="ck_quota_reservation_descriptor_size"),
)
quota_manifests = Table(
    "quota_manifests",
    quota_metadata,
    Column("project_id", String(64), primary_key=True),
    Column("repository_id", String(36), primary_key=True),
    Column("digest", String(71), primary_key=True),
    Column(
        "reservation_id",
        String(36),
        ForeignKey("quota_reservations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("state", String(24), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "state IN ('committed', 'released')", name="ck_quota_manifest_state"
    ),
)
Index(
    "ix_quota_manifests_project_digest_state",
    quota_manifests.c.project_id,
    quota_manifests.c.digest,
    quota_manifests.c.state,
)
quota_inventory_imports = Table(
    "quota_inventory_imports",
    quota_metadata,
    Column("scope", String(32), primary_key=True),
    Column("inventory_digest", String(71), nullable=False),
    Column("project_count", BigInteger, nullable=False),
    Column("repository_count", BigInteger, nullable=False),
    Column("manifest_count", BigInteger, nullable=False),
    Column("descriptor_count", BigInteger, nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "scope = 'baseline'", name="ck_quota_inventory_import_scope"
    ),
    CheckConstraint(
        "project_count >= 0", name="ck_quota_inventory_import_projects"
    ),
    CheckConstraint(
        "repository_count >= 0", name="ck_quota_inventory_import_repositories"
    ),
    CheckConstraint(
        "manifest_count >= 0", name="ck_quota_inventory_import_manifests"
    ),
    CheckConstraint(
        "descriptor_count >= 0", name="ck_quota_inventory_import_descriptors"
    ),
    UniqueConstraint(
        "inventory_digest", name="uq_quota_inventory_import_digest"
    ),
)
maintenance_comparison_sessions = Table(
    "maintenance_comparison_sessions",
    quota_metadata,
    Column("id", String(36), primary_key=True),
    Column("request_id", String(128), nullable=False),
    Column(
        "inventory_digest",
        String(71),
        ForeignKey(
            "quota_inventory_imports.inventory_digest",
            ondelete="RESTRICT",
        ),
        nullable=False,
    ),
    Column("workload_id", String(128), nullable=False),
    Column("writer_exclusion_ref", String(128), nullable=False),
    Column("state", String(16), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "state IN ('approved', 'completed', 'revoked')",
        name="ck_maintenance_comparison_session_state",
    ),
    CheckConstraint(
        "expires_at > approved_at",
        name="ck_maintenance_comparison_session_window",
    ),
    CheckConstraint(
        "(state = 'approved' AND closed_at IS NULL) OR "
        "(state IN ('completed', 'revoked') AND closed_at IS NOT NULL)",
        name="ck_maintenance_comparison_session_lifecycle",
    ),
    UniqueConstraint(
        "request_id",
        name="uq_maintenance_comparison_session_request",
    ),
)
Index(
    "ix_maintenance_comparison_sessions_state_expires",
    maintenance_comparison_sessions.c.state,
    maintenance_comparison_sessions.c.expires_at,
    maintenance_comparison_sessions.c.id,
)


class InvalidManifest(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class QuotaNotConfigured(Exception):
    pass


class ReservationNotFound(Exception):
    pass


class QuotaSchemaNotReady(SchemaNotReady):
    pass


class StaleReconciliationCandidate(Exception):
    pass


class StaleReconciliationClaim(Exception):
    pass


class ReconciliationReadNotAuthorized(Exception):
    pass


class ComparisonSessionNotReady(Exception):
    def __init__(self) -> None:
        super().__init__("comparison session is not ready")


class ComparisonSessionConflict(Exception):
    def __init__(self) -> None:
        super().__init__("comparison session conflicts with current authority")


class ComparisonSessionNotAuthorized(Exception):
    def __init__(self) -> None:
        super().__init__("comparison session read is not authorized")


def _retryable_transaction_error(exc: SQLAlchemyError) -> bool:
    original = getattr(exc, "orig", None)
    arguments = getattr(original, "args", ())
    mysql_code = arguments[0] if arguments else None
    sqlstate = getattr(original, "sqlstate", None) or getattr(
        original, "pgcode", None
    )
    return mysql_code in {1205, 1213} or sqlstate in {"40001", "40P01"}


def _retryable_quota_write(
    operation: str,
) -> Callable[
    [Callable[Concatenate["QuotaStore", P], R]],
    Callable[Concatenate["QuotaStore", P], R],
]:
    if operation not in QUOTA_WRITE_OPERATIONS:
        raise ValueError("quota write operation is not bounded")

    def decorate(
        method: Callable[Concatenate["QuotaStore", P], R],
    ) -> Callable[Concatenate["QuotaStore", P], R]:
        @wraps(method)
        def wrapped(
            store: "QuotaStore", *args: P.args, **kwargs: P.kwargs
        ) -> R:
            for attempt in range(1, MAX_TRANSACTION_ATTEMPTS + 1):
                try:
                    result = method(store, *args, **kwargs)
                except SQLAlchemyError as exc:
                    retryable = _retryable_transaction_error(exc)
                    if retryable and attempt < MAX_TRANSACTION_ATTEMPTS:
                        LOG.warning(
                            "retrying quota write after database transaction conflict",
                            extra={
                                "quota_operation": operation,
                                "quota_retry_attempt": attempt + 1,
                            },
                        )
                        continue
                    store._observe_quota_transaction(
                        operation,
                        attempt,
                        (
                            "conflict_exhausted"
                            if retryable
                            else "database_error"
                        ),
                    )
                    raise
                except Exception:
                    store._observe_quota_transaction(
                        operation,
                        attempt,
                        "rejected",
                    )
                    raise
                store._observe_quota_transaction(
                    operation,
                    attempt,
                    "success",
                )
                return result
            raise AssertionError("bounded quota write attempts were exhausted")

        return wrapped

    return decorate


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
    version: int
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
            version=mapping["version"],
            delta_bytes=mapping["delta_bytes"],
        )


@dataclass(frozen=True, slots=True)
class QuotaUsage:
    project_id: str
    limit_bytes: int
    used_bytes: int
    reserved_bytes: int


@dataclass(frozen=True, slots=True)
class ReconciliationCursor:
    updated_at: datetime
    reservation_id: str


@dataclass(frozen=True, slots=True)
class ReconciliationCandidate:
    reservation_id: str
    project_id: str
    repository_id: str
    manifest_digest: str
    state: str
    version: int
    updated_at: datetime

    @classmethod
    def from_row(cls, row: object) -> ReconciliationCandidate:
        mapping = row._mapping  # type: ignore[attr-defined]
        updated_at = mapping["updated_at"]
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return cls(
            reservation_id=mapping["id"],
            project_id=mapping["project_id"],
            repository_id=mapping["repository_id"],
            manifest_digest=mapping["manifest_digest"],
            state=mapping["state"],
            version=mapping["version"],
            updated_at=updated_at,
        )


@dataclass(frozen=True, slots=True)
class ReconciliationPage:
    candidates: tuple[ReconciliationCandidate, ...]
    next_cursor: ReconciliationCursor | None


@dataclass(frozen=True, slots=True)
class ReconciliationClaim:
    reservation_id: str
    project_id: str
    repository_id: str
    manifest_digest: str
    state: str
    version: int
    updated_at: datetime
    claim_token: str
    worker_id: str
    claimed_at: datetime
    expires_at: datetime

    @classmethod
    def from_row(
        cls,
        row: object,
        *,
        claim_token: str,
        worker_id: str,
        claimed_at: datetime,
        expires_at: datetime,
    ) -> ReconciliationClaim:
        candidate = ReconciliationCandidate.from_row(row)
        return cls(
            reservation_id=candidate.reservation_id,
            project_id=candidate.project_id,
            repository_id=candidate.repository_id,
            manifest_digest=candidate.manifest_digest,
            state=candidate.state,
            version=candidate.version,
            updated_at=candidate.updated_at,
            claim_token=claim_token,
            worker_id=worker_id,
            claimed_at=claimed_at,
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class ReconciliationClaimPage:
    claims: tuple[ReconciliationClaim, ...]
    next_cursor: ReconciliationCursor | None


@dataclass(frozen=True, slots=True)
class ReconciliationMetricsSnapshot:
    backlog: int
    active_claims: int
    stale_claims: int
    oldest_pending_seconds: float


@dataclass(frozen=True, slots=True)
class QuotaControlEvidenceSnapshot:
    limit_bytes: int
    used_bytes: int
    reserved_bytes: int
    expected_used_bytes: int
    expected_reserved_bytes: int
    pending_reservations: int
    mismatched_pending_deltas: int
    descriptor_invariant_violations: int
    active_claims: int
    stale_claims: int
    eligible_active_claims: int
    claim_invariant_violations: int

    @property
    def quota_invariant(self) -> bool:
        return (
            self.used_bytes == self.expected_used_bytes
            and self.reserved_bytes == self.expected_reserved_bytes
            and self.mismatched_pending_deltas == 0
            and self.descriptor_invariant_violations == 0
            and self.used_bytes + self.reserved_bytes <= self.limit_bytes
        )

    @property
    def claims_exact(self) -> bool:
        return (
            self.active_claims == self.eligible_active_claims
            and self.claim_invariant_violations == 0
        )


@dataclass(frozen=True, slots=True)
class ReconciliationReadAuthority:
    project_id: str
    repository_id: str
    reservation_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ComparisonSession:
    id: str
    request_id: str
    inventory_digest: str
    workload_id: str
    writer_exclusion_ref: str
    state: str
    approved_at: datetime
    expires_at: datetime
    closed_at: datetime | None

    @classmethod
    def from_row(cls, row: object) -> ComparisonSession:
        mapping = row._mapping  # type: ignore[attr-defined]

        def aware(value: datetime | None) -> datetime | None:
            if value is not None and value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value

        return cls(
            id=mapping["id"],
            request_id=mapping["request_id"],
            inventory_digest=mapping["inventory_digest"],
            workload_id=mapping["workload_id"],
            writer_exclusion_ref=mapping["writer_exclusion_ref"],
            state=mapping["state"],
            approved_at=aware(mapping["approved_at"]),  # type: ignore[arg-type]
            expires_at=aware(mapping["expires_at"]),  # type: ignore[arg-type]
            closed_at=aware(mapping["closed_at"]),
        )


@dataclass(frozen=True, slots=True)
class LiveComparisonReadAuthority:
    project_id: str
    repository_id: str
    session_id: str
    expires_at: datetime


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
    def __init__(
        self,
        connection: str,
        *,
        bootstrap_schema: bool = False,
        transaction_observer: Callable[[str, int, str], None] | None = None,
    ) -> None:
        if transaction_observer is not None and not callable(
            transaction_observer
        ):
            raise ValueError("quota transaction observer must be callable")
        self._transaction_observer = transaction_observer
        engine_options: dict[str, object] = {"pool_pre_ping": True}
        if connection.startswith("sqlite:"):
            engine_options["connect_args"] = {
                "check_same_thread": False,
                "timeout": 30,
            }
            if connection in {"sqlite://", "sqlite:///:memory:"}:
                engine_options["poolclass"] = StaticPool
        self._engine: Engine = create_engine(connection, **engine_options)
        if bootstrap_schema:
            quota_metadata.create_all(self._engine)
        else:
            self._require_migrated_schema()

    def _observe_quota_transaction(
        self,
        operation: str,
        attempts: int,
        result: str,
    ) -> None:
        observer = self._transaction_observer
        if observer is None:
            return
        try:
            observer(operation, attempts, result)
        except Exception:
            LOG.error(
                "quota transaction observation failed",
                extra={
                    "quota_operation": operation,
                    "quota_transaction_attempts": attempts,
                    "quota_transaction_result": result,
                },
            )

    def _require_migrated_schema(self) -> None:
        require_current_schema(
            self._engine,
            expected_tables=quota_metadata.tables,
            component="quota",
            error_type=QuotaSchemaNotReady,
        )

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

    @_retryable_quota_write("limit")
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

    def get_reservation(self, reservation_id: str) -> Reservation:
        with self._reader() as conn:
            row = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).first()
        if row is None:
            raise ReservationNotFound(reservation_id)
        return Reservation.from_row(row)

    def list_reconciliation_candidates(
        self,
        *,
        stale_before: datetime,
        limit: int,
        after: ReconciliationCursor | None = None,
    ) -> ReconciliationPage:
        if stale_before.tzinfo is None or stale_before.utcoffset() is None:
            raise ValueError("stale_before must be timezone-aware")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECONCILIATION_BATCH
        ):
            raise ValueError(
                f"reconciliation limit must be between 1 and {MAX_RECONCILIATION_BATCH}"
            )
        if after is not None and (
            after.updated_at.tzinfo is None
            or after.updated_at.utcoffset() is None
            or not after.reservation_id
        ):
            raise ValueError("reconciliation cursor is invalid")

        statement = select(quota_reservations).where(
            quota_reservations.c.state.in_(RECONCILIATION_STATES),
            quota_reservations.c.updated_at <= stale_before,
        )
        if after is not None:
            statement = statement.where(
                or_(
                    quota_reservations.c.updated_at > after.updated_at,
                    and_(
                        quota_reservations.c.updated_at == after.updated_at,
                        quota_reservations.c.id > after.reservation_id,
                    ),
                )
            )
        statement = statement.order_by(
            quota_reservations.c.updated_at, quota_reservations.c.id
        ).limit(limit)
        with self._reader() as conn:
            rows = tuple(conn.execute(statement))
        candidates = tuple(ReconciliationCandidate.from_row(row) for row in rows)
        next_cursor = None
        if len(candidates) == limit:
            final = candidates[-1]
            next_cursor = ReconciliationCursor(
                updated_at=final.updated_at,
                reservation_id=final.reservation_id,
            )
        return ReconciliationPage(candidates=candidates, next_cursor=next_cursor)

    @_retryable_quota_write("claim")
    def claim_reconciliation_candidates(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
        lease_for: timedelta,
        stale_before: datetime,
        limit: int,
        after: ReconciliationCursor | None = None,
    ) -> ReconciliationClaimPage:
        if (
            not worker_id
            or worker_id.strip() != worker_id
            or len(worker_id) > 128
        ):
            raise ValueError(
                "reconciliation worker_id must contain 1 to 128 characters"
            )
        if claimed_at.tzinfo is None or claimed_at.utcoffset() is None:
            raise ValueError("claimed_at must be timezone-aware")
        if stale_before.tzinfo is None or stale_before.utcoffset() is None:
            raise ValueError("stale_before must be timezone-aware")
        lease_seconds = lease_for.total_seconds()
        if not 0 < lease_seconds <= MAX_RECONCILIATION_LEASE_SECONDS:
            raise ValueError(
                "reconciliation lease must be greater than zero and at most "
                f"{MAX_RECONCILIATION_LEASE_SECONDS} seconds"
            )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RECONCILIATION_BATCH
        ):
            raise ValueError(
                f"reconciliation limit must be between 1 and {MAX_RECONCILIATION_BATCH}"
            )
        if after is not None and (
            after.updated_at.tzinfo is None
            or after.updated_at.utcoffset() is None
            or not after.reservation_id
        ):
            raise ValueError("reconciliation cursor is invalid")

        statement = select(quota_reservations).select_from(
            quota_reservations.outerjoin(
                quota_reconciliation_claims,
                quota_reconciliation_claims.c.reservation_id
                == quota_reservations.c.id,
            )
        ).where(
            quota_reservations.c.state.in_(RECONCILIATION_STATES),
            quota_reservations.c.updated_at <= stale_before,
            or_(
                quota_reconciliation_claims.c.reservation_id.is_(None),
                quota_reconciliation_claims.c.expires_at <= claimed_at,
            ),
        )
        if after is not None:
            statement = statement.where(
                or_(
                    quota_reservations.c.updated_at > after.updated_at,
                    and_(
                        quota_reservations.c.updated_at == after.updated_at,
                        quota_reservations.c.id > after.reservation_id,
                    ),
                )
            )
        statement = (
            statement.order_by(
                quota_reservations.c.updated_at, quota_reservations.c.id
            )
            .limit(limit)
            .with_for_update(skip_locked=True, of=quota_reservations)
        )
        try:
            expires_at = claimed_at + lease_for
        except OverflowError as exc:
            raise ValueError("reconciliation lease expiry is out of range") from exc
        claims: list[ReconciliationClaim] = []
        with self._writer() as conn:
            rows = tuple(conn.execute(statement))
            for row in rows:
                conn.execute(
                    delete(quota_reconciliation_claims).where(
                        quota_reconciliation_claims.c.reservation_id == row.id,
                        quota_reconciliation_claims.c.expires_at <= claimed_at,
                    )
                )
                claim_token = str(uuid.uuid4())
                conn.execute(
                    insert(quota_reconciliation_claims).values(
                        reservation_id=row.id,
                        claim_token=claim_token,
                        worker_id=worker_id,
                        reservation_version=row.version,
                        claimed_at=claimed_at,
                        expires_at=expires_at,
                    )
                )
                claims.append(
                    ReconciliationClaim.from_row(
                        row,
                        claim_token=claim_token,
                        worker_id=worker_id,
                        claimed_at=claimed_at,
                        expires_at=expires_at,
                    )
                )
        next_cursor = None
        if len(claims) == limit:
            final = claims[-1]
            next_cursor = ReconciliationCursor(
                updated_at=final.updated_at,
                reservation_id=final.reservation_id,
            )
        return ReconciliationClaimPage(
            claims=tuple(claims), next_cursor=next_cursor
        )

    def reconciliation_metrics_snapshot(
        self,
        *,
        observed_at: datetime,
        stale_after: timedelta,
    ) -> ReconciliationMetricsSnapshot:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("reconciliation metrics time must be timezone-aware")
        if stale_after.total_seconds() < 0:
            raise ValueError("reconciliation metrics stale_after must not be negative")
        stale_before = observed_at - stale_after
        with self._reader() as conn:
            backlog, oldest_pending = conn.execute(
                select(
                    func.count(quota_reservations.c.id),
                    func.min(quota_reservations.c.updated_at),
                ).where(
                    quota_reservations.c.state.in_(RECONCILIATION_STATES),
                    quota_reservations.c.updated_at <= stale_before,
                )
            ).one()
            active_claims = conn.execute(
                select(func.count(quota_reconciliation_claims.c.reservation_id)).where(
                    quota_reconciliation_claims.c.expires_at > observed_at
                )
            ).scalar_one()
            stale_claims = conn.execute(
                select(func.count(quota_reconciliation_claims.c.reservation_id)).where(
                    quota_reconciliation_claims.c.expires_at <= observed_at
                )
            ).scalar_one()
        oldest_seconds = 0.0
        if oldest_pending is not None:
            if oldest_pending.tzinfo is None:
                oldest_pending = oldest_pending.replace(tzinfo=UTC)
            oldest_seconds = max(
                0.0,
                (observed_at - oldest_pending).total_seconds(),
            )
        return ReconciliationMetricsSnapshot(
            backlog=int(backlog),
            active_claims=int(active_claims),
            stale_claims=int(stale_claims),
            oldest_pending_seconds=oldest_seconds,
        )

    def control_evidence_snapshot(
        self,
        project_id: str,
        *,
        observed_at: datetime,
    ) -> QuotaControlEvidenceSnapshot:
        if (
            not project_id
            or project_id.strip() != project_id
            or len(project_id) > 64
            or "\x00" in project_id
        ):
            raise ValueError("control evidence project is invalid")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("control evidence time must be timezone-aware")
        observed_at = observed_at.astimezone(UTC)
        with self._reader() as conn:
            quota_row = conn.execute(
                select(project_quotas).where(
                    project_quotas.c.project_id == project_id
                )
            ).first()
            if quota_row is None:
                raise QuotaNotConfigured(project_id)

            committed_rows = tuple(
                conn.execute(
                    select(
                        quota_descriptors.c.digest,
                        quota_descriptors.c.size,
                        quota_descriptors.c.reference_count,
                    )
                    .where(quota_descriptors.c.project_id == project_id)
                    .order_by(quota_descriptors.c.digest)
                    .limit(MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS + 1)
                )
            )
            if len(committed_rows) > MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS:
                raise ValueError(
                    "control evidence committed descriptor bound exceeded"
                )

            pending_rows = tuple(
                conn.execute(
                    select(
                        quota_reservations.c.id,
                        quota_reservations.c.delta_bytes,
                    )
                    .where(
                        quota_reservations.c.project_id == project_id,
                        quota_reservations.c.state.in_(PENDING_STATES),
                    )
                    .order_by(
                        quota_reservations.c.created_at,
                        quota_reservations.c.id,
                    )
                    .limit(MAX_CONTROL_EVIDENCE_PENDING + 1)
                )
            )
            if len(pending_rows) > MAX_CONTROL_EVIDENCE_PENDING:
                raise ValueError(
                    "control evidence pending reservation bound exceeded"
                )

            reservation_ids = [row.id for row in pending_rows]
            descriptor_rows: tuple[object, ...] = ()
            if reservation_ids:
                descriptor_rows = tuple(
                    conn.execute(
                        select(
                            quota_reservation_descriptors.c.reservation_id,
                            quota_reservation_descriptors.c.digest,
                            quota_reservation_descriptors.c.size,
                        )
                        .where(
                            quota_reservation_descriptors.c.reservation_id.in_(
                                reservation_ids
                            )
                        )
                        .order_by(
                            quota_reservation_descriptors.c.reservation_id,
                            quota_reservation_descriptors.c.digest,
                        )
                        .limit(MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS + 1)
                    )
                )
                if (
                    len(descriptor_rows)
                    > MAX_CONTROL_EVIDENCE_DESCRIPTOR_ROWS
                ):
                    raise ValueError(
                        "control evidence pending descriptor bound exceeded"
                    )

            claim_rows = tuple(
                conn.execute(
                    select(
                        quota_reconciliation_claims.c.expires_at,
                        quota_reconciliation_claims.c.reservation_version,
                        quota_reservations.c.state,
                        quota_reservations.c.version,
                    )
                    .select_from(
                        quota_reconciliation_claims.join(
                            quota_reservations,
                            quota_reconciliation_claims.c.reservation_id
                            == quota_reservations.c.id,
                        )
                    )
                    .order_by(
                        quota_reconciliation_claims.c.expires_at,
                        quota_reconciliation_claims.c.reservation_id,
                    )
                    .limit(MAX_CONTROL_EVIDENCE_CLAIMS + 1)
                )
            )
            if len(claim_rows) > MAX_CONTROL_EVIDENCE_CLAIMS:
                raise ValueError("control evidence claim bound exceeded")

        expected_sizes: dict[str, int] = {}
        descriptor_violations = 0
        expected_used = 0
        for row in committed_rows:
            size = int(row.size)
            references = int(row.reference_count)
            if size < 0 or references <= 0 or row.digest in expected_sizes:
                descriptor_violations += 1
                continue
            expected_sizes[row.digest] = size
            expected_used += size

        by_reservation: dict[str, list[tuple[str, int]]] = {
            row.id: [] for row in pending_rows
        }
        for row in descriptor_rows:
            by_reservation[row.reservation_id].append(
                (row.digest, int(row.size))
            )

        expected_reserved = 0
        mismatched_deltas = 0
        for row in pending_rows:
            descriptors = by_reservation[row.id]
            if not descriptors:
                descriptor_violations += 1
            delta = 0
            for digest, size in descriptors:
                if size < 0:
                    descriptor_violations += 1
                    continue
                existing_size = expected_sizes.get(digest)
                if existing_size is not None:
                    if existing_size != size:
                        descriptor_violations += 1
                    continue
                expected_sizes[digest] = size
                delta += size
            expected_reserved += delta
            if int(row.delta_bytes) != delta:
                mismatched_deltas += 1

        active_claims = 0
        stale_claims = 0
        eligible_active_claims = 0
        claim_violations = 0
        for row in claim_rows:
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= observed_at:
                stale_claims += 1
                continue
            active_claims += 1
            if (
                row.state in RECONCILIATION_STATES
                and row.reservation_version == row.version
            ):
                eligible_active_claims += 1
            else:
                claim_violations += 1

        quota = quota_row._mapping  # type: ignore[attr-defined]
        return QuotaControlEvidenceSnapshot(
            limit_bytes=int(quota["limit_bytes"]),
            used_bytes=int(quota["used_bytes"]),
            reserved_bytes=int(quota["reserved_bytes"]),
            expected_used_bytes=expected_used,
            expected_reserved_bytes=expected_reserved,
            pending_reservations=len(pending_rows),
            mismatched_pending_deltas=mismatched_deltas,
            descriptor_invariant_violations=descriptor_violations,
            active_claims=active_claims,
            stale_claims=stale_claims,
            eligible_active_claims=eligible_active_claims,
            claim_invariant_violations=claim_violations,
        )

    @_retryable_quota_write("claim")
    def release_reconciliation_claim(self, claim_token: str) -> bool:
        if not claim_token or len(claim_token) > 36:
            raise ValueError("reconciliation claim token is invalid")
        with self._writer() as conn:
            result = conn.execute(
                delete(quota_reconciliation_claims).where(
                    quota_reconciliation_claims.c.claim_token == claim_token
                )
            )
            return result.rowcount == 1

    def authorize_reconciliation_read(
        self,
        *,
        reservation_id: str,
        repository_id: str,
        claim_token: str,
        expected_version: int,
        worker_id: str,
        checked_at: datetime,
    ) -> ReconciliationReadAuthority:
        if (
            not reservation_id
            or len(reservation_id) > 36
            or not repository_id
            or len(repository_id) > 36
            or not claim_token
            or len(claim_token) > 36
            or not worker_id
            or worker_id.strip() != worker_id
            or len(worker_id) > 128
            or isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version <= 0
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
        ):
            raise ReconciliationReadNotAuthorized(
                "reconciliation read is not authorized"
            )

        statement = (
            select(
                quota_reservations.c.project_id,
                quota_reservations.c.repository_id,
                quota_reservations.c.id.label("reservation_id"),
                quota_reconciliation_claims.c.expires_at,
            )
            .select_from(
                quota_reservations.join(
                    quota_reconciliation_claims,
                    quota_reconciliation_claims.c.reservation_id
                    == quota_reservations.c.id,
                )
            )
            .where(
                quota_reservations.c.id == reservation_id,
                quota_reservations.c.repository_id == repository_id,
                quota_reservations.c.state.in_(RECONCILIATION_STATES),
                quota_reservations.c.version == expected_version,
                quota_reconciliation_claims.c.claim_token == claim_token,
                quota_reconciliation_claims.c.worker_id == worker_id,
                quota_reconciliation_claims.c.reservation_version
                == expected_version,
                quota_reconciliation_claims.c.expires_at > checked_at,
            )
        )
        with self._reader() as conn:
            row = conn.execute(statement).first()
        if row is None:
            raise ReconciliationReadNotAuthorized(
                "reconciliation read is not authorized"
            )
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return ReconciliationReadAuthority(
            project_id=row.project_id,
            repository_id=row.repository_id,
            reservation_id=row.reservation_id,
            expires_at=expires_at,
        )

    def approve_live_comparison_session(
        self,
        *,
        request_id: str,
        inventory_digest: str,
        workload_id: str,
        writer_exclusion_ref: str,
        approved_at: datetime,
        lifetime: timedelta,
    ) -> ComparisonSession:
        lifetime_seconds = lifetime.total_seconds()
        if (
            not request_id
            or request_id.strip() != request_id
            or len(request_id) > 128
            or SHA256_DIGEST.fullmatch(inventory_digest) is None
            or not workload_id
            or workload_id.strip() != workload_id
            or len(workload_id) > 128
            or not writer_exclusion_ref
            or writer_exclusion_ref.strip() != writer_exclusion_ref
            or len(writer_exclusion_ref) > 128
            or approved_at.tzinfo is None
            or approved_at.utcoffset() is None
            or not MIN_COMPARISON_SESSION_SECONDS
            <= lifetime_seconds
            <= MAX_COMPARISON_SESSION_SECONDS
        ):
            raise ComparisonSessionNotReady()
        approved_at = approved_at.astimezone(UTC)
        try:
            expires_at = approved_at + lifetime
        except OverflowError:
            raise ComparisonSessionNotReady() from None

        with self._writer() as conn:
            marker = conn.execute(
                select(quota_inventory_imports)
                .where(
                    quota_inventory_imports.c.scope == "baseline",
                    quota_inventory_imports.c.inventory_digest
                    == inventory_digest,
                )
                .with_for_update()
            ).first()
            if marker is None:
                raise ComparisonSessionNotReady()
            inventory_request_id = (
                f"inventory:{inventory_digest.removeprefix('sha256:')}"
            )
            imported_rows = tuple(
                conn.execute(
                    select(
                        quota_reservations.c.repository_id,
                        quota_reservations.c.project_id,
                    ).where(
                        quota_reservations.c.request_id == inventory_request_id,
                        quota_reservations.c.state == "committed",
                    )
                )
            )
            if (
                len(imported_rows) != marker.manifest_count
                or len({row.repository_id for row in imported_rows})
                != marker.repository_count
            ):
                raise ComparisonSessionNotReady()

            existing_row = conn.execute(
                select(maintenance_comparison_sessions)
                .where(
                    maintenance_comparison_sessions.c.request_id == request_id
                )
                .with_for_update()
            ).first()
            if existing_row is not None:
                existing = ComparisonSession.from_row(existing_row)
                if (
                    existing.inventory_digest != inventory_digest
                    or existing.workload_id != workload_id
                    or existing.writer_exclusion_ref != writer_exclusion_ref
                    or existing.approved_at != approved_at
                    or existing.expires_at != expires_at
                ):
                    raise ComparisonSessionConflict()
                return existing

            active_claim = conn.execute(
                select(quota_reconciliation_claims.c.reservation_id).where(
                    quota_reconciliation_claims.c.expires_at > approved_at
                )
            ).first()
            if active_claim is not None:
                raise ComparisonSessionNotReady()

            session_id = str(uuid.uuid4())
            conn.execute(
                insert(maintenance_comparison_sessions).values(
                    id=session_id,
                    request_id=request_id,
                    inventory_digest=inventory_digest,
                    workload_id=workload_id,
                    writer_exclusion_ref=writer_exclusion_ref,
                    state="approved",
                    approved_at=approved_at,
                    expires_at=expires_at,
                    closed_at=None,
                )
            )
            row = conn.execute(
                select(maintenance_comparison_sessions).where(
                    maintenance_comparison_sessions.c.id == session_id
                )
            ).one()
            return ComparisonSession.from_row(row)

    def close_live_comparison_session(
        self,
        session_id: str,
        *,
        final_state: str,
        closed_at: datetime,
    ) -> ComparisonSession:
        if (
            not session_id
            or len(session_id) > 36
            or final_state not in {"completed", "revoked"}
            or closed_at.tzinfo is None
            or closed_at.utcoffset() is None
        ):
            raise ComparisonSessionConflict()
        closed_at = closed_at.astimezone(UTC)
        with self._writer() as conn:
            row = conn.execute(
                select(maintenance_comparison_sessions)
                .where(maintenance_comparison_sessions.c.id == session_id)
                .with_for_update()
            ).first()
            if row is None:
                raise ComparisonSessionConflict()
            current = ComparisonSession.from_row(row)
            if closed_at < current.approved_at:
                raise ComparisonSessionConflict()
            if current.state == final_state:
                return current
            if current.state != "approved":
                raise ComparisonSessionConflict()
            conn.execute(
                update(maintenance_comparison_sessions)
                .where(maintenance_comparison_sessions.c.id == session_id)
                .values(state=final_state, closed_at=closed_at)
            )
            updated = conn.execute(
                select(maintenance_comparison_sessions).where(
                    maintenance_comparison_sessions.c.id == session_id
                )
            ).one()
            return ComparisonSession.from_row(updated)

    def authorize_live_comparison_read(
        self,
        *,
        session_id: str,
        inventory_digest: str,
        repository_id: str,
        workload_id: str,
        checked_at: datetime,
    ) -> LiveComparisonReadAuthority:
        if (
            not session_id
            or len(session_id) > 36
            or SHA256_DIGEST.fullmatch(inventory_digest) is None
            or not repository_id
            or len(repository_id) > 36
            or not workload_id
            or workload_id.strip() != workload_id
            or len(workload_id) > 128
            or checked_at.tzinfo is None
            or checked_at.utcoffset() is None
        ):
            raise ComparisonSessionNotAuthorized()
        checked_at = checked_at.astimezone(UTC)
        inventory_request_id = (
            f"inventory:{inventory_digest.removeprefix('sha256:')}"
        )
        with self._reader() as conn:
            session = conn.execute(
                select(maintenance_comparison_sessions).select_from(
                    maintenance_comparison_sessions.join(
                        quota_inventory_imports,
                        quota_inventory_imports.c.inventory_digest
                        == maintenance_comparison_sessions.c.inventory_digest,
                    )
                )
                .where(
                    maintenance_comparison_sessions.c.id == session_id,
                    maintenance_comparison_sessions.c.inventory_digest
                    == inventory_digest,
                    maintenance_comparison_sessions.c.workload_id == workload_id,
                    maintenance_comparison_sessions.c.state == "approved",
                    maintenance_comparison_sessions.c.expires_at > checked_at,
                    quota_inventory_imports.c.scope == "baseline",
                )
            ).first()
            if session is None:
                raise ComparisonSessionNotAuthorized()
            if (
                conn.execute(
                    select(quota_reconciliation_claims.c.reservation_id).where(
                        quota_reconciliation_claims.c.expires_at > checked_at
                    )
                ).first()
                is not None
            ):
                raise ComparisonSessionNotAuthorized()
            project_ids = tuple(
                conn.execute(
                    select(quota_reservations.c.project_id)
                    .where(
                        quota_reservations.c.repository_id == repository_id,
                        quota_reservations.c.request_id == inventory_request_id,
                        quota_reservations.c.state == "committed",
                    )
                    .distinct()
                ).scalars()
            )
        if len(project_ids) != 1:
            raise ComparisonSessionNotAuthorized()
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return LiveComparisonReadAuthority(
            project_id=project_ids[0],
            repository_id=repository_id,
            session_id=session_id,
            expires_at=expires_at,
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
            if row.delta_bytes != delta:
                conn.execute(  # type: ignore[attr-defined]
                    update(quota_reservations)
                    .where(quota_reservations.c.id == row.id)
                    .values(
                        delta_bytes=delta,
                        version=quota_reservations.c.version + 1,
                        updated_at=datetime.now(UTC),
                    )
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

    @_retryable_quota_write("reserve")
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
                        version=quota_reservations.c.version + 1,
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
                        version=1,
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
                        version=quota_reservations.c.version + 1,
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

    @staticmethod
    def _check_reconciliation_version(
        row: object, expected_version: int | None
    ) -> None:
        if expected_version is not None and row.version != expected_version:  # type: ignore[attr-defined]
            raise StaleReconciliationCandidate(str(row.id))  # type: ignore[attr-defined]

    @staticmethod
    def _check_reconciliation_claim(
        conn: object,
        reservation_id: str,
        expected_claim_token: str | None,
        expected_version: int | None,
        claim_checked_at: datetime | None,
    ) -> None:
        if expected_claim_token is None:
            if claim_checked_at is not None:
                raise ValueError(
                    "claim_checked_at requires an expected reconciliation claim token"
                )
            return
        if expected_version is None:
            raise ValueError(
                "an expected reconciliation version is required with a claim token"
            )
        if not expected_claim_token or len(expected_claim_token) > 36:
            raise ValueError("reconciliation claim token is invalid")
        checked_at = claim_checked_at or datetime.now(UTC)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("claim_checked_at must be timezone-aware")
        claim = conn.execute(  # type: ignore[attr-defined]
            select(quota_reconciliation_claims)
            .where(
                quota_reconciliation_claims.c.reservation_id == reservation_id
            )
            .with_for_update()
        ).first()
        if (
            claim is None
            or claim.claim_token != expected_claim_token
            or (
                expected_version is not None
                and claim.reservation_version != expected_version
            )
        ):
            raise StaleReconciliationClaim(reservation_id)
        expires_at = claim.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= checked_at:
            raise StaleReconciliationClaim(reservation_id)

    @staticmethod
    def _consume_reconciliation_claim(
        conn: object,
        reservation_id: str,
        expected_claim_token: str | None,
    ) -> None:
        if expected_claim_token is None:
            return
        result = conn.execute(  # type: ignore[attr-defined]
            delete(quota_reconciliation_claims).where(
                quota_reconciliation_claims.c.reservation_id == reservation_id,
                quota_reconciliation_claims.c.claim_token == expected_claim_token,
            )
        )
        if result.rowcount != 1:
            raise StaleReconciliationClaim(reservation_id)

    def _commit_locked(self, conn: object, row: object) -> Reservation:
        if row.state == "committed":  # type: ignore[attr-defined]
            return Reservation.from_row(row)
        if row.state != "pending":  # type: ignore[attr-defined]
            raise ValueError("only a pending reservation can be committed")
        reservation_id = row.id  # type: ignore[attr-defined]
        descriptors = self._reservation_descriptors(conn, reservation_id)
        for descriptor in descriptors:
            existing = conn.execute(  # type: ignore[attr-defined]
                select(quota_descriptors).where(
                    quota_descriptors.c.project_id == row.project_id,  # type: ignore[attr-defined]
                    quota_descriptors.c.digest == descriptor.digest,
                )
            ).first()
            if existing is None:
                conn.execute(  # type: ignore[attr-defined]
                    insert(quota_descriptors).values(
                        project_id=row.project_id,  # type: ignore[attr-defined]
                        digest=descriptor.digest,
                        size=descriptor.size,
                        reference_count=1,
                    )
                )
            else:
                if existing.size != descriptor.size:
                    raise InvalidManifest("committed descriptor size changed")
                conn.execute(  # type: ignore[attr-defined]
                    update(quota_descriptors)
                    .where(
                        quota_descriptors.c.project_id == row.project_id,  # type: ignore[attr-defined]
                        quota_descriptors.c.digest == descriptor.digest,
                    )
                    .values(reference_count=existing.reference_count + 1)
                )
        now = datetime.now(UTC)
        conn.execute(  # type: ignore[attr-defined]
            update(quota_reservations)
            .where(quota_reservations.c.id == reservation_id)
            .values(
                state="committed",
                version=quota_reservations.c.version + 1,
                delta_bytes=0,
                updated_at=now,
            )
        )
        existing_manifest = conn.execute(  # type: ignore[attr-defined]
            select(quota_manifests).where(
                quota_manifests.c.project_id == row.project_id,  # type: ignore[attr-defined]
                quota_manifests.c.repository_id == row.repository_id,  # type: ignore[attr-defined]
                quota_manifests.c.digest == row.manifest_digest,  # type: ignore[attr-defined]
            )
        ).first()
        if existing_manifest is None:
            conn.execute(  # type: ignore[attr-defined]
                insert(quota_manifests).values(
                    project_id=row.project_id,  # type: ignore[attr-defined]
                    repository_id=row.repository_id,  # type: ignore[attr-defined]
                    digest=row.manifest_digest,  # type: ignore[attr-defined]
                    reservation_id=reservation_id,
                    state="committed",
                    updated_at=now,
                )
            )
        else:
            conn.execute(  # type: ignore[attr-defined]
                update(quota_manifests)
                .where(
                    quota_manifests.c.project_id == row.project_id,  # type: ignore[attr-defined]
                    quota_manifests.c.repository_id == row.repository_id,  # type: ignore[attr-defined]
                    quota_manifests.c.digest == row.manifest_digest,  # type: ignore[attr-defined]
                )
                .values(
                    reservation_id=reservation_id,
                    state="committed",
                    updated_at=now,
                )
            )
        self._recompute(conn, row.project_id)  # type: ignore[attr-defined]
        committed = conn.execute(  # type: ignore[attr-defined]
            select(quota_reservations).where(
                quota_reservations.c.id == reservation_id
            )
        ).one()
        return Reservation.from_row(committed)

    @_retryable_quota_write("commit")
    def commit(self, reservation_id: str) -> Reservation:
        with self._writer() as conn:
            return self._commit_locked(conn, self._get_locked(conn, reservation_id))

    @_retryable_quota_write("release")
    def mark_release_pending(self, reservation_id: str) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            if row.state in {"committed", "released", "release_pending"}:
                return Reservation.from_row(row)
            conn.execute(
                update(quota_reservations)
                .where(quota_reservations.c.id == reservation_id)
                .values(
                    state="release_pending",
                    version=quota_reservations.c.version + 1,
                    updated_at=datetime.now(UTC),
                )
            )
            self._recompute(conn, row.project_id)
            result = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            return Reservation.from_row(result)

    @_retryable_quota_write("reconcile")
    def reconcile_present(
        self,
        reservation_id: str,
        *,
        expected_version: int | None = None,
        expected_claim_token: str | None = None,
        claim_checked_at: datetime | None = None,
    ) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            self._check_reconciliation_claim(
                conn,
                reservation_id,
                expected_claim_token,
                expected_version,
                claim_checked_at,
            )
            self._check_reconciliation_version(row, expected_version)
            if row.state == "released":
                result = Reservation.from_row(row)
                self._consume_reconciliation_claim(
                    conn, reservation_id, expected_claim_token
                )
                return result
            if row.state == "pending":
                result = self._commit_locked(conn, row)
                self._consume_reconciliation_claim(
                    conn, reservation_id, expected_claim_token
                )
                return result
            now = datetime.now(UTC)
            if row.state == "committed":
                conn.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == reservation_id)
                    .values(
                        version=quota_reservations.c.version + 1,
                        updated_at=now,
                    )
                )
                conn.execute(
                    update(quota_manifests)
                    .where(quota_manifests.c.reservation_id == reservation_id)
                    .values(state="committed", updated_at=now)
                )
            elif row.state == "release_pending":
                committed_manifest = conn.execute(
                    select(quota_manifests).where(
                        quota_manifests.c.reservation_id == reservation_id,
                        quota_manifests.c.state == "committed",
                    )
                ).first()
                next_state = "committed" if committed_manifest is not None else "pending"
                conn.execute(
                    update(quota_reservations)
                    .where(quota_reservations.c.id == reservation_id)
                    .values(
                        state=next_state,
                        version=quota_reservations.c.version + 1,
                        delta_bytes=0 if next_state == "committed" else row.delta_bytes,
                        updated_at=now,
                    )
                )
                current = conn.execute(
                    select(quota_reservations).where(
                        quota_reservations.c.id == reservation_id
                    )
                ).one()
                if next_state == "pending":
                    result = self._commit_locked(conn, current)
                    self._consume_reconciliation_claim(
                        conn, reservation_id, expected_claim_token
                    )
                    return result
                conn.execute(
                    update(quota_manifests)
                    .where(quota_manifests.c.reservation_id == reservation_id)
                    .values(state="committed", updated_at=now)
                )
                self._recompute(conn, row.project_id)
            else:
                raise ValueError("reservation cannot be reconciled as present")
            result = conn.execute(
                select(quota_reservations).where(
                    quota_reservations.c.id == reservation_id
                )
            ).one()
            reconciled = Reservation.from_row(result)
            self._consume_reconciliation_claim(
                conn, reservation_id, expected_claim_token
            )
            return reconciled

    @_retryable_quota_write("reconcile")
    def reconcile_absent(
        self,
        reservation_id: str,
        *,
        expected_version: int | None = None,
        expected_claim_token: str | None = None,
        claim_checked_at: datetime | None = None,
    ) -> Reservation:
        with self._writer() as conn:
            row = self._get_locked(conn, reservation_id)
            self._check_reconciliation_claim(
                conn,
                reservation_id,
                expected_claim_token,
                expected_version,
                claim_checked_at,
            )
            self._check_reconciliation_version(row, expected_version)
            if row.state == "released":
                result = Reservation.from_row(row)
                self._consume_reconciliation_claim(
                    conn, reservation_id, expected_claim_token
                )
                return result
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
                .values(
                    state="released",
                    version=quota_reservations.c.version + 1,
                    delta_bytes=0,
                    updated_at=now,
                )
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
            reconciled = Reservation.from_row(result)
            self._consume_reconciliation_claim(
                conn, reservation_id, expected_claim_token
            )
            return reconciled

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
