#!/usr/bin/env bash

set -Eeuo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
topology="${harness}/topology.yml"
work="${root}/work/kolla-ha"

action="${1:-}"
ssh_target="${2:-}"

if [[ "$#" -ne 2 ]] ||
    [[ ! "${action}" =~ ^(preflight|status|create|destroy)$ ]]; then
    echo "usage: $0 {preflight|status|create|destroy} <ssh-target>" >&2
    exit 64
fi
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

mkdir -p "${work}"

run_preflight() {
    "${harness}/inventory-host.sh" "${ssh_target}" \
        >"${work}/host-inventory.json"
    uv run python "${harness}/preflight.py" \
        "${topology}" "${work}/host-inventory.json"
}

topology_payload() {
    uv run python - "${topology}" <<'PYTHON'
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

import yaml


document = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
encoded = base64.b64encode(
    json.dumps(document, separators=(",", ":")).encode()
).decode()
print(encoded)
PYTHON
}

run_remote() {
    local remote_action="$1"
    local encoded_topology
    local remote_command
    encoded_topology="$(topology_payload)"
    remote_command="$(
        printf "COFFER_STAGE5_TOPOLOGY_B64='%s' python3 - '%s'" \
            "${encoded_topology}" "${remote_action}"
    )"
    ssh \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        "${ssh_target}" "${remote_command}" \
        <"${harness}/libvirt_remote.py"
}

case "${action}" in
    preflight)
        run_preflight | tee "${work}/preflight.json"
        ;;
    status)
        run_remote status | tee "${work}/libvirt-status.json"
        ;;
    create)
        run_preflight | tee "${work}/preflight.json"
        run_remote create | tee "${work}/libvirt-create.json"
        ;;
    destroy)
        run_remote destroy | tee "${work}/libvirt-destroy.json"
        ;;
esac
