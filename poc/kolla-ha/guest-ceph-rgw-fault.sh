#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -lt 2 || "$#" -gt 3 ]]; then
    echo "usage: $0 ACTION READ_HELPER [INGRESS_HOST]" >&2
    exit 64
fi

action="$1"
read_helper="$2"
ingress_host="${3:-}"
primary_hostname="coffer-rgw-ha-stage5-storage-1"
rgw_fault_host="coffer-rgw-ha-stage5-storage-3"
ingress_hosts=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
)
all_hosts=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)
registry_state="/etc/coffer-stage5-rgw/registry-user.json"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f "${read_helper}"
test -f "${registry_state}"

orch_ps() {
    cephadm shell -- ceph orch ps --refresh --format json </dev/null 2>/dev/null
}

service_rows() {
    local service="$1"

    orch_ps | jq -c --arg service "${service}" \
        '[.[] | select(.service_name == $service)]'
}

daemon_name() {
    local daemon_type="$1"
    local hostname="$2"
    local service="$3"
    local rows
    local names

    rows="$(service_rows "${service}")"
    mapfile -t names < <(
        jq -r \
            --arg daemon_type "${daemon_type}" \
            --arg hostname "${hostname}" \
            '.[] |
             select(
                .daemon_type == $daemon_type and
                .hostname == $hostname
             ) |
             .daemon_name' <<<"${rows}"
    )
    test "${#names[@]}" -eq 1
    case "${daemon_type}" in
        rgw)
            [[ "${names[0]}" =~ ^rgw\.coffer\.${hostname}\.[a-z]{6}$ ]]
            ;;
        haproxy|keepalived)
            [[ "${names[0]}" =~ ^${daemon_type}\.rgw\.coffer\.${hostname}\.[a-z]{6}$ ]]
            ;;
        *)
            return 1
            ;;
    esac
    printf '%s\n' "${names[0]}"
}

daemon_status() {
    local daemon_type="$1"
    local hostname="$2"
    local service="$3"
    local name

    name="$(daemon_name "${daemon_type}" "${hostname}" "${service}")"
    service_rows "${service}" |
        jq -r --arg name "${name}" \
            '.[] | select(.daemon_name == $name) | .status_desc'
}

validate_inventory() {
    local rows
    local hostname
    local daemon_type

    rows="$(service_rows rgw.coffer)"
    test "$(jq 'length' <<<"${rows}")" -eq 3
    for hostname in "${all_hosts[@]}"; do
        daemon_name rgw "${hostname}" rgw.coffer >/dev/null
    done

    rows="$(service_rows ingress.rgw.coffer)"
    test "$(jq 'length' <<<"${rows}")" -eq 4
    for hostname in "${ingress_hosts[@]}"; do
        for daemon_type in haproxy keepalived; do
            daemon_name \
                "${daemon_type}" "${hostname}" ingress.rgw.coffer \
                >/dev/null
        done
    done
}

running_count() {
    local service="$1"
    local daemon_type="$2"

    service_rows "${service}" |
        jq --arg daemon_type "${daemon_type}" \
            '[.[] | select(
                .daemon_type == $daemon_type and
                .status_desc == "running"
            )] | length'
}

wait_running_count() {
    local service="$1"
    local daemon_type="$2"
    local expected="$3"
    local current=0

    for _ in $(seq 1 90); do
        current="$(running_count "${service}" "${daemon_type}")"
        if test "${current}" -eq "${expected}"; then
            break
        fi
        sleep 2
    done
    test "${current}" -eq "${expected}"
}

wait_daemon_not_running() {
    local daemon_type="$1"
    local hostname="$2"
    local service="$3"
    local status=running

    for _ in $(seq 1 60); do
        status="$(daemon_status "${daemon_type}" "${hostname}" "${service}")"
        if test "${status}" != running; then
            break
        fi
        sleep 2
    done
    test "${status}" != running
}

wait_health() {
    local health_status=UNKNOWN
    local inactive_pgs=1

    for _ in $(seq 1 120); do
        health_status="$(
            cephadm shell -- ceph status --format json </dev/null 2>/dev/null |
                jq -r '.health.status'
        )"
        inactive_pgs="$(
            cephadm shell -- ceph pg stat --format json </dev/null 2>/dev/null |
                jq '[.pg_summary.num_pg_by_state[]? |
                    select(.name != "active+clean") | .num] | add // 0'
        )"
        if test "${health_status}" = HEALTH_OK &&
            test "${inactive_pgs}" -eq 0; then
            break
        fi
        sleep 2
    done
    test "${health_status}" = HEALTH_OK
    test "${inactive_pgs}" -eq 0
}

verify_healthy() {
    validate_inventory
    wait_running_count rgw.coffer rgw 3
    wait_running_count ingress.rgw.coffer haproxy 2
    wait_running_count ingress.rgw.coffer keepalived 2
    wait_health
}

start_if_needed() {
    local daemon_type="$1"
    local hostname="$2"
    local service="$3"
    local name

    if test "$(daemon_status "${daemon_type}" "${hostname}" "${service}")" != \
        running; then
        name="$(daemon_name "${daemon_type}" "${hostname}" "${service}")"
        cephadm shell -- ceph orch daemon start "${name}" \
            </dev/null >/dev/null 2>&1
    fi
}

restore_rgw() {
    local hostname

    validate_inventory
    for hostname in "${all_hosts[@]}"; do
        start_if_needed rgw "${hostname}" rgw.coffer
    done
    wait_running_count rgw.coffer rgw 3
}

restore_ingress() {
    local hostname

    validate_inventory
    for hostname in "${ingress_hosts[@]}"; do
        start_if_needed haproxy "${hostname}" ingress.rgw.coffer
    done
    wait_running_count ingress.rgw.coffer haproxy 2
    for hostname in "${ingress_hosts[@]}"; do
        start_if_needed keepalived "${hostname}" ingress.rgw.coffer
    done
    wait_running_count ingress.rgw.coffer keepalived 2
}

case "${action}" in
    preflight|verify)
        test -z "${ingress_host}"
        verify_healthy
        printf 'rgw_fault state=healthy rgw=3 haproxy=2 keepalived=2\n'
        ;;
    stop-rgw)
        test -z "${ingress_host}"
        verify_healthy
        rgw_name="$(daemon_name rgw "${rgw_fault_host}" rgw.coffer)"
        cephadm shell -- ceph orch daemon stop "${rgw_name}" \
            </dev/null >/dev/null 2>&1
        wait_daemon_not_running rgw "${rgw_fault_host}" rgw.coffer
        wait_running_count rgw.coffer rgw 2
        printf 'rgw_fault phase=rgw target=%s running=2\n' "${rgw_fault_host}"
        ;;
    restore-rgw)
        test -z "${ingress_host}"
        restore_rgw
        wait_health
        printf 'rgw_fault phase=rgw restored=3 health=HEALTH_OK\n'
        ;;
    stop-ingress)
        case "${ingress_host}" in
            "${ingress_hosts[0]}"|"${ingress_hosts[1]}") ;;
            *)
                echo "refusing a non-ingress fault host" >&2
                exit 65
                ;;
        esac
        verify_healthy
        keepalived_name="$(
            daemon_name keepalived "${ingress_host}" ingress.rgw.coffer
        )"
        haproxy_name="$(
            daemon_name haproxy "${ingress_host}" ingress.rgw.coffer
        )"
        cephadm shell -- ceph orch daemon stop "${keepalived_name}" \
            </dev/null >/dev/null 2>&1
        wait_daemon_not_running \
            keepalived "${ingress_host}" ingress.rgw.coffer
        cephadm shell -- ceph orch daemon stop "${haproxy_name}" \
            </dev/null >/dev/null 2>&1
        wait_daemon_not_running haproxy "${ingress_host}" ingress.rgw.coffer
        wait_running_count ingress.rgw.coffer keepalived 1
        wait_running_count ingress.rgw.coffer haproxy 1
        printf 'rgw_fault phase=ingress target=%s surviving_pairs=1\n' \
            "${ingress_host}"
        ;;
    restore-ingress)
        test -z "${ingress_host}"
        restore_ingress
        wait_health
        printf 'rgw_fault phase=ingress restored=2 health=HEALTH_OK\n'
        ;;
    restore-all)
        test -z "${ingress_host}"
        restore_rgw
        restore_ingress
        wait_health
        printf 'rgw_fault restored=all health=HEALTH_OK\n'
        ;;
    *)
        echo "refusing an unknown fault action" >&2
        exit 64
        ;;
esac
