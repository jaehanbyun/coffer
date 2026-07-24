#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {status|build} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    status|build)
        ;;
    *)
        echo "refusing an unknown Coffer image action" >&2
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

mkdir -p "$(dirname "${known_hosts}")"
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

"${harness}/run-kolla-lifecycle.sh" status "${ssh_target}"

set +e
ssh "${ssh_options[@]}" "ubuntu@${primary_controller}" \
    sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${action}" \
    <"${harness}/guest-build-distribute-coffer-images.sh"
phase_rc="$?"
set -e

boundary_rc=0
"${harness}/run-kolla-lifecycle.sh" status "${ssh_target}" ||
    boundary_rc="$?"
if test "${phase_rc}" -ne 0; then
    printf 'coffer_images action=%s result=failed rc=%s boundary_rc=%s\n' \
        "${action}" "${phase_rc}" "${boundary_rc}" >&2
    exit "${phase_rc}"
fi
if test "${boundary_rc}" -ne 0; then
    printf 'coffer_images action=%s result=passed boundary=failed rc=%s\n' \
        "${action}" "${boundary_rc}" >&2
    exit "${boundary_rc}"
fi

printf 'coffer_images action=%s result=passed controllers=3 bootstrap=direct publication=none\n' \
    "${action}"
