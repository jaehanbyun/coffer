#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|bootstrap|prechecks|pull|deploy|reconfigure} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|bootstrap|prechecks|pull|deploy|reconfigure)
        ;;
    *)
        echo "refusing an unknown Kolla lifecycle action" >&2
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
primary_controller="192.168.252.11"
primary_storage="192.168.253.31"

mkdir -p "$(dirname "${known_hosts}")"

jump_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
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

set +e
ssh "${jump_options[@]}" \
    "ubuntu@${primary_controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
    <"${harness}/guest-run-kolla-lifecycle.sh"
phase_rc="$?"
set -e

storage_rc=0
audit_storage || storage_rc="$?"
if test "${phase_rc}" -ne 0; then
    printf 'kolla_lifecycle action=%s result=failed rc=%s storage_rc=%s\n' \
        "${action}" "${phase_rc}" "${storage_rc}" >&2
    exit "${phase_rc}"
fi
if test "${storage_rc}" -ne 0; then
    printf 'kolla_lifecycle action=%s result=passed storage_audit=failed rc=%s\n' \
        "${action}" "${storage_rc}" >&2
    exit "${storage_rc}"
fi

printf 'kolla_lifecycle action=%s result=passed external_rgw=healthy\n' \
    "${action}"
