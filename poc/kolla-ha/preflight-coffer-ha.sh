#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {clean|ready} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    clean|ready)
        ;;
    *)
        echo "refusing an unknown Coffer preflight action" >&2
        exit 64
        ;;
esac
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
known_hosts="${root}/work/kolla-ha/known_hosts"
controller_hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
controller_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
storage_hostnames=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)
storage_addresses=(
    192.168.252.31
    192.168.252.32
    192.168.252.33
)

mkdir -p "$(dirname "${known_hosts}")"
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

"${harness}/run-kolla-lifecycle.sh" status "${ssh_target}"

coffer_image_id=
registry_image_id=
for index in "${!controller_hostnames[@]}"; do
    snapshot="$(
        ssh "${ssh_options[@]}" \
            "ubuntu@${controller_addresses[${index}]}" \
            sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- \
            "${action}" \
            "${controller_hostnames[${index}]}" \
            "$((index + 1))" \
            <"${harness}/guest-coffer-node-preflight.sh"
    )"
    test "$(wc -l <<<"${snapshot}" | tr -d ' ')" -eq 1
    printf '%s\n' "${snapshot}"
    if test "${action}" = ready; then
        node_coffer_image_id="$(
            sed -n 's/.* coffer_image=\\([^ ]*\\).*/\\1/p' <<<"${snapshot}"
        )"
        node_registry_image_id="$(
            sed -n 's/.* registry_image=\\([^ ]*\\).*/\\1/p' <<<"${snapshot}"
        )"
        if test -z "${coffer_image_id}"; then
            coffer_image_id="${node_coffer_image_id}"
            registry_image_id="${node_registry_image_id}"
        else
            test "${node_coffer_image_id}" = "${coffer_image_id}"
            test "${node_registry_image_id}" = "${registry_image_id}"
        fi
    fi
done

ssh "${ssh_options[@]}" \
    "ubuntu@${controller_addresses[0]}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    /home/ubuntu/coffer-stage5/venv/bin/python3 - "${action}" \
    <"${harness}/guest-coffer-control-preflight.py"

for index in "${!storage_hostnames[@]}"; do
    if test "${index}" -eq 0; then
        storage_role=primary
    else
        storage_role=secondary
    fi
    ssh "${ssh_options[@]}" \
        "ubuntu@${storage_addresses[${index}]}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- \
        "${storage_role}" \
        "${storage_hostnames[${index}]}" \
        <"${harness}/guest-coffer-storage-input-preflight.sh"
done

ssh "${ssh_options[@]}" \
    "ubuntu@${storage_addresses[0]}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    python3 - /etc/coffer-stage5-rgw/registry-user.json \
    <"${harness}/guest-stage5-s3-read.py"

printf 'coffer_ha_preflight action=%s controllers=3 storage=3 kolla=healthy rgw=healthy runtime=absent mutation=none\n' \
    "${action}"
