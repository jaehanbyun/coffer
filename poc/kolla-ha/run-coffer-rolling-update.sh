#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|status|upgrade|rollback} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|status|upgrade|rollback)
        ;;
    *)
        echo "refusing an unknown Coffer rolling-update action" >&2
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

require_baseline() {
    "${harness}/run-coffer-companion-lifecycle.sh" status "${ssh_target}"
}

run_guest() {
    local guest_action="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${guest_action}" \
        <"${harness}/guest-run-coffer-rolling-update.sh"
}

probe_tenant() {
    local attempt

    for attempt in 1 2 3; do
        if "${harness}/run-coffer-tenant-acceptance.sh" \
            path-status "${ssh_target}"; then
            printf 'coffer_rolling_update tenant_probe=passed attempt=%s\n' \
                "${attempt}"
            return 0
        fi
        sleep 2
    done
    echo "tenant data probe failed during rolling update" >&2
    return 1
}

require_baseline
probe_tenant

if test "${action}" = preflight || test "${action}" = status; then
    run_guest "${action}"
    printf 'coffer_rolling_update action=%s result=passed mutation=none\n' \
        "${action}"
    exit 0
fi

guest_action="${action}"
if test "${action}" = rollback; then
    guest_action=rollback-rehearse
fi
run_guest "${guest_action}" &
guest_pid="$!"
probe_count=0
probe_failure=0
while kill -0 "${guest_pid}" 2>/dev/null; do
    if probe_tenant; then
        probe_count="$((probe_count + 1))"
    else
        probe_failure=1
    fi
done
during_probe_count="${probe_count}"
set +e
wait "${guest_pid}"
guest_rc="$?"
set -e
if test "${guest_rc}" -ne 0; then
    printf 'coffer_rolling_update action=%s result=failed rc=%s probes=%s\n' \
        "${action}" "${guest_rc}" "${probe_count}" >&2
    exit "${guest_rc}"
fi
if test "${probe_failure}" -ne 0; then
    if test "${action}" = rollback; then
        run_guest rollback-reset
    fi
    echo "tenant availability failed during rolling update" >&2
    exit 1
fi
test "${during_probe_count}" -ge 1
while test "${probe_count}" -lt 3; do
    probe_tenant
    probe_count="$((probe_count + 1))"
done
test "${probe_count}" -ge 3

if test "${action}" = rollback; then
    run_guest rollback-finalize
fi
require_baseline
run_guest status
"${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
printf 'coffer_rolling_update action=%s result=passed probes=%s during=%s serial=1\n' \
    "${action}" "${probe_count}" "${during_probe_count}"
