from __future__ import annotations

import argparse
import hashlib
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config

from coffer.db import RepositoryStore
from coffer.inventory import AUTHORITY_SCHEMA
from coffer.quota import OCI_IMAGE_INDEX, OCI_IMAGE_MANIFEST


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"


def digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


class RegistryClient:
    def __init__(self, origin: str) -> None:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("fixture registry must be one HTTP origin")
        self._host = parsed.hostname
        self._port = parsed.port or 80

    def request(
        self,
        method: str,
        target: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(self._host, self._port, timeout=5)
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            response_body = response.read()
            return (
                response.status,
                {name.lower(): value for name, value in response.getheaders()},
                response_body,
            )
        finally:
            connection.close()

    def upload_blob(self, repository: str, body: bytes) -> str:
        blob_digest = digest(body)
        status, headers, _ = self.request(
            "POST",
            f"/v2/{repository}/blobs/uploads/",
            headers={"Content-Length": "0"},
        )
        if status != 202 or "location" not in headers:
            raise AssertionError(f"blob upload start failed with HTTP {status}")
        location = urlsplit(headers["location"])
        separator = "&" if location.query else "?"
        target = location.path
        if location.query:
            target = f"{target}?{location.query}"
        target = f"{target}{separator}digest={blob_digest}"
        status, _, _ = self.request(
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

    def put_manifest(
        self, repository: str, reference: str, body: bytes, media_type: str
    ) -> str:
        status, headers, _ = self.request(
            "PUT",
            f"/v2/{repository}/manifests/{reference}",
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "Content-Type": media_type,
            },
        )
        manifest_digest = digest(body)
        if status != 201 or headers.get("docker-content-digest") != manifest_digest:
            raise AssertionError(f"manifest publication failed with HTTP {status}")
        return manifest_digest


def migration_config(repository_root: Path, database_url: str) -> Config:
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(repository_root / "src/coffer/migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-origin", required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--work-directory", type=Path, required=True)
    args = parser.parse_args()

    database_path = args.work_directory / "control.sqlite"
    database_url = f"sqlite:///{database_path}"
    command.upgrade(migration_config(args.repository_root, database_url), "head")
    repository = RepositoryStore(database_url).create(PROJECT_ID, "inventory")
    canonical_name = f"p/{PROJECT_ID}/{repository.name}"

    client = RegistryClient(args.registry_origin)
    config_body = b'{"architecture":"amd64","os":"linux"}'
    layer_body = b"coffer-existing-content-inventory-layer"
    config_digest = client.upload_blob(canonical_name, config_body)
    layer_digest = client.upload_blob(canonical_name, layer_body)
    child_body = json.dumps(
        {
            "config": {
                "digest": config_digest,
                "mediaType": CONFIG_MEDIA_TYPE,
                "size": len(config_body),
            },
            "layers": [
                {
                    "digest": layer_digest,
                    "mediaType": LAYER_MEDIA_TYPE,
                    "size": len(layer_body),
                }
            ],
            "mediaType": OCI_IMAGE_MANIFEST,
            "schemaVersion": 2,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    child_digest = client.put_manifest(
        canonical_name, "tagged", child_body, OCI_IMAGE_MANIFEST
    )
    index_body = json.dumps(
        {
            "manifests": [
                {
                    "digest": child_digest,
                    "mediaType": OCI_IMAGE_MANIFEST,
                    "platform": {"architecture": "amd64", "os": "linux"},
                    "size": len(child_body),
                }
            ],
            "mediaType": OCI_IMAGE_INDEX,
            "schemaVersion": 2,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    index_digest = digest(index_body)
    assert (
        client.put_manifest(canonical_name, index_digest, index_body, OCI_IMAGE_INDEX)
        == index_digest
    )

    status, _, tag_body = client.request(
        "GET", f"/v2/{canonical_name}/tags/list?n=1"
    )
    tags = json.loads(tag_body)
    assert status == 200 and tags == {"name": canonical_name, "tags": ["tagged"]}
    status, headers, _ = client.request(
        "HEAD", f"/v2/{canonical_name}/manifests/{index_digest}"
    )
    assert status == 200 and headers.get("docker-content-digest") == index_digest

    write_json(
        args.work_directory / "authority.json",
        {
            "repositories": [
                {
                    "id": repository.id,
                    "name": repository.name,
                    "project_id": PROJECT_ID,
                }
            ],
            "schema": AUTHORITY_SCHEMA,
        },
    )
    write_json(
        args.work_directory / "expected.json",
        {
            "canonical_name": canonical_name,
            "child_digest": child_digest,
            "config_digest": config_digest,
            "index_digest": index_digest,
            "layer_digest": layer_digest,
            "logical_bytes": (
                len(config_body) + len(layer_body) + len(child_body) + len(index_body)
            ),
            "repository_id": repository.id,
        },
    )


if __name__ == "__main__":
    main()
