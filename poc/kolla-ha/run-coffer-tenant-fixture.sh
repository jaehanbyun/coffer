#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|prepare|status|cleanup} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|prepare|status|cleanup)
        ;;
    *)
        echo "refusing an unknown Coffer tenant fixture action" >&2
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

"${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"

ssh "${ssh_options[@]}" "ubuntu@${controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
    <"${harness}/guest-run-coffer-tenant-fixture.sh"

case "${action}" in
    prepare)
        ssh "${ssh_options[@]}" "ubuntu@${controller}" \
            sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- status \
            <"${harness}/guest-run-coffer-tenant-fixture.sh"
        ;;
    cleanup)
        ssh "${ssh_options[@]}" "ubuntu@${controller}" \
            sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- preflight \
            <"${harness}/guest-run-coffer-tenant-fixture.sh"
        ;;
esac

printf 'coffer_tenant_fixture action=%s result=passed companion=deployed\n' \
    "${action}"
