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
        echo "refusing an unknown Coffer service fault action" >&2
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
services=(
    coffer_api
    coffer_edge
    coffer_registry
)
marker_root="/home/ubuntu/coffer-stage5/service-faults"
marker_value="coffer-stage5-service-fault-v1"
target_address="${controller_addresses[2]}"
current_service=""
ssh_options=(
    -J "${ssh_target}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=20
    -o ServerAliveCountMax=6
    -o StrictHostKeyChecking=accept-new
    -o UserKnownHostsFile="${known_hosts}"
)

remote_snapshot() {
    local index="$1"

    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[${index}]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${controller_hostnames[${index}]}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
test "$(hostname)" = "${expected_hostname}"
test "$(systemctl is-active docker)" = active
for container in coffer_api coffer_edge coffer_registry; do
    test "$(docker inspect -f '{{.State.Running}}' "${container}")" = true
    test "$(docker inspect -f '{{.State.Health.Status}}' "${container}")" = healthy
    test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${container}")" = no
done
printf 'host=%s containers=3 running=3 healthy=3\n' "${expected_hostname}"
REMOTE
}

marker_path() {
    case "$1" in
        coffer_api|coffer_edge|coffer_registry)
            ;;
        *)
            echo "refusing a non-Coffer service marker" >&2
            return 64
            ;;
    esac
    printf '%s/%s.complete\n' "${marker_root}" "$1"
}

verify_markers() {
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${marker_root}" "${marker_value}" <<'REMOTE'
set -Eeuo pipefail

marker_root="$1"
marker_value="$2"
allowed='coffer_api.complete|coffer_edge.complete|coffer_registry.complete'
if test ! -e "${marker_root}"; then
    printf 'service_fault_markers state=absent completed=0\n'
    exit 0
fi
test "$(stat -c '%U:%G:%a' "${marker_root}")" = root:root:700
entries="$(
    find "${marker_root}" -mindepth 1 -maxdepth 1 -printf '%f\n' |
        LC_ALL=C sort
)"
if test -n "${entries}"; then
    grep -Ev "^(${allowed})$" <<<"${entries}" | grep -q . && exit 1
fi
completed=0
while IFS= read -r entry; do
    test -n "${entry}" || continue
    marker="${marker_root}/${entry}"
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${marker_value}"
    completed="$((completed + 1))"
done <<<"${entries}"
printf 'service_fault_markers state=present completed=%s\n' "${completed}"
REMOTE
}

wait_target_healthy() {
    local service="$1"
    local attempt
    local state

    for attempt in {1..90}; do
        state="$(
            ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
                sudo docker inspect \
                -f '{{.State.Running}}|{{.State.Health.Status}}' \
                "${service}" 2>/dev/null || true
        )"
        if test "${state}" = "true|healthy"; then
            return 0
        fi
        sleep 2
    done
    echo "Coffer service did not recover healthy" >&2
    return 1
}

restore_current() {
    local rc="$?"

    trap - EXIT
    if test -n "${current_service}"; then
        ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
            sudo docker start "${current_service}" >/dev/null 2>&1 || true
        wait_target_healthy "${current_service}" || true
    fi
    exit "${rc}"
}
trap restore_current EXIT

preflight() {
    local index
    local snapshot

    "${harness}/run-coffer-tenant-acceptance.sh" \
        status "${ssh_target}"
    for index in "${!controller_addresses[@]}"; do
        snapshot="$(remote_snapshot "${index}")"
        printf 'coffer_service_fault_node %s\n' "${snapshot}"
    done
    verify_markers
    printf 'coffer_service_fault action=preflight result=passed target=%s mutations=none\n' \
        "${controller_hostnames[2]}"
}

write_marker() {
    local service="$1"
    local marker

    marker="$(marker_path "${service}")"
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo env LC_ALL=C LANG=C bash -s -- \
        "${marker}" "${marker_value}" <<'REMOTE'
set -Eeuo pipefail

marker="$1"
marker_value="$2"
temporary="${marker}.tmp.$$"
trap 'rm -f -- "${temporary}"' EXIT
printf '%s\n' "${marker_value}" >"${temporary}"
chown root:root "${temporary}"
chmod 0600 "${temporary}"
mv -f -- "${temporary}" "${marker}"
trap - EXIT
REMOTE
}

marker_exists() {
    ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
        sudo test -e "$(marker_path "$1")"
}

run_outage_probe() {
    local service="$1"
    local ordinal="$2"
    local convergence_attempt

    for convergence_attempt in 1 2 3; do
        if "${harness}/run-coffer-tenant-acceptance.sh" \
            data-status "${ssh_target}"; then
            printf 'coffer_service_fault service=%s outage_probe=%s/3 convergence_attempt=%s result=passed\n' \
                "${service}" "${ordinal}" "${convergence_attempt}"
            return 0
        fi
        sleep 2
    done
    echo "surviving Coffer path did not converge" >&2
    return 1
}

preflight
if test "${action}" = preflight; then
    trap - EXIT
    exit 0
fi

ssh "${ssh_options[@]}" "ubuntu@${controller_addresses[0]}" \
    sudo install -d -o root -g root -m 0700 "${marker_root}"

for service in "${services[@]}"; do
    if marker_exists "${service}"; then
        printf 'coffer_service_fault service=%s result=passed idempotent=yes\n' \
            "${service}"
        continue
    fi
    current_service="${service}"
    ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
        sudo docker stop --time 15 "${service}" >/dev/null
    test "$(
        ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
            sudo docker inspect -f '{{.State.Running}}' "${service}"
    )" = false
    for attempt in 1 2 3; do
        run_outage_probe "${service}" "${attempt}"
    done
    ssh "${ssh_options[@]}" "ubuntu@${target_address}" \
        sudo docker start "${service}" >/dev/null
    wait_target_healthy "${service}"
    current_service=""
    "${harness}/run-coffer-tenant-acceptance.sh" \
        status "${ssh_target}"
    write_marker "${service}"
    printf 'coffer_service_fault service=%s result=passed restored=healthy probes=3\n' \
        "${service}"
done

preflight
test "$(verify_markers | tail -n 1)" = \
    "service_fault_markers state=present completed=3"
trap - EXIT
printf 'coffer_service_fault action=run result=passed services=3 outage_probes=9 restored=healthy\n'
