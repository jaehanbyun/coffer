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
known_hosts="${root}/work/kolla-ha/known_hosts"
primary_controller="192.168.252.11"
primary_storage="192.168.253.31"

jump_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

audit_storage() {
    ssh "${jump_options[@]}" \
        "ubuntu@${primary_storage}" \
        sudo env LC_ALL=C LANG=C bash -s healthy \
        <"${harness}/guest-ceph-storage-vm-audit.sh"
}

audit_storage
ssh "${jump_options[@]}" \
    "ubuntu@${primary_controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 \
    /home/ubuntu/coffer-stage5/venv/bin/python3 - \
    <"${harness}/guest-rotate-kolla-monitoring-password.py"
audit_storage

printf 'kolla_password_rotation result=passed external_rgw=healthy\n'
