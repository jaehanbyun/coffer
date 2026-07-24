#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|prechecks|deploy} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|prechecks|deploy)
        ;;
    *)
        echo "refusing an unknown Coffer companion lifecycle action" >&2
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
controller="192.168.252.11"
storage="192.168.253.31"

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

audit_storage() {
    ssh "${ssh_options[@]}" "ubuntu@${storage}" \
        sudo env LC_ALL=C LANG=C bash -s healthy \
        <"${harness}/guest-ceph-storage-vm-audit.sh"
}

if test "${action}" = prechecks; then
    "${harness}/prepare-coffer-companion.sh" status "${ssh_target}"
elif test "${action}" = deploy; then
    "${harness}/prepare-coffer-operator-source.sh" status "${ssh_target}"
fi
audit_storage

set +e
ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
    <"${harness}/guest-run-coffer-companion-lifecycle.sh"
phase_rc="$?"
set -e

boundary_rc=0
if test "${action}" = prechecks; then
    "${harness}/prepare-coffer-companion.sh" status "${ssh_target}" ||
        boundary_rc="$?"
elif test "${action}" = deploy; then
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- status \
        <"${harness}/guest-run-coffer-companion-lifecycle.sh" ||
        boundary_rc="$?"
fi

storage_rc=0
audit_storage || storage_rc="$?"
if test "${phase_rc}" -ne 0; then
    printf 'coffer_companion_lifecycle action=%s result=failed rc=%s boundary_rc=%s storage_rc=%s\n' \
        "${action}" "${phase_rc}" "${boundary_rc}" "${storage_rc}" >&2
    exit "${phase_rc}"
fi
if test "${boundary_rc}" -ne 0; then
    printf 'coffer_companion_lifecycle action=%s result=passed boundary=failed rc=%s\n' \
        "${action}" "${boundary_rc}" >&2
    exit "${boundary_rc}"
fi
if test "${storage_rc}" -ne 0; then
    printf 'coffer_companion_lifecycle action=%s result=passed storage=failed rc=%s\n' \
        "${action}" "${storage_rc}" >&2
    exit "${storage_rc}"
fi

printf 'coffer_companion_lifecycle action=%s result=passed external_rgw=healthy\n' \
    "${action}"
