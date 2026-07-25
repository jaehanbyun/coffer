from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


MANIFEST_ACCEPT = (
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.oci.image.index.v1+json"
)


class RegistryClient:
    def __init__(self, origin: str) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("fixture registry must be one HTTP origin")
        self._host = parsed.hostname
        self._port = parsed.port or 80

    def request(
        self,
        method: str,
        target: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(
            self._host,
            self._port,
            timeout=5,
        )
        try:
            connection.request(method, target, headers=headers or {})
            response = connection.getresponse()
            body = response.read()
            return (
                response.status,
                {
                    name.lower(): value
                    for name, value in response.getheaders()
                },
                body,
            )
        finally:
            connection.close()


def write_private_json(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-origin", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("collected", "restored"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    if fixture.get("schema") != "coffer.gc-filesystem-fixture/v1":
        raise SystemExit("fixture schema changed")
    client = RegistryClient(args.registry_origin)
    observed_classes: set[str] = set()
    for probe in fixture["probes"]:
        repository = probe["repository"]
        reference = probe["reference"]
        if probe["kind"] == "manifest":
            target = f"/v2/{repository}/manifests/{reference}"
            headers = {"Accept": MANIFEST_ACCEPT}
        elif probe["kind"] == "blob":
            target = f"/v2/{repository}/blobs/{reference}"
            headers = {}
        else:
            raise SystemExit("fixture probe kind changed")
        status, response_headers, _ = client.request(
            "HEAD",
            target,
            headers=headers,
        )
        if (
            status != 200
            or response_headers.get("docker-content-digest")
            != probe["digest"]
        ):
            raise SystemExit("retained fixture content is unavailable")
        observed_classes.add(probe["class"])
    expected_classes = {
        "shared-blob",
        "private-blob",
        "tagged-manifest",
        "index",
        "index-child",
        "digest-only-manifest",
        "subject",
        "referrer",
        "referrers-index",
    }
    if observed_classes != expected_classes:
        raise SystemExit("survivor class verification is incomplete")

    shared_probe = next(
        probe
        for probe in fixture["probes"]
        if probe["class"] == "shared-blob"
    )
    project_b_repository = next(
        repository
        for repository in fixture["repositories"]
        if repository.endswith("/keep-b")
    )
    status, headers, _ = client.request(
        "HEAD",
        f"/v2/{project_b_repository}/blobs/{shared_probe['digest']}",
    )
    if (
        status != 200
        or headers.get("docker-content-digest")
        != shared_probe["digest"]
    ):
        raise SystemExit("shared blob did not survive in both repositories")

    deleted = fixture["deleted"]
    status, _, _ = client.request(
        "HEAD",
        f"/v2/{deleted['repository']}/manifests/"
        f"{deleted['manifest_digest']}",
        headers={"Accept": MANIFEST_ACCEPT},
    )
    if status != 404:
        raise SystemExit("logically deleted manifest became readable")
    if args.mode == "collected":
        for blob_digest in deleted["blob_digests"]:
            status, _, _ = client.request(
                "HEAD",
                f"/v2/{deleted['repository']}/blobs/{blob_digest}",
            )
            if status != 404:
                raise SystemExit("collected blob remained readable")

    digest_only_repository = next(
        repository
        for repository in fixture["repositories"]
        if repository.endswith("/digest-only")
    )
    status, _, body = client.request(
        "GET",
        f"/v2/{digest_only_repository}/tags/list",
    )
    tags = json.loads(body)
    empty_tag_listing = status == 200 and tags.get("tags") in (None, [])
    absent_tag_path = (
        status == 404
        and isinstance(tags.get("errors"), list)
        and tags["errors"]
        and tags["errors"][0].get("code") == "NAME_UNKNOWN"
    )
    if not empty_tag_listing and not absent_tag_path:
        raise SystemExit("digest-only manifest gained a tag")

    write_private_json(
        args.output,
        {
            "deleted_manifest_unreadable": True,
            "mode": args.mode,
            "schema": "coffer.gc-filesystem-survivors/v1",
            "shared_blob_repositories": 2,
            "survivor_classes": sorted(observed_classes),
        },
    )


if __name__ == "__main__":
    main()
