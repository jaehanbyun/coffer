#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|run|status} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|run|status)
        ;;
    *)
        echo "refusing an unknown Stage 5 teardown action" >&2
        exit 64
        ;;
esac
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
topology="${harness}/topology.yml"
work="${root}/work/kolla-ha"
before_inventory="${work}/teardown-before.json"
after_inventory="${work}/teardown-after.json"
tenant_status="${work}/teardown-tenant-status.log"
companion_status="${work}/teardown-companion-status.log"
s3_status="${work}/teardown-s3-status.log"
complete_marker="${work}/teardown.complete"
libvirt_status="${work}/teardown-libvirt-status.json"

mkdir -p "${work}"

classify_libvirt() {
    "${harness}/provision.sh" status "${ssh_target}" >"${libvirt_status}"
    uv run python - "${libvirt_status}" <<'PY'
import json
from pathlib import Path
import sys

document = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
states = [
    item["exists"]
    for collection in ("domains", "volumes", "networks")
    for item in document[collection]
]
if all(states):
    print("present")
elif not any(states):
    print("removed")
else:
    raise SystemExit("partial Stage 5 libvirt state")
PY
}

collect_live_preflight() {
    test "$(classify_libvirt)" = present
    "${harness}/inventory-host.sh" "${ssh_target}" >"${before_inventory}"
    uv run python "${harness}/audit-teardown.py" \
        preflight "${topology}" "${before_inventory}"

    if "${harness}/run-coffer-tenant-fixture.sh" \
        status "${ssh_target}" >"${tenant_status}" 2>&1; then
        tenant_state=prepared
    elif "${harness}/run-coffer-tenant-fixture.sh" \
        preflight "${ssh_target}" >"${tenant_status}" 2>&1; then
        tenant_state=clean
    else
        cat "${tenant_status}" >&2
        echo "tenant teardown state is neither prepared nor clean" >&2
        return 1
    fi

    "${harness}/run-coffer-companion-lifecycle.sh" \
        status "${ssh_target}" >"${companion_status}" 2>&1
    if grep -Fq \
        'coffer_companion_lifecycle state=deployed ' \
        "${companion_status}"; then
        companion_state=deployed
    elif grep -Fq \
        'coffer_companion_lifecycle state=stopped ' \
        "${companion_status}"; then
        companion_state=stopped
    else
        cat "${companion_status}" >&2
        echo "companion teardown state is neither deployed nor stopped" >&2
        return 1
    fi

    "${harness}/cleanup-ceph-s3.sh" \
        status "${ssh_target}" >"${s3_status}" 2>&1
    if grep -Fq 'ceph_s3_cleanup state=prepared ' "${s3_status}"; then
        s3_state=prepared
    elif grep -Fq 'ceph_s3_cleanup state=clean ' "${s3_status}"; then
        s3_state=clean
    else
        cat "${s3_status}" >&2
        echo "S3 teardown state is neither prepared nor clean" >&2
        return 1
    fi

    if test "${s3_state}" = clean; then
        test "${tenant_state}" = clean
        test "${companion_state}" = stopped
    fi
    if test "${companion_state}" = deployed; then
        test "${s3_state}" = prepared
    fi

    printf 'stage5_teardown_preflight tenant=%s companion=%s s3=%s libvirt=present\n' \
        "${tenant_state}" "${companion_state}" "${s3_state}"
}

collect_post_destroy() {
    test "$(classify_libvirt)" = removed
    "${harness}/inventory-host.sh" "${ssh_target}" >"${after_inventory}"
    uv run python "${harness}/audit-teardown.py" \
        post "${topology}" "${before_inventory}" "${after_inventory}"
}

case "${action}" in
    preflight)
        collect_live_preflight
        ;;
    run)
        if test "$(classify_libvirt)" = present; then
            collect_live_preflight
            "${harness}/run-coffer-tenant-fixture.sh" \
                cleanup "${ssh_target}"
            "${harness}/run-coffer-companion-lifecycle.sh" \
                stop "${ssh_target}"
            "${harness}/cleanup-ceph-s3.sh" cleanup "${ssh_target}"
            "${harness}/provision.sh" destroy "${ssh_target}"
        else
            test -f "${before_inventory}"
        fi
        collect_post_destroy
        printf 'coffer-stage5-teardown-v1\n' >"${complete_marker}"
        chmod 0600 "${complete_marker}"
        ;;
    status)
        if test "$(classify_libvirt)" = removed; then
            test -f "${before_inventory}"
            collect_post_destroy
            printf 'stage5_teardown_status state=removed marker=%s\n' "$(
                if test -f "${complete_marker}"; then
                    printf complete
                else
                    printf pending
                fi
            )"
        else
            collect_live_preflight
            printf 'stage5_teardown_status state=ready marker=absent\n'
        fi
        ;;
esac
