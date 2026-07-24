#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {primary|secondary} HOST" >&2
    exit 64
fi

role="$1"
expected_hostname="$2"
credential_root="/etc/coffer-stage5-rgw"
registry_user="${credential_root}/registry-user.json"
distribution_env="${credential_root}/distribution.env"
rgw_ca="/etc/ceph/coffer-stage5-ingress/ca.crt"

case "${role}" in
    primary|secondary)
        ;;
    *)
        echo "refusing an unknown RGW input role" >&2
        exit 64
        ;;
esac

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"

if test "${role}" = secondary; then
    test ! -e "${credential_root}"
    test ! -e "${rgw_ca}"
    printf 'coffer_storage_input role=secondary host=%s credentials=absent ca=primary-only\n' \
        "${expected_hostname}"
    exit 0
fi

test "$(stat -c '%U:%G:%a' "${rgw_ca}")" = root:root:644
test -s "${rgw_ca}"
openssl x509 -in "${rgw_ca}" -checkend 86400 -noout >/dev/null
test "$(stat -c '%U:%G:%a' "${credential_root}")" = root:root:700
test "$(stat -c '%U:%G:%a' "${registry_user}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${distribution_env}")" = root:root:600
test -s "${registry_user}"
test -s "${distribution_env}"

python3 - "${registry_user}" "${distribution_env}" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys


user_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
document = json.loads(user_path.read_text(encoding="utf-8"))
keys = document.get("keys", [])
if len(keys) != 1:
    raise SystemExit("expected one registry key")
access_key = keys[0].get("access_key")
secret_key = keys[0].get("secret_key")
if not isinstance(access_key, str) or len(access_key) < 8:
    raise SystemExit("invalid registry access key")
if not isinstance(secret_key, str) or len(secret_key) < 16:
    raise SystemExit("invalid registry secret key")

values: dict[str, str] = {}
for raw_line in env_path.read_text(encoding="utf-8").splitlines():
    if not raw_line or raw_line.startswith("#"):
        continue
    name, separator, value = raw_line.partition("=")
    if not separator:
        raise SystemExit("invalid Distribution environment input")
    values[name] = value.strip("'\"")

expected = {
    "REGISTRY_STORAGE_S3_ACCESSKEY": access_key,
    "REGISTRY_STORAGE_S3_SECRETKEY": secret_key,
}
for name, value in expected.items():
    if values.get(name) != value:
        raise SystemExit("Distribution credential input mismatch")
PY

printf 'coffer_storage_input role=primary host=%s credentials=owner-only ca=valid\n' \
    "${expected_hostname}"
