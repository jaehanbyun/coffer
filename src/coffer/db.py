from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import uuid

from oslo_context import context as oslo_context
from oslo_db import exception as db_exception
from oslo_db.sqlalchemy import enginefacade
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    insert,
    select,
    text,
)

from coffer.schema import SchemaNotReady, require_current_schema


metadata = MetaData()
repositories = Table(
    "repositories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("name", String(255), nullable=False),
    Column("immutable_tags", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("project_id", "name", name="uq_repository_project_name"),
)


class RepositoryAlreadyExists(Exception):
    pass


class RepositorySchemaNotReady(SchemaNotReady):
    pass


@dataclass(frozen=True, slots=True)
class Repository:
    id: str
    project_id: str
    name: str
    immutable_tags: bool
    created_at: datetime

    @classmethod
    def from_row(cls, row: object) -> "Repository":
        mapping = row._mapping  # type: ignore[attr-defined]
        return cls(
            id=mapping["id"],
            project_id=mapping["project_id"],
            name=mapping["name"],
            immutable_tags=mapping["immutable_tags"],
            created_at=mapping["created_at"],
        )

    def to_dict(self) -> dict[str, object]:
        created_at = self.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "immutable_tags": self.immutable_tags,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }


class RepositoryStore:
    def __init__(self, connection: str, *, bootstrap_schema: bool = False) -> None:
        self._transaction = enginefacade.transaction_context()
        self._transaction.configure(connection=connection)
        engine = self._transaction.writer.get_engine()
        if bootstrap_schema:
            metadata.create_all(engine)
        else:
            require_current_schema(
                engine,
                expected_tables=metadata.tables,
                component="repository",
                error_type=RepositorySchemaNotReady,
            )

    @staticmethod
    def _context() -> oslo_context.RequestContext:
        return oslo_context.RequestContext()

    def create(
        self, project_id: str, name: str, *, immutable_tags: bool = False
    ) -> Repository:
        repository_id = str(uuid.uuid4())
        created_at = datetime.now(UTC)
        statement = insert(repositories).values(
            id=repository_id,
            project_id=project_id,
            name=name,
            immutable_tags=immutable_tags,
            created_at=created_at,
        )
        try:
            with self._transaction.writer.connection.using(self._context()) as conn:
                conn.execute(statement)
        except db_exception.DBDuplicateEntry as exc:
            raise RepositoryAlreadyExists(name) from exc
        return Repository(
            id=repository_id,
            project_id=project_id,
            name=name,
            immutable_tags=immutable_tags,
            created_at=created_at,
        )

    def list(self, project_id: str) -> list[Repository]:
        statement = (
            select(repositories)
            .where(repositories.c.project_id == project_id)
            .order_by(repositories.c.name)
        )
        with self._transaction.reader.connection.using(self._context()) as conn:
            return [Repository.from_row(row) for row in conn.execute(statement)]

    def get(self, project_id: str, repository_id: str) -> Repository | None:
        statement = select(repositories).where(
            repositories.c.id == repository_id,
            repositories.c.project_id == project_id,
        )
        with self._transaction.reader.connection.using(self._context()) as conn:
            row = conn.execute(statement).first()
        return Repository.from_row(row) if row is not None else None

    def get_by_name(self, project_id: str, name: str) -> Repository | None:
        statement = select(repositories).where(
            repositories.c.project_id == project_id,
            repositories.c.name == name,
        )
        with self._transaction.reader.connection.using(self._context()) as conn:
            row = conn.execute(statement).first()
        return Repository.from_row(row) if row is not None else None

    def ping(self) -> None:
        with self._transaction.reader.connection.using(self._context()) as conn:
            conn.execute(text("SELECT 1"))
