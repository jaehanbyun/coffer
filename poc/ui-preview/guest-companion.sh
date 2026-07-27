#!/usr/bin/env bash

set -Eeuo pipefail

action="${1:-}"
source_root="/home/ubuntu/coffer"
state_root="/home/ubuntu/coffer-ui-preview"
log_root="${state_root}/logs"
inventory="/etc/kolla/all-in-one"
config_root="/etc/kolla"
passwords="${config_root}/passwords.yml"
coffer_globals="${config_root}/coffer-globals.yml"
image_globals="${config_root}/coffer-ui-images.yml"

case "${action}" in
    prechecks|deploy|reconfigure|status)
        ;;
    *)
        echo "usage: $0 {prechecks|deploy|reconfigure|status}" >&2
        exit 64
        ;;
esac
test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test -x "${source_root}/ansible/kolla-ansible-coffer"

if test "${action}" = status; then
    docker ps -a --format '{{.Names}} {{.Status}} {{.Image}}' |
        grep -E '^(coffer_|horizon |skyline_console |coffer-bootstrap-registry )'
    exit 0
fi

test -s "${coffer_globals}"
test -s "${image_globals}"
test "$(cat "${state_root}/images.complete")" = \
    "coffer-ui-preview-images-v1"

verify_log_secret_free() {
    local checked_log="$1"

    "${state_root}/venv/bin/python3" - \
        "${passwords}" \
        "${config_root}/config/coffer/secrets" \
        "/root/coffer-ui-preview-identities.json" \
        "${checked_log}" <<'PY'
from pathlib import Path
import base64
import json
import sys
import urllib.parse

import yaml

password_path, secret_root, identity_path, log_path = map(Path, sys.argv[1:])
values = []
passwords = yaml.safe_load(password_path.read_text(encoding="utf-8"))
values.extend(
    value.encode()
    for value in passwords.values()
    if isinstance(value, str) and len(value) >= 8
)
for path in secret_root.iterdir():
    if path.is_file() and not path.is_symlink():
        value = path.read_bytes().strip()
        if len(value) >= 8:
            values.append(value)
if identity_path.is_file():
    identities = json.loads(identity_path.read_text(encoding="utf-8"))
    for fixture in identities.values():
        if not isinstance(fixture, dict):
            continue
        for name, value in fixture.items():
            if (
                isinstance(value, str)
                and len(value) >= 8
                and ("password" in name or "secret" in name)
            ):
                values.append(value.encode())

data = log_path.read_bytes()
for value in values:
    candidates = {
        value,
        urllib.parse.quote_from_bytes(value, safe="").encode(),
        base64.b64encode(value),
    }
    if any(candidate in data for candidate in candidates):
        raise SystemExit("owner secret found in companion lifecycle log")
PY
}

log="${log_root}/coffer-${action}.log"
install -o root -g root -m 0600 /dev/null "${log}"
set +e
env \
    PATH="${state_root}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    ANSIBLE_NOCOLOR=1 \
    ANSIBLE_NO_LOG=True \
    ANSIBLE_DEPRECATION_WARNINGS=False \
    ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
    timeout --signal=INT --kill-after=120 3600 \
    "${source_root}/ansible/kolla-ansible-coffer" "${action}" \
    -i "${inventory}" \
    --configdir "${config_root}" \
    --passwords "${passwords}" \
    -e "@${coffer_globals}" \
    -e "@${image_globals}" \
    >"${log}" 2>&1
rc="$?"
set -e
verify_log_secret_free "${log}"
if test "${rc}" -ne 0; then
    tail -n 100 "${log}" >&2
    exit "${rc}"
fi
awk '
    /^PLAY RECAP/ {capture = 1; next}
    capture && NF {print "coffer_recap " $0}
    capture && !NF {exit}
' "${log}"
