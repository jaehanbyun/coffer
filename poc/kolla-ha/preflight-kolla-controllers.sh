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
kolla_source="${root}/work/kolla-ansible-stage3"
kolla_commit="cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
ansible_inventory="${kolla_source}/.venv/bin/ansible-inventory"
rendered_inventory="${work}/kolla-multinode"
inventory_json="${work}/kolla-multinode.json"
controller_hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
management_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
storage_addresses=(
    192.168.253.11
    192.168.253.12
    192.168.253.13
)
management_macs=(
    52:54:00:c5:01:11
    52:54:00:c5:02:11
    52:54:00:c5:03:11
)
storage_macs=(
    52:54:00:c5:01:12
    52:54:00:c5:02:12
    52:54:00:c5:03:12
)
external_macs=(
    52:54:00:c5:01:13
    52:54:00:c5:02:13
    52:54:00:c5:03:13
)

ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

test "$(git -C "${kolla_source}" rev-parse HEAD)" = "${kolla_commit}"
test -f "${kolla_source}/ansible/inventory/multinode"
test -x "${ansible_inventory}"
test "$(cat "${root}/ansible/KOLLA_ANSIBLE_COMMIT")" = "${kolla_commit}"

mkdir -p "${work}"
uv run python "${harness}/render-kolla-inventory.py" \
    "${kolla_source}/ansible/inventory/multinode" \
    "${rendered_inventory}"
"${ansible_inventory}" -i "${rendered_inventory}" --list \
    >"${inventory_json}"
uv run python - "${inventory_json}" "${harness}/kolla-globals.yml" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml


inventory = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {
    "coffer-kolla-ha-stage5-controller-1",
    "coffer-kolla-ha-stage5-controller-2",
    "coffer-kolla-ha-stage5-controller-3",
}


def effective_hosts(group: str) -> set[str]:
    definition = inventory.get(group, {})
    result = set(definition.get("hosts", []))
    for child in definition.get("children", []):
        result.update(effective_hosts(child))
    return result


for group in ("control", "network", "mariadb", "rabbitmq", "keystone"):
    assert effective_hosts(group) == expected, group
for group in ("compute", "monitoring", "storage"):
    assert not effective_hosts(group), group
assert effective_hosts("deployment") == {"localhost"}

globals_document = yaml.safe_load(
    Path(sys.argv[2]).read_text(encoding="utf-8")
)
assert globals_document["openstack_release"] == "2026.1"
assert globals_document["network_interface"] == "ens3"
assert globals_document["storage_interface"] == "ens4"
assert globals_document["kolla_external_vip_interface"] == "ens5"
assert globals_document["kolla_internal_vip_address"] == "192.168.252.10"
assert globals_document["kolla_external_vip_address"] == "192.168.254.10"
assert globals_document["enable_openstack_core"] is False
assert globals_document["enable_keystone"] is True
assert globals_document["kolla_enable_tls_external"] is True
PY

for index in "${!controller_hostnames[@]}"; do
    ssh "${ssh_options[@]}" \
        "ubuntu@${management_addresses[${index}]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${controller_hostnames[${index}]}" \
        "${management_addresses[${index}]}" \
        "${storage_addresses[${index}]}" \
        "${management_macs[${index}]}" \
        "${storage_macs[${index}]}" \
        "${external_macs[${index}]}" \
        <"${harness}/guest-kolla-controller-preflight.sh"
done

ssh "${ssh_options[@]}" ubuntu@192.168.252.31 \
    sudo env LC_ALL=C LANG=C bash -s healthy \
    <"${harness}/guest-ceph-storage-vm-audit.sh"

printf 'kolla_controller_preflight controllers=3 inventory=valid kolla_commit=%s rgw=healthy mutation=none\n' \
    "${kolla_commit}"
