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
target_domain="coffer-rgw-ha-stage5-storage-3"
primary_management_address="192.168.252.31"
target_management_address="192.168.252.33"
ingress_management_addresses=(
    192.168.252.31
    192.168.252.32
)
ingress_vip="192.168.253.30"
remote_audit="/tmp/coffer-stage5-storage-vm-audit.sh"
remote_reader="/tmp/coffer-stage5-storage-vm-read.py"
registry_state="/etc/coffer-stage5-rgw/registry-user.json"
fault_started=0

jump_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

run_libvirt() {
    local action="$1"

    ssh \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        "${ssh_target}" \
        env LC_ALL=C LANG=C python3 - "${action}" \
        <"${harness}/storage_vm_fault_remote.py"
}

run_audit() {
    local action="$1"

    # Fixed remote path and allowlisted action expand locally.
    # shellcheck disable=SC2029
    ssh "${jump_options[@]}" \
        "ubuntu@${primary_management_address}" \
        sudo env LC_ALL=C LANG=C bash "${remote_audit}" "${action}"
}

run_reader() {
    # Both remote paths are fixed by this harness.
    # shellcheck disable=SC2029
    ssh "${jump_options[@]}" \
        "ubuntu@${primary_management_address}" \
        sudo env LC_ALL=C LANG=C python3 "${remote_reader}" \
        "${registry_state}"
}

vip_owner_count() {
    local address
    local count
    local total=0

    for address in "${ingress_management_addresses[@]}"; do
        count="$(
            ssh "${jump_options[@]}" "ubuntu@${address}" ip -j address show |
                jq --arg vip "${ingress_vip}" \
                    '[.[].addr_info[] | select(.local == $vip)] | length'
        )"
        test "${count}" -le 1
        total="$((total + count))"
    done
    printf '%s\n' "${total}"
}

wait_target_ssh() {
    local reachable=0

    for _ in $(seq 1 120); do
        if ssh "${jump_options[@]}" \
            "ubuntu@${target_management_address}" true 2>/dev/null; then
            reachable=1
            break
        fi
        sleep 2
    done
    test "${reachable}" -eq 1
}

cleanup() {
    if test "${fault_started}" -eq 1; then
        run_libvirt restore >/dev/null 2>&1 || true
        wait_target_ssh >/dev/null 2>&1 || true
        run_audit healthy >/dev/null 2>&1 || true
    fi
    ssh "${jump_options[@]}" \
        "ubuntu@${primary_management_address}" \
        rm -f -- "${remote_audit}" "${remote_reader}" \
        >/dev/null 2>&1 || true
}
trap cleanup EXIT

scp "${jump_options[@]}" \
    "${harness}/guest-ceph-storage-vm-audit.sh" \
    "ubuntu@${primary_management_address}:${remote_audit}"
scp "${jump_options[@]}" \
    "${harness}/guest-stage5-s3-read.py" \
    "ubuntu@${primary_management_address}:${remote_reader}"

run_libvirt preflight
run_audit healthy
run_reader
test "$(vip_owner_count)" -eq 1

fault_started=1
run_libvirt poweroff
if ssh "${jump_options[@]}" \
    "ubuntu@${target_management_address}" true 2>/dev/null; then
    echo "powered-off storage target remains reachable" >&2
    exit 68
fi
run_audit degraded
for _ in $(seq 1 5); do
    degraded_read_evidence="$(run_reader)"
done
printf '%s\n' "${degraded_read_evidence}"
test "$(vip_owner_count)" -eq 1

run_libvirt restore
wait_target_ssh
run_audit healthy
recovered_read_evidence="$(run_reader)"
printf '%s\n' "${recovered_read_evidence}"
test "$(vip_owner_count)" -eq 1
run_libvirt status

fault_started=0
cleanup
trap - EXIT
printf 'storage_vm_failover target=%s degraded_reads=5 vip_owners=1 restored=true\n' \
    "${target_domain}"
