#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 {preflight|run} <ssh-target>" >&2
    exit 64
fi

action="$1"
ssh_target="$2"
case "${action}" in
    preflight|run)
        ;;
    *)
        echo "refusing an unknown Coffer reconciler fencing action" >&2
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
controllers=(
    192.168.252.11
    192.168.252.12
)
workers=(
    stage5-reconcile-controller-1
    stage5-reconcile-controller-2
)
temporary_root="${root}/work/kolla-ha/.reconciler-fencing.$$"
cleanup_required=0
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

run_marker() {
    local marker_action="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controllers[0]}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${marker_action}" \
        <"${harness}/guest-run-coffer-reconciler-fencing.sh"
}

run_helper() {
    local index="$1"
    shift

    case "${index}" in
        0|1)
            ;;
        *)
            echo "refusing a non-controller reconciler worker" >&2
            return 64
            ;;
    esac
    ssh "${ssh_options[@]}" "ubuntu@${controllers[${index}]}" \
        sudo docker exec -i coffer_api \
        /var/lib/kolla/venv/bin/python3 - "$@" \
        <"${harness}/guest-coffer-reconciler-fencing.py"
}

run_database_check() {
    ssh "${ssh_options[@]}" "ubuntu@${controllers[0]}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- healthy \
        <"${harness}/guest-check-kolla-galera.sh"
}

require_baseline() {
    "${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
    run_database_check
}

cleanup_temporary() {
    local rc="$?"

    trap - EXIT
    if test "${cleanup_required}" -eq 1; then
        run_helper 0 cleanup >/dev/null 2>&1 || true
    fi
    if test -d "${temporary_root}"; then
        find "${temporary_root}" -mindepth 1 -maxdepth 1 -type f -delete
        rmdir -- "${temporary_root}"
    fi
    exit "${rc}"
}
trap cleanup_temporary EXIT

require_baseline
marker_state="$(run_marker status)"
printf '%s\n' "${marker_state}"
if test "${action}" = run &&
    [[ "${marker_state}" == *" state=running "* ]]; then
    printf 'coffer_reconciler_fencing resume=owned-partial cleanup=allowlisted\n'
else
    for index in 0 1; do
        helper_state="$(run_helper "${index}" preflight)"
        test "${helper_state}" = \
            "coffer_reconciler_fencing state=ready retry_bound=3 residue=0 mutation=none"
        printf 'coffer_reconciler_fencing_node controller=%s %s\n' \
            "$((index + 1))" "${helper_state}"
    done
fi

if test "${action}" = preflight; then
    trap - EXIT
    printf 'coffer_reconciler_fencing action=preflight result=passed mutations=none\n'
    exit 0
fi
if [[ "${marker_state}" == *" state=completed "* ]]; then
    trap - EXIT
    printf 'coffer_reconciler_fencing action=run result=passed idempotent=yes\n'
    exit 0
fi

run_marker start
cleanup_required=1
run_helper 0 cleanup
setup_claims="$(run_helper 0 setup-claims)"
printf '%s\n' "${setup_claims}"
claims_cursor="$(sed -n 's/.* cursor=//p' <<<"${setup_claims}")"
test -n "${claims_cursor}"
install -d -m 0700 "${temporary_root}"

run_helper 0 claim --worker "${workers[0]}" --cursor "${claims_cursor}" \
    >"${temporary_root}/worker-0.out" &
worker_zero_pid="$!"
run_helper 1 claim --worker "${workers[1]}" --cursor "${claims_cursor}" \
    >"${temporary_root}/worker-1.out" &
worker_one_pid="$!"
set +e
wait "${worker_zero_pid}"
worker_zero_rc="$?"
wait "${worker_one_pid}"
worker_one_rc="$?"
set -e
test "${worker_zero_rc}" -eq 0
test "${worker_one_rc}" -eq 0
worker_zero_claims="$(
    sed -n 's/.* claims=//p' "${temporary_root}/worker-0.out"
)"
worker_one_claims="$(
    sed -n 's/.* claims=//p' "${temporary_root}/worker-1.out"
)"
[[ "${worker_zero_claims}" =~ ^[0-2]$ ]]
[[ "${worker_one_claims}" =~ ^[0-2]$ ]]
total_claims="$((worker_zero_claims + worker_one_claims))"
retry_count=0
while test "${total_claims}" -lt 3 && test "${retry_count}" -lt 3; do
    if test "${worker_zero_claims}" -le "${worker_one_claims}"; then
        retry_index=0
    else
        retry_index=1
    fi
    retry_output="$(
        run_helper "${retry_index}" claim \
            --worker "${workers[${retry_index}]}" --cursor "${claims_cursor}"
    )"
    retry_claims="$(sed -n 's/.* claims=//p' <<<"${retry_output}")"
    [[ "${retry_claims}" =~ ^[0-2]$ ]]
    if test "${retry_index}" -eq 0; then
        worker_zero_claims="$((worker_zero_claims + retry_claims))"
    else
        worker_one_claims="$((worker_one_claims + retry_claims))"
    fi
    total_claims="$((worker_zero_claims + worker_one_claims))"
    retry_count="$((retry_count + 1))"
done
test "${total_claims}" -eq 3
printf 'coffer_reconciler_fencing claims=%s+%s retries=%s\n' \
    "${worker_zero_claims}" "${worker_one_claims}" "${retry_count}"
run_helper 0 finish-claims

setup_abandon="$(run_helper 0 setup-abandon)"
printf '%s\n' "${setup_abandon}"
abandon_cursor="$(sed -n 's/.* cursor=//p' <<<"${setup_abandon}")"
test -n "${abandon_cursor}"
run_helper 1 abandon --cursor "${abandon_cursor}"
run_helper 0 recover --cursor "${abandon_cursor}"
run_helper 0 cleanup
run_helper 0 preflight
run_helper 1 preflight
cleanup_required=0

run_database_check
"${harness}/run-coffer-tenant-acceptance.sh" database-status "${ssh_target}"
require_baseline
run_marker complete
test "$(run_marker status)" = \
    "coffer_reconciler_fencing_marker state=completed mutation=none"
trap - EXIT
find "${temporary_root}" -mindepth 1 -maxdepth 1 -type f -delete
rmdir -- "${temporary_root}"
printf 'coffer_reconciler_fencing action=run result=passed workers=2 claims=3 lease=recovered stale_token=fenced residue=0\n'
