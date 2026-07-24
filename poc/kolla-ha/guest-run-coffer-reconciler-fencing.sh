#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|start|complete}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status|start|complete)
        ;;
    *)
        echo "refusing an unknown Coffer reconciler fencing action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
marker_root="${state_root}/coffer-reconciler-fencing"
owner_marker="${marker_root}/owner"
complete_marker="${marker_root}/complete"
owner_value="coffer-stage5-reconciler-fencing-v1"
complete_value="workers=2 disjoint=yes lease=recovered stale-token=fenced residue=0"
temporary_helper="/run/coffer-stage5-reconciler-fencing.py"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(docker inspect -f '{{.State.Running}}' coffer_api)" = true
test "$(docker inspect -f '{{.State.Health.Status}}' coffer_api)" = healthy
test ! -e "${temporary_helper}"

write_marker() {
    local marker="$1"
    local value="$2"
    local temporary="${marker}.tmp.$$"

    printf '%s\n' "${value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
}

require_owner() {
    test "$(stat -c '%U:%G:%a' "${marker_root}")" = root:root:700
    test "$(stat -c '%U:%G:%a' "${owner_marker}")" = root:root:600
    test "$(cat "${owner_marker}")" = "${owner_value}"
}

if test ! -e "${marker_root}"; then
    state=ready
else
    require_owner
    if test -e "${complete_marker}"; then
        test "$(stat -c '%U:%G:%a' "${complete_marker}")" = root:root:600
        test "$(cat "${complete_marker}")" = "${complete_value}"
        state=completed
    else
        test "$(find "${marker_root}" -mindepth 1 -maxdepth 1 -printf '%f\n')" = \
            owner
        state=running
    fi
fi

case "${action}" in
    status)
        printf 'coffer_reconciler_fencing_marker state=%s mutation=none\n' \
            "${state}"
        ;;
    start)
        if test "${state}" = completed; then
            printf 'coffer_reconciler_fencing_marker state=completed idempotent=yes\n'
            exit 0
        fi
        if test "${state}" = ready; then
            install -d -o root -g root -m 0700 "${marker_root}"
            write_marker "${owner_marker}" "${owner_value}"
        fi
        require_owner
        printf 'coffer_reconciler_fencing_marker state=running owner=verified\n'
        ;;
    complete)
        test "${state}" = running
        require_owner
        write_marker "${complete_marker}" "${complete_value}"
        printf 'coffer_reconciler_fencing_marker state=completed result=passed\n'
        ;;
esac
