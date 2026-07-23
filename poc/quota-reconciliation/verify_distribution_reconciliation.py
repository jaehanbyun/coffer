from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config

from coffer.db import RepositoryStore
from coffer.quota import Descriptor, QuotaStore
from coffer.quota_reconciliation import (
    HTTPDistributionManifestProbe,
    QuotaReconciler,
    RepositoryStoreResolver,
)


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"


def digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


class RegistryClient:
    def __init__(self, origin: str) -> None:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("fixture registry must be one HTTP origin")
        self._host = parsed.hostname
        self._port = parsed.port or 80

    def _request(
        self,
        method: str,
        target: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str]]:
        connection = http.client.HTTPConnection(self._host, self._port, timeout=5)
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            response.read()
            return response.status, {
                name.lower(): value for name, value in response.getheaders()
            }
        finally:
            connection.close()

    def upload_blob(self, repository: str, body: bytes) -> str:
        blob_digest = digest(body)
        status, headers = self._request(
            "POST",
            f"/v2/{repository}/blobs/uploads/",
            headers={"Content-Length": "0"},
        )
        if status != 202 or "location" not in headers:
            raise AssertionError(f"blob upload start failed with HTTP {status}")
        location = urlsplit(headers["location"])
        target = location.path
        if location.query:
            target = f"{target}?{location.query}&digest={blob_digest}"
        else:
            target = f"{target}?digest={blob_digest}"
        status, _ = self._request(
            "PUT",
            target,
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "Content-Type": "application/octet-stream",
            },
        )
        if status != 201:
            raise AssertionError(f"blob upload finish failed with HTTP {status}")
        return blob_digest

    def put_manifest(self, repository: str, body: bytes) -> str:
        status, headers = self._request(
            "PUT",
            f"/v2/{repository}/manifests/fixture",
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "Content-Type": MEDIA_TYPE,
            },
        )
        manifest_digest = digest(body)
        if status != 201 or headers.get("docker-content-digest") != manifest_digest:
            raise AssertionError(f"manifest publication failed with HTTP {status}")
        return manifest_digest

    def delete_manifest(self, repository: str, manifest_digest: str) -> None:
        status, _ = self._request(
            "DELETE", f"/v2/{repository}/manifests/{manifest_digest}"
        )
        if status != 202:
            raise AssertionError(f"manifest deletion failed with HTTP {status}")


def migration_config(repository_root: Path, database_url: str) -> Config:
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-origin", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    args = parser.parse_args()

    database_url = f"sqlite:///{args.database}"
    command.upgrade(migration_config(args.repository_root, database_url), "head")
    repositories = RepositoryStore(database_url)
    quotas = QuotaStore(database_url)
    quotas.set_limit(PROJECT_ID, 10_000)
    records = {
        name: repositories.create(PROJECT_ID, name)
        for name in ("present", "absent", "deleted")
    }
    canonical = {
        name: f"p/{PROJECT_ID}/{name}" for name in records
    }

    client = RegistryClient(args.registry_origin)
    config_body = b'{"architecture":"amd64","os":"linux"}'
    config_digest = digest(config_body)
    manifest_body = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": MEDIA_TYPE,
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": config_digest,
                "size": len(config_body),
            },
            "layers": [],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    manifest_digest = digest(manifest_body)
    descriptors = (
        Descriptor(manifest_digest, len(manifest_body)),
        Descriptor(config_digest, len(config_body)),
    )

    for name in ("present", "deleted"):
        assert client.upload_blob(canonical[name], config_body) == config_digest
        assert client.put_manifest(canonical[name], manifest_body) == manifest_digest

    reservations = {
        name: quotas.reserve(
            project_id=PROJECT_ID,
            repository_id=records[name].id,
            manifest_digest=manifest_digest,
            request_id=f"req-{name}",
            descriptors=descriptors,
        )
        for name in ("deleted", "present", "absent")
    }
    quotas.commit(reservations["deleted"].id)
    expected_usage = sum(descriptor.size for descriptor in descriptors)
    assert quotas.usage(PROJECT_ID).used_bytes == expected_usage
    client.delete_manifest(canonical["deleted"], manifest_digest)

    reconciler = QuotaReconciler(
        quotas,
        RepositoryStoreResolver(repositories),
        HTTPDistributionManifestProbe(args.registry_origin, timeout_seconds=2),
        worker_id="fixture-worker",
        stale_after=timedelta(0),
        batch_limit=10,
    )
    runs = []
    for _attempt in range(3):
        runs.append(reconciler.run_once(now=datetime.now(UTC)))

    assert quotas.get_reservation(reservations["deleted"].id).state == "released"
    assert quotas.get_reservation(reservations["present"].id).state == "committed"
    assert quotas.get_reservation(reservations["absent"].id).state == "released"
    assert quotas.usage(PROJECT_ID).used_bytes == expected_usage
    assert sum(run.stale for run in runs) == 0
    assert sum(run.indeterminate for run in runs) == 0

    client.delete_manifest(canonical["present"], manifest_digest)
    deleted_present = reconciler.run_once(now=datetime.now(UTC))
    assert deleted_present.absent == 1
    assert quotas.get_reservation(reservations["present"].id).state == "released"
    usage = quotas.usage(PROJECT_ID)
    assert usage.used_bytes == 0
    assert usage.reserved_bytes == 0
    print(
        json.dumps(
            {
                "absent_pending_released": True,
                "claim_fencing_enabled": True,
                "committed_delete_refunded": True,
                "exact_present_committed": True,
                "final_reserved_bytes": usage.reserved_bytes,
                "final_used_bytes": usage.used_bytes,
                "shared_descriptor_preserved_until_last_reference": True,
                "unchanged_reservation_versions_stable": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
