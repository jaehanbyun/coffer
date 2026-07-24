#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|prepare} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|prepare)
        ;;
    *)
        echo "refusing an unknown Kolla production-profile action" >&2
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
marker="/home/ubuntu/coffer-stage5/production-profile.prepared"

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

if test "${action}" = prepare; then
    if ! ssh "${ssh_options[@]}" "ubuntu@${primary_controller}" \
        sudo test -f "${marker}"; then
        "${harness}/preflight-coffer-ha.sh" clean "${ssh_target}"
    fi
fi

ssh "${ssh_options[@]}" "ubuntu@${primary_controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
    <"${harness}/guest-prepare-kolla-production-profile.sh"

"${harness}/run-kolla-lifecycle.sh" status "${ssh_target}"

printf 'kolla_production_profile action=%s result=passed external_rgw=healthy coffer_runtime=absent\n' \
    "${action}"
