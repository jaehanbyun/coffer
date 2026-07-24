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
work="${root}/work/kolla-ha"
known_hosts="${work}/known_hosts"

mkdir -p "${work}"
touch "${known_hosts}"

guest_records="$(
    uv run python - "${harness}/topology.yml" <<'PYTHON'
from __future__ import annotations

from pathlib import Path
import sys

import yaml


topology = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in (
    topology["domains"]["controllers"] + topology["domains"]["storage"]
):
    print(
        item["name"],
        item["management_address"],
        item["storage_address"],
        item["vcpus"],
        item["memory_mib"],
        item["root_gib"],
        2 if "osd_gib" in item else 1,
        "yes" if "external" in item["macs"] else "no",
        sep="\t",
    )
PYTHON
)"

verify_guest() {
    local guest_name="$1"
    local management_address="$2"
    local storage_address="$3"
    local expected_vcpus="$4"
    local expected_memory_mib="$5"
    local expected_root_gib="$6"
    local expected_disks="$7"
    local expected_external="$8"

    for _ in $(seq 1 30); do
        if ssh \
            -J "${ssh_target}" \
            -o BatchMode=yes \
            -o ConnectTimeout=3 \
            -o StrictHostKeyChecking=accept-new \
            -o UserKnownHostsFile="${known_hosts}" \
            "ubuntu@${management_address}" \
            bash -s -- \
            "${guest_name}" \
            "${management_address}" \
            "${storage_address}" \
            "${expected_vcpus}" \
            "${expected_memory_mib}" \
            "${expected_root_gib}" \
            "${expected_disks}" \
            "${expected_external}" <<'REMOTE'
set -Eeuo pipefail

expected_name="$1"
expected_management="$2"
expected_storage="$3"
expected_vcpus="$4"
expected_memory_mib="$5"
expected_root_gib="$6"
expected_disks="$7"
expected_external="$8"

cloud-init status --wait >/dev/null
test "$(hostname)" = "${expected_name}"
test "$(uname -m)" = x86_64
test "$(nproc)" -eq "${expected_vcpus}"
test "$(systemctl is-active qemu-guest-agent)" = active

actual_memory_mib="$(
    awk '/MemTotal/{printf "%.0f", $2/1024}' /proc/meminfo
)"
test "${actual_memory_mib}" -ge "$((expected_memory_mib * 95 / 100))"
actual_root_gib="$(
    df -BG --output=size / | tail -1 | tr -dc '0-9'
)"
test "${actual_root_gib}" -ge "$((expected_root_gib * 90 / 100))"
actual_disks="$(
    lsblk -dn -o TYPE | awk '$1=="disk"{count++} END{print count+0}'
)"
test "${actual_disks}" -eq "${expected_disks}"

ip -4 -o address show dev ens3 |
    grep -Fq " ${expected_management}/24 "
ip -4 -o address show dev ens4 |
    grep -Fq " ${expected_storage}/24 "
if [[ "${expected_external}" == "yes" ]]; then
    ip link show dev ens5 >/dev/null
    test -z "$(ip -4 -o address show dev ens5)"
else
    if ip link show dev ens5 >/dev/null 2>&1; then
        exit 1
    fi
fi

printf '%s arch=x86_64 cpus=%s memory_mib=%s root_gib=%s disks=%s ready=yes\n' \
    "${expected_name}" "${expected_vcpus}" "${actual_memory_mib}" \
    "${actual_root_gib}" "${actual_disks}"
REMOTE
        then
            return 0
        fi
        sleep 2
    done
    echo "guest readiness timeout: ${guest_name}" >&2
    return 1
}

pids=()
while IFS=$'\t' read -r \
    guest_name management_address storage_address expected_vcpus \
    expected_memory_mib expected_root_gib expected_disks expected_external; do
    verify_guest \
        "${guest_name}" \
        "${management_address}" \
        "${storage_address}" \
        "${expected_vcpus}" \
        "${expected_memory_mib}" \
        "${expected_root_gib}" \
        "${expected_disks}" \
        "${expected_external}" &
    pids+=("$!")
done <<<"${guest_records}"

failures=0
for process_id in "${pids[@]}"; do
    if ! wait "${process_id}"; then
        failures=$((failures + 1))
    fi
done
test "${failures}" -eq 0
