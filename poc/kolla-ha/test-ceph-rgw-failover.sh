#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 <ssh-target>" >&2
    exit 64
fi

ssh_target="$1"
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="${root}/poc/kolla-ha"
known_hosts="${root}/work/kolla-ha/known_hosts"
primary_management_address="192.168.252.31"
management_addresses=(
    192.168.252.31
    192.168.252.32
)
hostnames=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
)
ingress_vip="192.168.253.30"
remote_fault="/tmp/coffer-stage5-rgw-fault.sh"
remote_reader="/tmp/coffer-stage5-s3-read.py"
registry_state="/etc/coffer-stage5-rgw/registry-user.json"
mutation_started=0

ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

run_fault() {
    local action="$1"
    local ingress_host="${2:-}"

    if test -n "${ingress_host}"; then
        # Fixed remote paths and allowlisted action/hostname expand locally.
        # shellcheck disable=SC2029
        ssh "${ssh_options[@]}" \
            "ubuntu@${primary_management_address}" \
            sudo env LC_ALL=C LANG=C bash "${remote_fault}" \
            "${action}" "${remote_reader}" "${ingress_host}"
    else
        # Fixed remote paths and allowlisted actions expand locally.
        # shellcheck disable=SC2029
        ssh "${ssh_options[@]}" \
            "ubuntu@${primary_management_address}" \
            sudo env LC_ALL=C LANG=C bash "${remote_fault}" \
            "${action}" "${remote_reader}"
    fi
}

run_reader() {
    # Both remote paths are fixed by this harness.
    # shellcheck disable=SC2029
    ssh "${ssh_options[@]}" \
        "ubuntu@${primary_management_address}" \
        sudo env LC_ALL=C LANG=C python3 "${remote_reader}" \
        "${registry_state}"
}

find_vip_owner() {
    local owner_count=0
    local owner_hostname=
    local index
    local node_count

    for index in "${!management_addresses[@]}"; do
        node_count="$(
            ssh "${ssh_options[@]}" \
                "ubuntu@${management_addresses[${index}]}" \
                ip -j address show |
                jq --arg vip "${ingress_vip}" \
                    '[.[].addr_info[] | select(.local == $vip)] | length'
        )"
        test "${node_count}" -le 1
        if test "${node_count}" -eq 1; then
            owner_count="$((owner_count + 1))"
            owner_hostname="${hostnames[${index}]}"
        fi
    done
    test "${owner_count}" -eq 1
    printf '%s\n' "${owner_hostname}"
}

cleanup() {
    if test "${mutation_started}" -eq 1; then
        run_fault restore-all >/dev/null 2>&1 || true
    fi
    ssh "${ssh_options[@]}" \
        "ubuntu@${primary_management_address}" \
        rm -f -- "${remote_fault}" "${remote_reader}" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

scp "${ssh_options[@]}" \
    "${harness}/guest-ceph-rgw-fault.sh" \
    "ubuntu@${primary_management_address}:${remote_fault}"
scp "${ssh_options[@]}" \
    "${harness}/guest-stage5-s3-read.py" \
    "ubuntu@${primary_management_address}:${remote_reader}"

run_fault preflight
run_reader
active_ingress_host="$(find_vip_owner)"
case "${active_ingress_host}" in
    "${hostnames[0]}"|"${hostnames[1]}") ;;
    *)
        echo "refusing an unexpected active ingress host" >&2
        exit 66
        ;;
esac

mutation_started=1
run_fault stop-rgw
for _ in $(seq 1 5); do
    rgw_read_evidence="$(run_reader)"
done
printf '%s\n' "${rgw_read_evidence}"
run_fault restore-rgw
run_fault verify

run_fault stop-ingress "${active_ingress_host}"
failed_owner_switched=0
for _ in $(seq 1 60); do
    if surviving_ingress_host="$(find_vip_owner 2>/dev/null)" &&
        test "${surviving_ingress_host}" != "${active_ingress_host}"; then
        failed_owner_switched=1
        break
    fi
    sleep 1
done
test "${failed_owner_switched}" -eq 1
for _ in $(seq 1 5); do
    ingress_read_evidence="$(run_reader)"
done
printf '%s\n' "${ingress_read_evidence}"
run_fault restore-ingress
run_fault verify
final_ingress_host="$(find_vip_owner)"
case "${final_ingress_host}" in
    "${hostnames[0]}"|"${hostnames[1]}") ;;
    *)
        echo "restored ingress has no exact VIP owner" >&2
        exit 67
        ;;
esac

mutation_started=0
cleanup
trap - EXIT
printf 'rgw_failover rgw_reads=5 ingress_reads=5 vip_owners=1 restored=true\n'
