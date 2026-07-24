#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|status|run|rollback} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|status|run|rollback)
        ;;
    *)
        echo "refusing an unknown Coffer key-rotation action" >&2
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
    -o ServerAliveCountMax=9
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

run_guest() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "$1" \
        <"${harness}/guest-run-coffer-key-rotation.sh"
}

probe_tenant() {
    local attempt

    for attempt in 1 2 3; do
        if "${harness}/run-coffer-tenant-acceptance.sh" \
            path-status "${ssh_target}"; then
            printf 'coffer_key_rotation tenant_probe=passed attempt=%s\n' \
                "${attempt}"
            return 0
        fi
        sleep 2
    done
    return 1
}

"${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"
probe_tenant
if test "${action}" = preflight || test "${action}" = status; then
    run_guest "${action}"
    printf 'coffer_key_rotation action=%s result=passed mutation=none\n' \
        "${action}"
    exit 0
fi

run_guest "${action}" &
guest_pid="$!"
probes=0
probe_failure=0
while kill -0 "${guest_pid}" 2>/dev/null; do
    if probe_tenant; then
        probes="$((probes + 1))"
    else
        probe_failure=1
    fi
done
set +e
wait "${guest_pid}"
guest_rc="$?"
set -e
test "${guest_rc}" -eq 0
for _ in 1 2 3; do
    test "${probes}" -ge 3 && break
    if probe_tenant; then
        probes="$((probes + 1))"
    else
        probe_failure=1
    fi
done
test "${probe_failure}" -eq 0
test "${probes}" -ge 3
"${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"
"${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
run_guest status
printf 'coffer_key_rotation action=%s result=passed probes=%s serial=1\n' \
    "${action}" "${probes}"
