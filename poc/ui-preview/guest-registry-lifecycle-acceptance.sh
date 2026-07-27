#!/usr/bin/env bash

set -Eeuo pipefail

backend_ca="/etc/kolla/coffer-edge-replica/backend-ca.crt"
guest_address="192.168.122.204"

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"

docker restart \
    coffer_api \
    coffer_edge \
    coffer_registry \
    coffer_edge_replica \
    coffer_registry_replica >/dev/null
for _attempt in $(seq 1 60); do
    if test "$(
        docker inspect \
            --format '{{.State.Health.Status}}' coffer_api
    )" = healthy &&
        test "$(
            docker inspect \
                --format '{{.State.Health.Status}}' coffer_edge
        )" = healthy &&
        test "$(
            docker inspect \
                --format '{{.State.Health.Status}}' coffer_registry
        )" = healthy &&
        test "$(
            curl --silent \
                --cacert "${backend_ca}" \
                --output /dev/null \
                --write-out '%{http_code}' \
                "https://${guest_address}:18888/v2/" || true
        )" = 401; then
        break
    fi
    sleep 1
done
for container in coffer_api coffer_edge coffer_registry; do
    test "$(
        docker inspect \
            --format '{{.State.Health.Status}}' "${container}"
    )" = healthy
done
test "$(
    curl --silent --show-error \
        --cacert "${backend_ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        "https://${guest_address}:18888/v2/"
)" = 401

python3 - <<'PY'
from pathlib import Path
import base64
import json
import re
import subprocess
import urllib.parse


identity = json.loads(
    Path("/root/coffer-ui-preview-identities.json").read_text(encoding="utf-8")
)
values = []
for fixture in identity.values():
    if not isinstance(fixture, dict):
        continue
    for key, value in fixture.items():
        if (
            isinstance(value, str)
            and len(value) >= 8
            and ("password" in key or "secret" in key)
        ):
            values.append(value.encode())
for path in Path("/etc/kolla/config/coffer/secrets").iterdir():
    if path.is_file() and not path.is_symlink():
        value = path.read_bytes().strip()
        if len(value) >= 8:
            values.append(value)

data = b""
for container in (
    "coffer_api",
    "coffer_edge",
    "coffer_registry",
    "coffer_edge_replica",
    "coffer_registry_replica",
):
    data += subprocess.run(
        ["docker", "logs", container],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    ).stdout
for value in values:
    candidates = {
        value,
        urllib.parse.quote_from_bytes(value, safe="").encode(),
        base64.b64encode(value),
    }
    if any(candidate in data for candidate in candidates):
        raise SystemExit("owner secret found in Coffer runtime logs")
if b"-----BEGIN PRIVATE KEY-----" in data:
    raise SystemExit("private key found in Coffer runtime logs")
if re.search(
    rb"Authorization ['\"](?:Basic|Bearer) [A-Za-z0-9+/=._-]+",
    data,
):
    raise SystemExit("authorization credential found in Coffer runtime logs")
if re.search(
    rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    data,
):
    raise SystemExit("bearer token found in Coffer runtime logs")
PY

echo "guest_restart_and_log_scan=passed"
