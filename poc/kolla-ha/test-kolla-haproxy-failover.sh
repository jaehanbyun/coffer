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
        echo "refusing an unknown Kolla HAProxy fault action" >&2
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
controller_addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
controller_hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
marker_root="/home/ubuntu/coffer-stage5/kolla-haproxy-fault"
marker="${marker_root}/complete"
marker_value="coffer-stage5-kolla-haproxy-fault-v1"
current_address=""
current_hostname=""
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

field_value() {
    local line="$1"
    local field="$2"

    awk -v field="${field}" '
        {
            for (field_index = 1; field_index <= NF; field_index++) {
                split($field_index, pair, "=")
                if (pair[1] == field) {
                    print pair[2]
                    exit
                }
            }
        }
    ' <<<"${line}"
}

node_preflight_snapshot() {
    local index="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[${index}]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${controller_hostnames[${index}]}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
test "$(hostname)" = "${expected_hostname}"
test "$(systemctl is-active docker)" = active
test "$(docker inspect -f '{{.State.Running}}' haproxy)" = true
test "$(docker inspect -f '{{.State.Health.Status}}' haproxy)" = healthy
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' haproxy)" = no
test "$(docker inspect -f '{{.State.Running}}' keepalived)" = true
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' keepalived)" = no
docker exec keepalived /check_alive.sh >/dev/null
external="$(
    ip -o -4 addr show dev ens5 |
        awk '$4 == "192.168.254.10/32" {count++} END {print count + 0}'
)"
internal="$(
    ip -o -4 addr show dev ens3 |
        awk '$4 == "192.168.252.10/32" {count++} END {print count + 0}'
)"
test "$(ss -H -ltn 'sport = :443' | wc -l)" -eq 1
printf 'host=%s haproxy=healthy keepalived=running check=passed external_vip=%s internal_vip=%s\n' \
    "${expected_hostname}" "${external}" "${internal}"
REMOTE
}

vip_snapshot() {
    local index
    local snapshot
    local external
    local internal
    local external_count=0
    local internal_count=0
    local external_owner=""
    local internal_owner=""

    for index in "${!controller_addresses[@]}"; do
        snapshot="$(
            ssh "${ssh_options[@]}" \
                "ubuntu@${controller_addresses[${index}]}" \
                sudo env LC_ALL=C LANG=C bash -s -- \
                "${controller_hostnames[${index}]}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
test "$(hostname)" = "${expected_hostname}"
external="$(
    ip -o -4 addr show dev ens5 |
        awk '$4 == "192.168.254.10/32" {count++} END {print count + 0}'
)"
internal="$(
    ip -o -4 addr show dev ens3 |
        awk '$4 == "192.168.252.10/32" {count++} END {print count + 0}'
)"
printf 'host=%s external_vip=%s internal_vip=%s\n' \
    "${expected_hostname}" "${external}" "${internal}"
REMOTE
        )"
        external="$(field_value "${snapshot}" external_vip)"
        internal="$(field_value "${snapshot}" internal_vip)"
        case "${external}:${internal}" in
            0:0|1:1)
                ;;
            *)
                echo "internal and external Kolla VIP ownership diverged" >&2
                return 1
                ;;
        esac
        if test "${external}" -eq 1; then
            external_count="$((external_count + 1))"
            external_owner="${controller_hostnames[${index}]}"
        fi
        if test "${internal}" -eq 1; then
            internal_count="$((internal_count + 1))"
            internal_owner="${controller_hostnames[${index}]}"
        fi
    done
    printf 'external_count=%s internal_count=%s external_owner=%s internal_owner=%s\n' \
        "${external_count}" "${internal_count}" \
        "${external_owner:-none}" "${internal_owner:-none}"
}

require_single_vip_owner() {
    local snapshot
    local external_count
    local internal_count
    local external_owner
    local internal_owner

    if ! snapshot="$(vip_snapshot)"; then
        return 1
    fi
    external_count="$(field_value "${snapshot}" external_count)"
    internal_count="$(field_value "${snapshot}" internal_count)"
    external_owner="$(field_value "${snapshot}" external_owner)"
    internal_owner="$(field_value "${snapshot}" internal_owner)"
    if ! test "${external_count}" -eq 1 ||
        ! test "${internal_count}" -eq 1 ||
        ! test "${external_owner}" = "${internal_owner}"; then
        echo "Kolla VIP does not have one shared owner" >&2
        return 1
    fi
    printf '%s\n' "${snapshot}"
}

address_for_hostname() {
    local expected="$1"
    local index

    for index in "${!controller_hostnames[@]}"; do
        if test "${controller_hostnames[${index}]}" = "${expected}"; then
            printf '%s\n' "${controller_addresses[${index}]}"
            return 0
        fi
    done
    echo "refusing a non-controller VIP owner" >&2
    return 64
}

wait_haproxy_healthy() {
    local address="$1"
    local attempt
    local state

    for attempt in {1..90}; do
        state="$(
            ssh "${ssh_options[@]}" "ubuntu@${address}" \
                sudo docker inspect \
                -f '{{.State.Running}}:{{.State.Health.Status}}' \
                haproxy 2>/dev/null || true
        )"
        if test "${state}" = true:healthy; then
            return 0
        fi
        sleep 2
    done
    echo "Kolla HAProxy did not recover healthy" >&2
    return 1
}

wait_keepalived_check() {
    local address="$1"
    local attempt

    for attempt in {1..45}; do
        if ssh "${ssh_options[@]}" "ubuntu@${address}" \
            sudo docker exec keepalived /check_alive.sh >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    echo "Kolla Keepalived HAProxy check did not recover" >&2
    return 1
}

wait_vip_moved() {
    local original_owner="$1"
    local attempt
    local snapshot
    local owner

    for attempt in {1..45}; do
        snapshot="$(vip_snapshot)"
        if test "$(field_value "${snapshot}" external_count)" -eq 1 &&
            test "$(field_value "${snapshot}" internal_count)" -eq 1; then
            owner="$(field_value "${snapshot}" external_owner)"
            if test "${owner}" = "$(field_value "${snapshot}" internal_owner)" &&
                test "${owner}" != "${original_owner}"; then
                printf '%s\n' "${snapshot}"
                return 0
            fi
        fi
        sleep 2
    done
    echo "Kolla VIP did not move to one surviving owner" >&2
    return 1
}

verify_marker() {
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${marker_root}" "${marker}" "${marker_value}" <<'REMOTE'
set -Eeuo pipefail

marker_root="$1"
marker="$2"
marker_value="$3"
if test ! -e "${marker_root}"; then
    printf 'kolla_haproxy_fault_marker state=absent completed=0\n'
    exit 0
fi
test "$(stat -c '%U:%G:%a' "${marker_root}")" = root:root:700
entries="$(find "${marker_root}" -mindepth 1 -maxdepth 1 -printf '%f\n')"
if test -z "${entries}"; then
    printf 'kolla_haproxy_fault_marker state=present completed=0\n'
    exit 0
fi
test "${entries}" = complete
test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
test "$(cat "${marker}")" = "${marker_value}"
printf 'kolla_haproxy_fault_marker state=present completed=1\n'
REMOTE
}

marker_exists() {
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo test -e "${marker}"
}

write_marker() {
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${marker_root}" "${marker}" "${marker_value}" <<'REMOTE'
set -Eeuo pipefail

marker_root="$1"
marker="$2"
marker_value="$3"
install -d -o root -g root -m 0700 "${marker_root}"
temporary="${marker}.tmp.$$"
trap 'rm -f -- "${temporary}"' EXIT
printf '%s\n' "${marker_value}" >"${temporary}"
chown root:root "${temporary}"
chmod 0600 "${temporary}"
mv -f -- "${temporary}" "${marker}"
trap - EXIT
REMOTE
}

restore_current() {
    local rc="$?"

    trap - EXIT
    if test -n "${current_address}"; then
        ssh "${ssh_options[@]}" "ubuntu@${current_address}" \
            sudo docker start haproxy >/dev/null 2>&1 || true
        wait_haproxy_healthy "${current_address}" || true
        wait_keepalived_check "${current_address}" || true
    fi
    exit "${rc}"
}
trap restore_current EXIT

run_outage_probe() {
    local ordinal="$1"
    local convergence_attempt

    for convergence_attempt in 1 2 3; do
        if "${harness}/run-coffer-tenant-acceptance.sh" \
            data-status "${ssh_target}"; then
            printf 'kolla_haproxy_fault outage_probe=%s/3 convergence_attempt=%s result=passed\n' \
                "${ordinal}" "${convergence_attempt}"
            return 0
        fi
        sleep 2
    done
    echo "Kolla HAProxy survivor path did not converge" >&2
    return 1
}

preflight() {
    local index
    local snapshot
    local vip

    "${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
    for index in "${!controller_addresses[@]}"; do
        snapshot="$(node_preflight_snapshot "${index}")"
        printf 'kolla_haproxy_fault_node %s\n' "${snapshot}"
    done
    if ! vip="$(require_single_vip_owner)"; then
        echo "Kolla HAProxy fault preflight rejected VIP ownership" >&2
        return 1
    fi
    printf 'kolla_haproxy_fault_vip %s\n' "${vip}"
    verify_marker
    printf 'kolla_haproxy_fault action=preflight result=passed mutations=none\n'
}

preflight
if test "${action}" = preflight; then
    trap - EXIT
    exit 0
fi
if marker_exists; then
    trap - EXIT
    printf 'kolla_haproxy_fault action=run result=passed idempotent=yes\n'
    exit 0
fi

if ! baseline="$(require_single_vip_owner)"; then
    echo "Kolla HAProxy fault rejected VIP ownership before stop" >&2
    exit 1
fi
current_hostname="$(field_value "${baseline}" external_owner)"
current_address="$(address_for_hostname "${current_hostname}")"
ssh "${ssh_options[@]}" "ubuntu@${current_address}" \
    sudo docker stop --time 15 haproxy >/dev/null
test "$(
    ssh "${ssh_options[@]}" "ubuntu@${current_address}" \
        sudo docker inspect -f '{{.State.Running}}' haproxy
)" = false
moved="$(wait_vip_moved "${current_hostname}")"
printf 'kolla_haproxy_fault vip_moved from=%s to=%s result=passed\n' \
    "${current_hostname}" "$(field_value "${moved}" external_owner)"

for attempt in 1 2 3; do
    run_outage_probe "${attempt}"
done

ssh "${ssh_options[@]}" "ubuntu@${current_address}" \
    sudo docker start haproxy >/dev/null
wait_haproxy_healthy "${current_address}"
wait_keepalived_check "${current_address}"
current_address=""
current_hostname=""
"${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
final_vip="$(require_single_vip_owner)"
write_marker
preflight
trap - EXIT
printf 'kolla_haproxy_fault action=run result=passed outage_probes=3 final_owner=%s restored=healthy\n' \
    "$(field_value "${final_vip}" external_owner)"
