#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|accept|status|path-status|data-status|database-status} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|accept|status|path-status|data-status|database-status)
        ;;
    *)
        echo "refusing an unknown Coffer tenant acceptance action" >&2
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
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

if test "${action}" != path-status &&
    test "${action}" != data-status &&
    test "${action}" != database-status; then
    "${harness}/run-coffer-tenant-fixture.sh" status "${ssh_target}"
fi

guest_action="${action}"
if test "${action}" = data-status; then
    guest_action=status
fi

set +e
ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${guest_action}" \
    <"${harness}/guest-run-coffer-tenant-acceptance.sh"
phase_rc="$?"
set -e
if test "${phase_rc}" -ne 0; then
    printf 'coffer_tenant_acceptance action=%s result=failed rc=%s\n' \
        "${action}" "${phase_rc}" >&2
    exit "${phase_rc}"
fi

if test "${action}" = accept; then
    if ! ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo test -s \
        /home/ubuntu/coffer-stage5/tenant-acceptance/accepted.complete; then
        echo "tenant acceptance phase returned without its completion marker" >&2
        exit 1
    fi
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- status \
        <"${harness}/guest-run-coffer-tenant-acceptance.sh"
fi

printf 'coffer_tenant_acceptance action=%s result=passed fixture=prepared\n' \
    "${action}"
