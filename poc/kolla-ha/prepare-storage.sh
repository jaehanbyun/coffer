#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 <ssh-target>" >&2
    exit 64
fi

ssh_target="$1"
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
topology="${harness}/topology.yml"
work="${root}/work/kolla-ha"
known_hosts="${work}/known_hosts"
cephadm_source="${root}/work/rgw/cephadm-20.2.2"
cephadm_sha256="42daa0d45411be4c8bb16fe92e265c59cc21fc86cd0040b96409c80ba0da884c"

test -f "${cephadm_source}"
printf '%s  %s\n' "${cephadm_sha256}" "${cephadm_source}" |
    shasum -a 256 --check --status
mkdir -p "${work}"
touch "${known_hosts}"

storage_records="$(
    uv run python - "${topology}" <<'PYTHON'
from __future__ import annotations

import base64
from pathlib import Path
import sys

import yaml


topology = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
storage_nodes = topology["domains"]["storage"]
host_map = "".join(
    f"{item['storage_address']} {item['name']}\n"
    for item in storage_nodes
)
encoded_host_map = base64.b64encode(host_map.encode()).decode()
for item in storage_nodes:
    print(
        item["name"],
        item["management_address"],
        encoded_host_map,
        sep="\t",
    )
PYTHON
)"

prepare_storage() {
    local storage_hostname="$1"
    local management_address="$2"
    local host_map_base64="$3"

    scp \
        -o "ProxyJump=${ssh_target}" \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile="${known_hosts}" \
        "${cephadm_source}" \
        "ubuntu@${management_address}:/tmp/cephadm-20.2.2"
    ssh \
        -J "${ssh_target}" \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile="${known_hosts}" \
        "ubuntu@${management_address}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${storage_hostname}" "${host_map_base64}" \
        <"${harness}/guest-prepare-storage.sh"
}

pids=()
while IFS=$'\t' read -r \
    storage_hostname management_address host_map_base64; do
    prepare_storage \
        "${storage_hostname}" "${management_address}" "${host_map_base64}" &
    pids+=("$!")
done <<<"${storage_records}"

failures=0
for process_id in "${pids[@]}"; do
    if ! wait "${process_id}"; then
        failures=$((failures + 1))
    fi
done
test "${failures}" -eq 0
