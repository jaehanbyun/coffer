from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Iterator

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    and_,
    create_engine,
    delete,
    exists,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from coffer.quota import MAX_LOGICAL_BYTES, SHA256_DIGEST
from coffer.schema import SchemaNotReady, require_current_schema


MAX_ARTIFACT_PAGE = 100
MAX_TAGS_PER_ARTIFACT = 100
MAX_ARTIFACT_QUERY_LENGTH = 128
MAX_TAG_CLAIM_SECONDS = 3600
TAG_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
ARTIFACT_KINDS = frozenset({"artifact", "image", "image_index"})

artifact_metadata = MetaData()
registry_artifacts = Table(
    "registry_artifacts",
    artifact_metadata,
    Column("project_id", String(64), nullable=False),
    Column("repository_id", String(36), nullable=False),
    Column("digest", String(71), nullable=False),
    Column("media_type", String(255), nullable=False),
    Column("artifact_type", String(255), nullable=True),
    Column("kind", String(16), nullable=False),
    Column("size_bytes", BigInteger, nullable=False),
    Column("pushed_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "project_id",
        "repository_id",
        "digest",
        name="pk_registry_artifacts",
    ),
    CheckConstraint(
        "kind IN ('artifact', 'image', 'image_index')",
        name="ck_registry_artifact_kind",
    ),
    CheckConstraint(
        "size_bytes >= 0",
        name="ck_registry_artifact_size",
    ),
)
Index(
    "ix_registry_artifacts_repository_time",
    registry_artifacts.c.project_id,
    registry_artifacts.c.repository_id,
    registry_artifacts.c.pushed_at,
    registry_artifacts.c.digest,
)
registry_tags = Table(
    "registry_tags",
    artifact_metadata,
    Column("project_id", String(64), nullable=False),
    Column("repository_id", String(36), nullable=False),
    Column("name", String(128), nullable=False),
    Column("digest", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "project_id",
        "repository_id",
        "name",
        name="pk_registry_tags",
    ),
)
Index(
    "ix_registry_tags_repository_digest",
    registry_tags.c.project_id,
    registry_tags.c.repository_id,
    registry_tags.c.digest,
    registry_tags.c.name,
)
registry_tag_claims = Table(
    "registry_tag_claims",
    artifact_metadata,
    Column("project_id", String(64), nullable=False),
    Column("repository_id", String(36), nullable=False),
    Column("name", String(128), nullable=False),
    Column("digest", String(71), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "project_id",
        "repository_id",
        "name",
        name="pk_registry_tag_claims",
    ),
    CheckConstraint(
        "expires_at > claimed_at",
        name="ck_registry_tag_claim_window",
    ),
)
Index(
    "ix_registry_tag_claims_expires",
    registry_tag_claims.c.expires_at,
    registry_tag_claims.c.project_id,
    registry_tag_claims.c.repository_id,
)


class ArtifactSchemaNotReady(SchemaNotReady):
    pass


class InvalidArtifactMarker(Exception):
    pass


class TagImmutable(Exception):
    pass


class TagClaimConflict(Exception):
    pass


class TagClaimNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class TagClaim:
    project_id: str
    repository_id: str
    name: str
    digest: str
    request_id: str
    claimed_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class Artifact:
    project_id: str
    repository_id: str
    digest: str
    media_type: str
    artifact_type: str | None
    kind: str
    size_bytes: int
    pushed_at: datetime
    updated_at: datetime
    tags: tuple[str, ...]
    tag_count: int
    tags_truncated: bool

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "repository_id": self.repository_id,
            "digest": self.digest,
            "media_type": self.media_type,
            "artifact_type": self.artifact_type,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "pushed_at": self._timestamp(self.pushed_at),
            "updated_at": self._timestamp(self.updated_at),
            "tags": list(self.tags),
            "tag_count": self.tag_count,
            "tags_truncated": self.tags_truncated,
        }


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    artifacts: tuple[Artifact, ...]
    next_marker: str | None


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_scope(project_id: str, repository_id: str) -> None:
    if (
        not isinstance(project_id, str)
        or not project_id
        or project_id.strip() != project_id
        or len(project_id) > 64
        or "\x00" in project_id
    ):
        raise ValueError("artifact project scope is invalid")
    if (
        not isinstance(repository_id, str)
        or not repository_id
        or repository_id.strip() != repository_id
        or len(repository_id) > 36
        or "\x00" in repository_id
    ):
        raise ValueError("artifact repository scope is invalid")


def _validate_digest(digest: str) -> None:
    if not isinstance(digest, str) or SHA256_DIGEST.fullmatch(digest) is None:
        raise ValueError("artifact digest must be canonical sha256")


def _validate_tag(tag: str) -> None:
    if not isinstance(tag, str) or TAG_NAME.fullmatch(tag) is None:
        raise ValueError("artifact tag is invalid")


class ArtifactStore:
    def __init__(self, connection: str, *, bootstrap_schema: bool = False) -> None:
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
            artifact_metadata.create_all(self._engine)
        else:
            require_current_schema(
                self._engine,
                expected_tables=artifact_metadata.tables,
                component="artifact",
                error_type=ArtifactSchemaNotReady,
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

    def claim_tag(
        self,
        *,
        project_id: str,
        repository_id: str,
        reference: str,
        digest: str,
        request_id: str,
        immutable: bool,
        claimed_at: datetime | None = None,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> TagClaim | None:
        _validate_scope(project_id, repository_id)
        _validate_digest(digest)
        if reference == digest:
            return None
        _validate_tag(reference)
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or "\x00" in request_id
        ):
            raise ValueError("artifact tag claim request is invalid")
        if not isinstance(immutable, bool):
            raise ValueError("artifact tag immutability must be boolean")
        claimed_at = _aware(claimed_at or datetime.now(UTC))
        lease_seconds = lease_for.total_seconds()
        if not 0 < lease_seconds <= MAX_TAG_CLAIM_SECONDS:
            raise ValueError("artifact tag claim lease is invalid")
        expires_at = claimed_at + lease_for

        with self._writer() as connection:
            existing_tag = connection.execute(
                select(registry_tags)
                .where(
                    registry_tags.c.project_id == project_id,
                    registry_tags.c.repository_id == repository_id,
                    registry_tags.c.name == reference,
                )
                .with_for_update()
            ).first()
            if (
                immutable
                and existing_tag is not None
                and existing_tag.digest != digest
            ):
                raise TagImmutable(reference)

            existing_claim = connection.execute(
                select(registry_tag_claims)
                .where(
                    registry_tag_claims.c.project_id == project_id,
                    registry_tag_claims.c.repository_id == repository_id,
                    registry_tag_claims.c.name == reference,
                )
                .with_for_update()
            ).first()
            if existing_claim is not None:
                existing_expires = _aware(existing_claim.expires_at)
                if existing_expires <= claimed_at:
                    connection.execute(
                        delete(registry_tag_claims).where(
                            registry_tag_claims.c.project_id == project_id,
                            registry_tag_claims.c.repository_id == repository_id,
                            registry_tag_claims.c.name == reference,
                        )
                    )
                    existing_claim = None
                elif existing_claim.digest != digest:
                    raise TagClaimConflict(reference)

            values = {
                "digest": digest,
                "request_id": request_id,
                "claimed_at": claimed_at,
                "expires_at": expires_at,
            }
            if existing_claim is None:
                connection.execute(
                    insert(registry_tag_claims).values(
                        project_id=project_id,
                        repository_id=repository_id,
                        name=reference,
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(registry_tag_claims)
                    .where(
                        registry_tag_claims.c.project_id == project_id,
                        registry_tag_claims.c.repository_id == repository_id,
                        registry_tag_claims.c.name == reference,
                    )
                    .values(**values)
                )
        return TagClaim(
            project_id=project_id,
            repository_id=repository_id,
            name=reference,
            digest=digest,
            request_id=request_id,
            claimed_at=claimed_at,
            expires_at=expires_at,
        )

    def release_tag_claim(self, claim: TagClaim | None) -> bool:
        if claim is None:
            return False
        with self._writer() as connection:
            result = connection.execute(
                delete(registry_tag_claims).where(
                    registry_tag_claims.c.project_id == claim.project_id,
                    registry_tag_claims.c.repository_id == claim.repository_id,
                    registry_tag_claims.c.name == claim.name,
                    registry_tag_claims.c.digest == claim.digest,
                    registry_tag_claims.c.request_id == claim.request_id,
                )
            )
        return result.rowcount == 1

    def commit_artifact(
        self,
        *,
        project_id: str,
        repository_id: str,
        digest: str,
        media_type: str,
        artifact_type: str | None,
        kind: str,
        size_bytes: int,
        claim: TagClaim | None,
        pushed_at: datetime | None = None,
    ) -> Artifact:
        _validate_scope(project_id, repository_id)
        _validate_digest(digest)
        if (
            not isinstance(media_type, str)
            or not media_type
            or len(media_type) > 255
        ):
            raise ValueError("artifact media type is invalid")
        if artifact_type is not None and (
            not isinstance(artifact_type, str)
            or not artifact_type
            or len(artifact_type) > 255
        ):
            raise ValueError("artifact type is invalid")
        if kind not in ARTIFACT_KINDS:
            raise ValueError("artifact kind is invalid")
        if (
            isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or not 0 <= size_bytes <= MAX_LOGICAL_BYTES
        ):
            raise ValueError("artifact size is invalid")
        pushed_at = _aware(pushed_at or datetime.now(UTC))

        with self._writer() as connection:
            if claim is not None:
                if (
                    claim.project_id != project_id
                    or claim.repository_id != repository_id
                    or claim.digest != digest
                ):
                    raise ValueError("artifact tag claim scope does not match")
                current_claim = connection.execute(
                    select(registry_tag_claims)
                    .where(
                        registry_tag_claims.c.project_id == claim.project_id,
                        registry_tag_claims.c.repository_id == claim.repository_id,
                        registry_tag_claims.c.name == claim.name,
                    )
                    .with_for_update()
                ).first()
                if (
                    current_claim is None
                    or current_claim.digest != claim.digest
                    or current_claim.request_id != claim.request_id
                ):
                    raise TagClaimNotFound(claim.name)

            existing_artifact = connection.execute(
                select(registry_artifacts).where(
                    registry_artifacts.c.project_id == project_id,
                    registry_artifacts.c.repository_id == repository_id,
                    registry_artifacts.c.digest == digest,
                )
            ).first()
            values = {
                "media_type": media_type,
                "artifact_type": artifact_type,
                "kind": kind,
                "size_bytes": size_bytes,
                "pushed_at": pushed_at,
                "updated_at": pushed_at,
            }
            if existing_artifact is None:
                connection.execute(
                    insert(registry_artifacts).values(
                        project_id=project_id,
                        repository_id=repository_id,
                        digest=digest,
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(registry_artifacts)
                    .where(
                        registry_artifacts.c.project_id == project_id,
                        registry_artifacts.c.repository_id == repository_id,
                        registry_artifacts.c.digest == digest,
                    )
                    .values(**values)
                )

            if claim is not None:
                existing_tag = connection.execute(
                    select(registry_tags).where(
                        registry_tags.c.project_id == project_id,
                        registry_tags.c.repository_id == repository_id,
                        registry_tags.c.name == claim.name,
                    )
                ).first()
                tag_values = {
                    "digest": digest,
                    "updated_at": pushed_at,
                }
                if existing_tag is None:
                    connection.execute(
                        insert(registry_tags).values(
                            project_id=project_id,
                            repository_id=repository_id,
                            name=claim.name,
                            created_at=pushed_at,
                            **tag_values,
                        )
                    )
                else:
                    connection.execute(
                        update(registry_tags)
                        .where(
                            registry_tags.c.project_id == project_id,
                            registry_tags.c.repository_id == repository_id,
                            registry_tags.c.name == claim.name,
                        )
                        .values(**tag_values)
                    )
                connection.execute(
                    delete(registry_tag_claims).where(
                        registry_tag_claims.c.project_id == claim.project_id,
                        registry_tag_claims.c.repository_id == claim.repository_id,
                        registry_tag_claims.c.name == claim.name,
                        registry_tag_claims.c.digest == claim.digest,
                        registry_tag_claims.c.request_id == claim.request_id,
                    )
                )
        artifact = self.get(project_id, repository_id, digest)
        if artifact is None:
            raise RuntimeError("committed artifact projection is unavailable")
        return artifact

    @staticmethod
    def _query_condition(query: str | None):
        if query is None:
            return None
        if (
            not isinstance(query, str)
            or not query
            or query.strip() != query
            or len(query) > MAX_ARTIFACT_QUERY_LENGTH
            or "\x00" in query
        ):
            raise ValueError("artifact query is invalid")
        return or_(
            registry_artifacts.c.digest.startswith(query, autoescape=True),
            exists(
                select(registry_tags.c.name).where(
                    registry_tags.c.project_id
                    == registry_artifacts.c.project_id,
                    registry_tags.c.repository_id
                    == registry_artifacts.c.repository_id,
                    registry_tags.c.digest == registry_artifacts.c.digest,
                    registry_tags.c.name.contains(query, autoescape=True),
                )
            ),
        )

    def _decorate(
        self,
        connection: Connection,
        rows: tuple[object, ...],
    ) -> tuple[Artifact, ...]:
        if not rows:
            return ()
        project_id = rows[0].project_id  # type: ignore[attr-defined]
        repository_id = rows[0].repository_id  # type: ignore[attr-defined]
        digests = tuple(row.digest for row in rows)  # type: ignore[attr-defined]
        counts = {
            row.digest: int(row.tag_count)
            for row in connection.execute(
                select(
                    registry_tags.c.digest,
                    func.count().label("tag_count"),
                )
                .where(
                    registry_tags.c.project_id == project_id,
                    registry_tags.c.repository_id == repository_id,
                    registry_tags.c.digest.in_(digests),
                )
                .group_by(registry_tags.c.digest)
            )
        }
        ranked = (
            select(
                registry_tags.c.digest,
                registry_tags.c.name,
                func.row_number()
                .over(
                    partition_by=registry_tags.c.digest,
                    order_by=registry_tags.c.name,
                )
                .label("position"),
            )
            .where(
                registry_tags.c.project_id == project_id,
                registry_tags.c.repository_id == repository_id,
                registry_tags.c.digest.in_(digests),
            )
            .subquery()
        )
        tags: dict[str, list[str]] = {digest: [] for digest in digests}
        for row in connection.execute(
            select(ranked.c.digest, ranked.c.name)
            .where(ranked.c.position <= MAX_TAGS_PER_ARTIFACT)
            .order_by(ranked.c.digest, ranked.c.name)
        ):
            tags[row.digest].append(row.name)

        return tuple(
            Artifact(
                project_id=row.project_id,  # type: ignore[attr-defined]
                repository_id=row.repository_id,  # type: ignore[attr-defined]
                digest=row.digest,  # type: ignore[attr-defined]
                media_type=row.media_type,  # type: ignore[attr-defined]
                artifact_type=row.artifact_type,  # type: ignore[attr-defined]
                kind=row.kind,  # type: ignore[attr-defined]
                size_bytes=int(row.size_bytes),  # type: ignore[attr-defined]
                pushed_at=_aware(row.pushed_at),  # type: ignore[attr-defined]
                updated_at=_aware(row.updated_at),  # type: ignore[attr-defined]
                tags=tuple(tags[row.digest]),  # type: ignore[attr-defined]
                tag_count=counts.get(row.digest, 0),  # type: ignore[attr-defined]
                tags_truncated=(
                    counts.get(row.digest, 0) > MAX_TAGS_PER_ARTIFACT  # type: ignore[attr-defined]
                ),
            )
            for row in rows
        )

    def list_page(
        self,
        project_id: str,
        repository_id: str,
        *,
        limit: int,
        marker: str | None = None,
        query: str | None = None,
    ) -> ArtifactPage:
        _validate_scope(project_id, repository_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_ARTIFACT_PAGE
        ):
            raise ValueError("artifact page limit must be between 1 and 100")
        if marker is not None:
            _validate_digest(marker)
        query_condition = self._query_condition(query)

        with self._reader() as connection:
            conditions = [
                registry_artifacts.c.project_id == project_id,
                registry_artifacts.c.repository_id == repository_id,
            ]
            if query_condition is not None:
                conditions.append(query_condition)
            statement = select(registry_artifacts).where(*conditions)
            if marker is not None:
                marker_row = connection.execute(
                    select(registry_artifacts)
                    .where(*conditions)
                    .where(registry_artifacts.c.digest == marker)
                ).first()
                if marker_row is None:
                    raise InvalidArtifactMarker()
                statement = statement.where(
                    or_(
                        registry_artifacts.c.pushed_at < marker_row.pushed_at,
                        and_(
                            registry_artifacts.c.pushed_at
                            == marker_row.pushed_at,
                            registry_artifacts.c.digest > marker,
                        ),
                    )
                )
            rows = tuple(
                connection.execute(
                    statement.order_by(
                        registry_artifacts.c.pushed_at.desc(),
                        registry_artifacts.c.digest,
                    ).limit(limit + 1)
                )
            )
            visible = rows[:limit]
            artifacts = self._decorate(connection, visible)
        return ArtifactPage(
            artifacts=artifacts,
            next_marker=artifacts[-1].digest if len(rows) > limit else None,
        )

    def get(
        self,
        project_id: str,
        repository_id: str,
        digest: str,
    ) -> Artifact | None:
        _validate_scope(project_id, repository_id)
        _validate_digest(digest)
        with self._reader() as connection:
            row = connection.execute(
                select(registry_artifacts).where(
                    registry_artifacts.c.project_id == project_id,
                    registry_artifacts.c.repository_id == repository_id,
                    registry_artifacts.c.digest == digest,
                )
            ).first()
            values = self._decorate(connection, (row,)) if row is not None else ()
        return values[0] if values else None

    def ping(self) -> None:
        with self._reader() as connection:
            connection.execute(select(func.count()).select_from(registry_artifacts))
