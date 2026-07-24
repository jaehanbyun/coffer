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
        echo "refusing an unknown Kolla Galera fault action" >&2
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
target_address="${controller_addresses[2]}"
target_hostname="${controller_hostnames[2]}"
marker_root="/home/ubuntu/coffer-stage5/kolla-galera-fault"
marker="${marker_root}/complete"
marker_value="coffer-stage5-kolla-galera-fault-v1"
current_fault=0
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

node_snapshot() {
    local index="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[${index}]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${controller_hostnames[${index}]}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
test "$(hostname)" = "${expected_hostname}"
test "$(systemctl is-active docker)" = active
for container in mariadb proxysql; do
    test "$(docker inspect -f '{{.State.Running}}' "${container}")" = true
    test "$(docker inspect -f '{{.State.Paused}}' "${container}")" = false
    test "$(docker inspect -f '{{.State.Health.Status}}' "${container}")" = healthy
    test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${container}")" = no
done
printf 'host=%s mariadb=healthy proxysql=healthy restart=no\n' \
    "${expected_hostname}"
REMOTE
}

database_snapshot() {
    local expected_state="$1"

    case "${expected_state}" in
        healthy|degraded)
            ;;
        *)
            echo "refusing an unknown expected database state" >&2
            return 64
            ;;
    esac
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo env LC_ALL=C LANG=C bash -s -- "${expected_state}" \
        <"${harness}/guest-check-kolla-galera.sh"
}

wait_database_state() {
    local expected_state="$1"
    local attempts="$2"
    local attempt
    local snapshot

    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if snapshot="$(database_snapshot "${expected_state}" 2>/dev/null)"; then
            printf '%s\n' "${snapshot}"
            return 0
        fi
        sleep 2
    done
    echo "Galera and ProxySQL did not reach the expected state" >&2
    return 1
}

wait_target_healthy() {
    local attempt
    local state

    for attempt in {1..300}; do
        state="$(
            ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
                sudo docker inspect \
                -f '{{.State.Running}}:{{.State.Paused}}:{{.State.Health.Status}}' \
                mariadb 2>/dev/null || true
        )"
        if test "${state}" = true:false:healthy; then
            return 0
        fi
        sleep 2
    done
    echo "target MariaDB did not recover healthy" >&2
    return 1
}

run_database_probe() {
    local ordinal="$1"
    local convergence_attempt

    for convergence_attempt in 1 2 3; do
        if "${harness}/run-coffer-tenant-acceptance.sh" \
            database-status "${ssh_target}"; then
            printf 'kolla_galera_fault database_probe=%s/3 convergence_attempt=%s result=passed\n' \
                "${ordinal}" "${convergence_attempt}"
            return 0
        fi
        sleep 2
    done
    echo "surviving Galera write/read path did not converge" >&2
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
    printf 'kolla_galera_fault_marker state=absent completed=0\n'
    exit 0
fi
test "$(stat -c '%U:%G:%a' "${marker_root}")" = root:root:700
entries="$(find "${marker_root}" -mindepth 1 -maxdepth 1 -printf '%f\n')"
if test -z "${entries}"; then
    printf 'kolla_galera_fault_marker state=present completed=0\n'
    exit 0
fi
test "${entries}" = complete
test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
test "$(cat "${marker}")" = "${marker_value}"
printf 'kolla_galera_fault_marker state=present completed=1\n'
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

restore_target() {
    local rc="$?"

    trap - EXIT
    if test "${current_fault}" -eq 1; then
        ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
            sudo docker unpause mariadb >/dev/null 2>&1 || true
        wait_target_healthy || true
        wait_database_state healthy 300 || true
    fi
    exit "${rc}"
}
trap restore_target EXIT

preflight() {
    local index
    local snapshot

    "${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
    for index in "${!controller_addresses[@]}"; do
        snapshot="$(node_snapshot "${index}")"
        printf 'kolla_galera_fault_node %s\n' "${snapshot}"
    done
    database_snapshot healthy
    verify_marker
    printf 'kolla_galera_fault action=preflight result=passed target=%s mutations=none\n' \
        "${target_hostname}"
}

preflight
if test "${action}" = preflight; then
    trap - EXIT
    exit 0
fi
if marker_exists; then
    trap - EXIT
    printf 'kolla_galera_fault action=run result=passed idempotent=yes\n'
    exit 0
fi

current_fault=1
ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
    sudo docker pause mariadb >/dev/null
test "$(
    ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
        sudo docker inspect -f '{{.State.Running}}:{{.State.Paused}}' mariadb
)" = true:true
wait_database_state degraded 90
for attempt in 1 2 3; do
    run_database_probe "${attempt}"
done

ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
    sudo docker unpause mariadb >/dev/null
wait_target_healthy
wait_database_state healthy 300
current_fault=0
"${harness}/run-coffer-tenant-acceptance.sh" status "${ssh_target}"
write_marker
preflight
trap - EXIT
printf 'kolla_galera_fault action=run result=passed database_probes=3 target=%s restored=synced\n' \
    "${target_hostname}"
