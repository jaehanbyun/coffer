#!/usr/bin/env bash

set -Eeuo pipefail

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
        echo "refusing an unknown Coffer Galera transaction action" >&2
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
expected_result=(
    "coffer_galera_transactions concurrency_admitted=1"
    "concurrency_denied=1"
    "retry_code=1205"
    "retry_attempt=2"
    "retry_operation=set_limit"
    "residue=0"
)
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

run_guest() {
    local guest_action="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- "${guest_action}" \
        <"${harness}/guest-run-coffer-galera-transactions.sh"
}

run_database_check() {
    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- healthy \
        <"${harness}/guest-check-kolla-galera.sh"
}

run_transaction_helper() {
    local helper_action="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller}" \
        sudo docker exec -i coffer_api \
        /var/lib/kolla/venv/bin/python3 - "${helper_action}" \
        <"${harness}/guest-coffer-galera-transactions.py"
}

require_baseline() {
    "${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
    run_database_check
}

require_baseline
marker_state="$(run_guest status)"
printf '%s\n' "${marker_state}"
if test "${action}" = run &&
    [[ "${marker_state}" == *" state=running "* ]]; then
    printf 'coffer_galera_transactions resume=owned-partial cleanup=allowlisted\n'
else
    helper_state="$(run_transaction_helper preflight)"
    test "${helper_state}" = \
        "coffer_galera_transactions state=ready retry_bound=3 residue=0 mutation=none"
    printf '%s\n' "${helper_state}"
fi

if test "${action}" = preflight; then
    printf 'coffer_galera_transactions action=preflight result=passed mutations=none\n'
    exit 0
fi

if [[ "${marker_state}" == *" state=completed "* ]]; then
    printf 'coffer_galera_transactions action=run result=passed idempotent=yes\n'
    exit 0
fi

run_guest start
result="$(run_transaction_helper run)"
test "${result}" = "${expected_result[*]}"
printf '%s\n' "${result}"
run_database_check
"${harness}/run-coffer-tenant-acceptance.sh" database-status "${ssh_target}"
run_transaction_helper preflight
run_guest complete
require_baseline
test "$(run_guest status)" = \
    "coffer_galera_transactions_marker state=completed mutation=none"
printf 'coffer_galera_transactions action=run result=passed galera=healthy tenant=retained residue=0\n'
