from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


OCI_CONFIG = "application/vnd.oci.image.config.v1+json"
OCI_LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
ARTIFACT_TYPE = "application/vnd.openstack.coffer.fixture.v1"
PROJECT_A = "11111111-1111-4111-8111-111111111111"
PROJECT_B = "22222222-2222-4222-8222-222222222222"


def digest(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def descriptor(media_type: str, body: bytes) -> dict[str, object]:
    return {
        "digest": digest(body),
        "mediaType": media_type,
        "size": len(body),
    }


def write_private_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor_fd = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor_fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class RegistryClient:
    def __init__(self, origin: str) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("fixture registry must be one unauthenticated HTTP origin")
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
        connection = http.client.HTTPConnection(
            self._host,
            self._port,
            timeout=5,
        )
        try:
            connection.request(
                method,
                target,
                body=body,
                headers=headers or {},
            )
            response = connection.getresponse()
            response_body = response.read()
            return (
                response.status,
                {
                    name.lower(): value
                    for name, value in response.getheaders()
                },
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
            raise RuntimeError("fixture blob upload start failed")
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
            raise RuntimeError("fixture blob upload finish failed")
        return blob_digest

    def put_manifest(
        self,
        repository: str,
        reference: str,
        body: bytes,
        media_type: str,
    ) -> str:
        manifest_digest = digest(body)
        status, headers, _ = self.request(
            "PUT",
            f"/v2/{repository}/manifests/{reference}",
            body=body,
            headers={
                "Content-Length": str(len(body)),
                "Content-Type": media_type,
            },
        )
        if (
            status != 201
            or headers.get("docker-content-digest") != manifest_digest
        ):
            raise RuntimeError("fixture manifest publication failed")
        return manifest_digest

    def delete_manifest(self, repository: str, manifest_digest: str) -> None:
        status, _, _ = self.request(
            "DELETE",
            f"/v2/{repository}/manifests/{manifest_digest}",
        )
        if status != 202:
            raise RuntimeError("fixture manifest deletion failed")


def image_manifest(
    config_body: bytes,
    layer_bodies: list[bytes],
    *,
    subject: dict[str, object] | None = None,
    artifact_type: str | None = None,
) -> bytes:
    value: dict[str, object] = {
        "config": descriptor(OCI_CONFIG, config_body),
        "layers": [
            descriptor(OCI_LAYER, layer_body)
            for layer_body in layer_bodies
        ],
        "mediaType": OCI_MANIFEST,
        "schemaVersion": 2,
    }
    if subject is not None:
        value["subject"] = subject
    if artifact_type is not None:
        value["artifactType"] = artifact_type
    return canonical_json(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-origin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    client = RegistryClient(args.registry_origin)
    repositories = {
        "keep-a": f"p/{PROJECT_A}/keep-a",
        "keep-b": f"p/{PROJECT_B}/keep-b",
        "index": f"p/{PROJECT_A}/index",
        "digest-only": f"p/{PROJECT_A}/digest-only",
        "artifacts": f"p/{PROJECT_A}/artifacts",
        "deleted": f"p/{PROJECT_A}/deleted",
    }
    retained: set[str] = set()
    probes: list[dict[str, str]] = []

    shared_body = b"coffer-gc-shared-blob"
    private_a_body = b"coffer-gc-private-a"
    private_b_body = b"coffer-gc-private-b"
    config_a = canonical_json({"architecture": "amd64", "fixture": "keep-a"})
    config_b = canonical_json({"architecture": "arm64", "fixture": "keep-b"})
    for repository, config_body, private_body, tag in (
        (repositories["keep-a"], config_a, private_a_body, "stable"),
        (repositories["keep-b"], config_b, private_b_body, "stable"),
    ):
        for body in (config_body, shared_body, private_body):
            retained.add(client.upload_blob(repository, body))
        manifest = image_manifest(
            config_body,
            [shared_body, private_body],
        )
        manifest_digest = client.put_manifest(
            repository,
            tag,
            manifest,
            OCI_MANIFEST,
        )
        retained.add(manifest_digest)
        if repository == repositories["keep-a"]:
            probes.extend(
                [
                    {
                        "class": "shared-blob",
                        "digest": digest(shared_body),
                        "kind": "blob",
                        "reference": digest(shared_body),
                        "repository": repository,
                    },
                    {
                        "class": "private-blob",
                        "digest": digest(private_a_body),
                        "kind": "blob",
                        "reference": digest(private_a_body),
                        "repository": repository,
                    },
                    {
                        "class": "tagged-manifest",
                        "digest": manifest_digest,
                        "kind": "manifest",
                        "reference": tag,
                        "repository": repository,
                    },
                ]
            )

    index_config = canonical_json({"architecture": "amd64", "fixture": "index"})
    index_layer = b"coffer-gc-index-child"
    retained.update(
        {
            client.upload_blob(repositories["index"], index_config),
            client.upload_blob(repositories["index"], index_layer),
        }
    )
    child_manifest = image_manifest(index_config, [index_layer])
    child_digest = client.put_manifest(
        repositories["index"],
        digest(child_manifest),
        child_manifest,
        OCI_MANIFEST,
    )
    retained.add(child_digest)
    index_body = canonical_json(
        {
            "manifests": [
                {
                    **descriptor(OCI_MANIFEST, child_manifest),
                    "platform": {"architecture": "amd64", "os": "linux"},
                }
            ],
            "mediaType": OCI_INDEX,
            "schemaVersion": 2,
        }
    )
    index_digest = client.put_manifest(
        repositories["index"],
        "multi",
        index_body,
        OCI_INDEX,
    )
    retained.add(index_digest)
    probes.extend(
        [
            {
                "class": "index",
                "digest": index_digest,
                "kind": "manifest",
                "reference": "multi",
                "repository": repositories["index"],
            },
            {
                "class": "index-child",
                "digest": child_digest,
                "kind": "manifest",
                "reference": child_digest,
                "repository": repositories["index"],
            },
        ]
    )

    digest_config = canonical_json(
        {"architecture": "amd64", "fixture": "digest-only"}
    )
    digest_layer = b"coffer-gc-digest-only"
    retained.update(
        {
            client.upload_blob(repositories["digest-only"], digest_config),
            client.upload_blob(repositories["digest-only"], digest_layer),
        }
    )
    digest_manifest = image_manifest(digest_config, [digest_layer])
    digest_manifest_digest = client.put_manifest(
        repositories["digest-only"],
        digest(digest_manifest),
        digest_manifest,
        OCI_MANIFEST,
    )
    retained.add(digest_manifest_digest)
    probes.append(
        {
            "class": "digest-only-manifest",
            "digest": digest_manifest_digest,
            "kind": "manifest",
            "reference": digest_manifest_digest,
            "repository": repositories["digest-only"],
        }
    )

    subject_config = canonical_json(
        {"architecture": "amd64", "fixture": "subject"}
    )
    subject_layer = b"coffer-gc-subject"
    retained.update(
        {
            client.upload_blob(repositories["artifacts"], subject_config),
            client.upload_blob(repositories["artifacts"], subject_layer),
        }
    )
    subject_manifest = image_manifest(subject_config, [subject_layer])
    subject_digest = client.put_manifest(
        repositories["artifacts"],
        "subject",
        subject_manifest,
        OCI_MANIFEST,
    )
    retained.add(subject_digest)
    subject_descriptor = descriptor(OCI_MANIFEST, subject_manifest)
    artifact_config = canonical_json({"fixture": "referrer"})
    artifact_layer = b"coffer-gc-referrer"
    retained.update(
        {
            client.upload_blob(repositories["artifacts"], artifact_config),
            client.upload_blob(repositories["artifacts"], artifact_layer),
        }
    )
    artifact_manifest = image_manifest(
        artifact_config,
        [artifact_layer],
        subject=subject_descriptor,
        artifact_type=ARTIFACT_TYPE,
    )
    artifact_digest = client.put_manifest(
        repositories["artifacts"],
        digest(artifact_manifest),
        artifact_manifest,
        OCI_MANIFEST,
    )
    retained.add(artifact_digest)
    fallback_tag = f"sha256-{subject_digest.removeprefix('sha256:')}"
    fallback_body = canonical_json(
        {
            "manifests": [
                {
                    **descriptor(OCI_MANIFEST, artifact_manifest),
                    "artifactType": ARTIFACT_TYPE,
                }
            ],
            "mediaType": OCI_INDEX,
            "schemaVersion": 2,
        }
    )
    fallback_digest = client.put_manifest(
        repositories["artifacts"],
        fallback_tag,
        fallback_body,
        OCI_INDEX,
    )
    retained.add(fallback_digest)
    probes.extend(
        [
            {
                "class": "subject",
                "digest": subject_digest,
                "kind": "manifest",
                "reference": "subject",
                "repository": repositories["artifacts"],
            },
            {
                "class": "referrer",
                "digest": artifact_digest,
                "kind": "manifest",
                "reference": artifact_digest,
                "repository": repositories["artifacts"],
            },
            {
                "class": "referrers-index",
                "digest": fallback_digest,
                "kind": "manifest",
                "reference": fallback_tag,
                "repository": repositories["artifacts"],
            },
        ]
    )

    deleted_config = canonical_json(
        {"architecture": "amd64", "fixture": "deleted"}
    )
    deleted_layer = b"coffer-gc-explicitly-deleted"
    deleted_config_digest = client.upload_blob(
        repositories["deleted"],
        deleted_config,
    )
    deleted_layer_digest = client.upload_blob(
        repositories["deleted"],
        deleted_layer,
    )
    deleted_manifest = image_manifest(deleted_config, [deleted_layer])
    deleted_manifest_digest = client.put_manifest(
        repositories["deleted"],
        "delete-me",
        deleted_manifest,
        OCI_MANIFEST,
    )
    client.delete_manifest(
        repositories["deleted"],
        deleted_manifest_digest,
    )
    status, _, _ = client.request(
        "HEAD",
        f"/v2/{repositories['deleted']}/manifests/{deleted_manifest_digest}",
    )
    if status != 404:
        raise RuntimeError("explicitly deleted manifest remained readable")

    candidates = [
        {
            "digest": candidate_digest,
            "kind": "blob",
            "repository": None,
        }
        for candidate_digest in (
            deleted_config_digest,
            deleted_layer_digest,
            deleted_manifest_digest,
        )
    ]
    candidates.extend(
        {
            "digest": candidate_digest,
            "kind": "layer-link",
            "repository": repositories["deleted"],
        }
        for candidate_digest in (
            deleted_config_digest,
            deleted_layer_digest,
        )
    )
    if {probe["class"] for probe in probes} != {
        "shared-blob",
        "private-blob",
        "tagged-manifest",
        "index",
        "index-child",
        "digest-only-manifest",
        "subject",
        "referrer",
        "referrers-index",
    }:
        raise RuntimeError("survivor fixture classes are incomplete")
    write_private_json(
        args.output,
        {
            "candidates": candidates,
            "deleted": {
                "blob_digests": [
                    deleted_config_digest,
                    deleted_layer_digest,
                ],
                "manifest_digest": deleted_manifest_digest,
                "repository": repositories["deleted"],
            },
            "probes": probes,
            "repositories": sorted(repositories.values()),
            "retained_digests": sorted(retained),
            "schema": "coffer.gc-filesystem-fixture/v1",
        },
    )


if __name__ == "__main__":
    main()
