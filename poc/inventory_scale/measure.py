from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import gc
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import tracemalloc
from typing import Callable, TypeVar
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine

from coffer.db import repositories as repository_table
from coffer.inventory import (
    INVENTORY_SCHEMA,
    PINNED_DISTRIBUTION_VERSION,
    PINNED_ENUMERATOR,
)
from coffer.live_inventory_verification import (
    LiveRepositoryTarget,
    verify_live_inventory,
)
from coffer.quota import (
    OCI_IMAGE_MANIFEST,
    QuotaStore,
    project_quotas,
)
from coffer.quota_import import (
    InventoryArtifact,
    import_inventory,
    parse_inventory_artifact,
)
from coffer.quota_import_verification import verify_inventory_import_snapshot
from coffer.quota_reconciliation import ManifestPresence, ProbeObservation


ROOT = Path(__file__).resolve().parents[2]
SCALE_SCHEMA = "coffer.inventory-scale/v1"
MAX_SYNTHETIC_MANIFESTS = 50_000
SYNTHETIC_TIME = datetime(2026, 7, 23, tzinfo=UTC)
SYNTHETIC_NAMESPACE = uuid.UUID("8606555c-72ab-5ec5-9f82-957a0af860c7")
CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"
PROFILE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True, slots=True)
class ScaleProfile:
    name: str
    project_count: int
    repositories_per_project: int
    manifests_per_repository: int

    def __post_init__(self) -> None:
        values = (
            self.project_count,
            self.repositories_per_project,
            self.manifests_per_repository,
        )
        invalid_name = (
            not isinstance(self.name, str)
            or PROFILE_NAME.fullmatch(self.name) is None
        )
        if invalid_name or any(
            type(value) is not int or value <= 0 for value in values
        ):
            raise ValueError("synthetic inventory scale profile is invalid")
        if self.manifest_count > MAX_SYNTHETIC_MANIFESTS:
            raise ValueError("synthetic inventory scale profile is too large")

    @property
    def repository_count(self) -> int:
        return self.project_count * self.repositories_per_project

    @property
    def manifest_count(self) -> int:
        return self.repository_count * self.manifests_per_repository

    @property
    def descriptor_count(self) -> int:
        return self.manifest_count * 3


PROFILES = {
    profile.name: profile
    for profile in (
        ScaleProfile("manifest-100", 2, 5, 10),
        ScaleProfile("manifest-1000", 5, 10, 20),
        ScaleProfile("manifest-5000", 10, 20, 25),
    )
}


@dataclass(frozen=True, slots=True)
class SyntheticRepositoryAuthority:
    project_id: str
    repository_id: str
    name: str


@dataclass(frozen=True, slots=True)
class SyntheticInventoryDocument:
    value: dict[str, object]
    payload: bytes
    artifact_digest: str
    authorities: tuple[SyntheticRepositoryAuthority, ...]


@dataclass(frozen=True, slots=True)
class PhaseMeasurement:
    duration_seconds: float
    peak_traced_bytes: int
    sql_statement_count: int


class SyntheticAuthenticatedProbe:
    def __init__(self) -> None:
        self._prepared = False
        self.probe_count = 0

    def prepare(self, repositories: tuple[LiveRepositoryTarget, ...]) -> None:
        self._prepared = True

    def probe(
        self,
        *,
        repository_id: str,
        repository: str,
        digest: str,
    ) -> ProbeObservation:
        if not self._prepared:
            raise RuntimeError("synthetic probe was not prepared")
        self.probe_count += 1
        return ProbeObservation(ManifestPresence.PRESENT, 200)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _descriptor(digest: str, media_type: str, size: int) -> dict[str, object]:
    return {"digest": digest, "media_type": media_type, "size": size}


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def build_inventory_document(profile: ScaleProfile) -> SyntheticInventoryDocument:
    projects: list[dict[str, object]] = []
    repositories: list[dict[str, object]] = []
    authorities: list[SyntheticRepositoryAuthority] = []
    logical_bytes = 0

    for project_index in range(profile.project_count):
        project_id = str(
            uuid.uuid5(SYNTHETIC_NAMESPACE, f"project:{project_index}")
        )
        project_descriptors: dict[str, dict[str, object]] = {}
        for repository_index in range(profile.repositories_per_project):
            repository_id = str(
                uuid.uuid5(
                    SYNTHETIC_NAMESPACE,
                    f"repository:{project_index}:{repository_index}",
                )
            )
            repository_name = f"scale-{project_index}-{repository_index}"
            authorities.append(
                SyntheticRepositoryAuthority(
                    project_id,
                    repository_id,
                    repository_name,
                )
            )
            manifests: list[dict[str, object]] = []
            for manifest_index in range(profile.manifests_per_repository):
                prefix = (
                    f"{project_index}:{repository_index}:{manifest_index}"
                )
                manifest_digest = _digest(f"manifest:{prefix}")
                config_digest = _digest(f"config:{prefix}")
                layer_digest = _digest(f"layer:{prefix}")
                references = sorted(
                    (
                        _descriptor(config_digest, CONFIG_MEDIA_TYPE, 64),
                        _descriptor(layer_digest, LAYER_MEDIA_TYPE, 1024),
                    ),
                    key=lambda item: str(item["digest"]),
                )
                manifest = {
                    "digest": manifest_digest,
                    "media_type": OCI_IMAGE_MANIFEST,
                    "references": references,
                    "size": 512,
                }
                manifests.append(manifest)
                for descriptor in (
                    _descriptor(manifest_digest, OCI_IMAGE_MANIFEST, 512),
                    *references,
                ):
                    project_descriptors[str(descriptor["digest"])] = descriptor
            manifests.sort(key=lambda item: str(item["digest"]))
            repositories.append(
                {
                    "manifests": manifests,
                    "project_id": project_id,
                    "repository_id": repository_id,
                }
            )
        descriptors = [
            descriptor
            for _, descriptor in sorted(project_descriptors.items())
        ]
        project_logical_bytes = sum(
            int(descriptor["size"]) for descriptor in descriptors
        )
        logical_bytes += project_logical_bytes
        projects.append(
            {
                "descriptor_count": len(descriptors),
                "descriptors": descriptors,
                "logical_bytes": project_logical_bytes,
                "project_id": project_id,
            }
        )

    projects.sort(key=lambda item: str(item["project_id"]))
    repositories.sort(
        key=lambda item: (str(item["project_id"]), str(item["repository_id"]))
    )
    authorities.sort(key=lambda item: (item.project_id, item.repository_id))
    value: dict[str, object] = {
        "projects": projects,
        "repositories": repositories,
        "schema": INVENTORY_SCHEMA,
        "source": {
            "distribution_version": PINNED_DISTRIBUTION_VERSION,
            "enumerator": PINNED_ENUMERATOR,
            "snapshot_scans": 2,
        },
        "summary": {
            "descriptor_count": profile.descriptor_count,
            "logical_bytes": logical_bytes,
            "manifest_count": profile.manifest_count,
            "project_count": profile.project_count,
            "repository_count": profile.repository_count,
        },
    }
    payload = _canonical_bytes(value)
    artifact_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    return SyntheticInventoryDocument(
        value=value,
        payload=payload,
        artifact_digest=artifact_digest,
        authorities=tuple(authorities),
    )


ValueT = TypeVar("ValueT")


def _measure(function: Callable[[], ValueT]) -> tuple[ValueT, PhaseMeasurement]:
    sql_statement_count = 0

    def count_statement(
        _connection: object,
        _cursor: object,
        _statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal sql_statement_count
        sql_statement_count += 1

    gc.collect()
    event.listen(Engine, "before_cursor_execute", count_statement)
    tracemalloc.start()
    started = time.perf_counter()
    try:
        value = function()
        duration_seconds = time.perf_counter() - started
        _, peak_traced_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        event.remove(Engine, "before_cursor_execute", count_statement)
    return value, PhaseMeasurement(
        duration_seconds=round(duration_seconds, 6),
        peak_traced_bytes=peak_traced_bytes,
        sql_statement_count=sql_statement_count,
    )


def _migration_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _prepare_authority(
    database_url: str,
    document: SyntheticInventoryDocument,
    artifact: InventoryArtifact,
) -> QuotaStore:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(repository_table),
                [
                    {
                        "created_at": SYNTHETIC_TIME,
                        "id": authority.repository_id,
                        "immutable_tags": False,
                        "name": authority.name,
                        "project_id": authority.project_id,
                    }
                    for authority in document.authorities
                ],
            )
            connection.execute(
                insert(project_quotas),
                [
                    {
                        "limit_bytes": project.logical_bytes + 1,
                        "project_id": project.project_id,
                        "reserved_bytes": 0,
                        "updated_at": SYNTHETIC_TIME,
                        "used_bytes": 0,
                    }
                    for project in artifact.projects
                ],
            )
    finally:
        engine.dispose()
    return QuotaStore(database_url)


def measure_profile(
    profile: ScaleProfile,
    *,
    temporary_parent: Path | None = None,
) -> dict[str, object]:
    phases: dict[str, PhaseMeasurement] = {}
    document, phases["document_build"] = _measure(
        lambda: build_inventory_document(profile)
    )
    artifact, phases["inventory_parse"] = _measure(
        lambda: parse_inventory_artifact(
            document.value,
            artifact_digest=document.artifact_digest,
        )
    )

    store: QuotaStore | None = None
    with tempfile.TemporaryDirectory(
        prefix="coffer-inventory-scale-",
        dir=temporary_parent,
    ) as temporary_directory:
        database_url = f"sqlite:///{Path(temporary_directory) / 'scale.sqlite'}"
        _, phases["schema_migration"] = _measure(
            lambda: command.upgrade(_migration_config(database_url), "head")
        )
        store, phases["authority_prepare"] = _measure(
            lambda: _prepare_authority(database_url, document, artifact)
        )
        try:
            import_result, phases["ledger_import"] = _measure(
                lambda: import_inventory(
                    store,
                    artifact,
                    imported_at=SYNTHETIC_TIME,
                )
            )
            sql_snapshot, phases["sql_compare"] = _measure(
                lambda: verify_inventory_import_snapshot(store, artifact)
            )
            probe = SyntheticAuthenticatedProbe()
            live_result, phases["live_compare"] = _measure(
                lambda: verify_live_inventory(store, artifact, probe)
            )
        finally:
            store._engine.dispose()

    if (
        import_result.status != "imported"
        or sql_snapshot.result.status != "verified"
        or live_result.status != "verified"
        or probe.probe_count != profile.manifest_count
    ):
        raise RuntimeError("synthetic inventory scale result is inconsistent")

    return {
        "artifact_bytes": len(document.payload),
        "phases": {
            name: asdict(measurement) for name, measurement in phases.items()
        },
        "profile": {
            "descriptor_count": profile.descriptor_count,
            "manifest_count": profile.manifest_count,
            "name": profile.name,
            "project_count": profile.project_count,
            "repository_count": profile.repository_count,
        },
        "result": {
            "live_status": live_result.status,
            "probe_count": probe.probe_count,
            "sql_status": sql_snapshot.result.status,
        },
        "schema": SCALE_SCHEMA,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure deterministic disposable inventory scale profiles"
    )
    parser.add_argument(
        "--profile",
        choices=("all", *PROFILES),
        default="all",
    )
    args = parser.parse_args(argv)
    selected = PROFILES.values() if args.profile == "all" else (PROFILES[args.profile],)
    try:
        measurements = [measure_profile(profile) for profile in selected]
    except Exception:
        print("synthetic inventory scale measurement failed", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"measurements": measurements, "schema": SCALE_SCHEMA},
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
