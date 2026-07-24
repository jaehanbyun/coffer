#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {healthy|degraded}" >&2
    exit 64
fi

action="$1"
primary_hostname="coffer-rgw-ha-stage5-storage-1"
healthy_quorum="$(
    printf '%s\n' \
        coffer-rgw-ha-stage5-storage-1 \
        coffer-rgw-ha-stage5-storage-2 \
        coffer-rgw-ha-stage5-storage-3
)"
degraded_quorum="$(
    printf '%s\n' \
        coffer-rgw-ha-stage5-storage-1 \
        coffer-rgw-ha-stage5-storage-2
)"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"

case "${action}" in
    healthy)
        expected_quorum="${healthy_quorum}"
        expected_up_osds=3
        expected_running_rgw=3
        expected_health=HEALTH_OK
        ;;
    degraded)
        expected_quorum="${degraded_quorum}"
        expected_up_osds=2
        expected_running_rgw=2
        expected_health=HEALTH_WARN
        ;;
    *)
        echo "refusing an unknown storage VM audit action" >&2
        exit 64
        ;;
esac

health_status=UNKNOWN
quorum_names=
num_osds=0
up_osds=0
in_osds=0
running_rgw=0
running_haproxy=0
running_keepalived=0
inactive_pgs=1
unclean_pgs=1

for _ in $(seq 1 180); do
    quorum_names="$(
        cephadm shell -- ceph quorum_status --format json \
            </dev/null 2>/dev/null |
            jq -r '.quorum_names | sort | .[]'
    )"
    osd_status="$(
        cephadm shell -- ceph osd stat --format json \
            </dev/null 2>/dev/null
    )"
    num_osds="$(jq '.num_osds' <<<"${osd_status}")"
    up_osds="$(jq '.num_up_osds' <<<"${osd_status}")"
    in_osds="$(jq '.num_in_osds' <<<"${osd_status}")"
    daemon_status="$(
        cephadm shell -- ceph orch ps --refresh --format json \
            </dev/null 2>/dev/null
    )"
    running_rgw="$(
        jq '[.[] | select(
            .service_name == "rgw.coffer" and
            .daemon_type == "rgw" and
            .status_desc == "running"
        )] | length' <<<"${daemon_status}"
    )"
    running_haproxy="$(
        jq '[.[] | select(
            .service_name == "ingress.rgw.coffer" and
            .daemon_type == "haproxy" and
            .status_desc == "running"
        )] | length' <<<"${daemon_status}"
    )"
    running_keepalived="$(
        jq '[.[] | select(
            .service_name == "ingress.rgw.coffer" and
            .daemon_type == "keepalived" and
            .status_desc == "running"
        )] | length' <<<"${daemon_status}"
    )"
    pg_status="$(
        cephadm shell -- ceph pg stat --format json \
            </dev/null 2>/dev/null
    )"
    inactive_pgs="$(
        jq '[.pg_summary.num_pg_by_state[]? |
            select((.name | split("+") | index("active")) == null) |
            .num] | add // 0' <<<"${pg_status}"
    )"
    unclean_pgs="$(
        jq '[.pg_summary.num_pg_by_state[]? |
            select(.name != "active+clean") |
            .num] | add // 0' <<<"${pg_status}"
    )"
    health_status="$(
        cephadm shell -- ceph status --format json </dev/null 2>/dev/null |
            jq -r '.health.status'
    )"

    if test "${quorum_names}" = "${expected_quorum}" &&
        test "${num_osds}" -eq 3 &&
        test "${up_osds}" -eq "${expected_up_osds}" &&
        test "${in_osds}" -eq 3 &&
        test "${running_rgw}" -eq "${expected_running_rgw}" &&
        test "${running_haproxy}" -eq 2 &&
        test "${running_keepalived}" -eq 2 &&
        test "${inactive_pgs}" -eq 0 &&
        test "${health_status}" = "${expected_health}"; then
        if test "${action}" = degraded ||
            test "${unclean_pgs}" -eq 0; then
            break
        fi
    fi
    sleep 2
done

test "${quorum_names}" = "${expected_quorum}"
test "${num_osds}" -eq 3
test "${up_osds}" -eq "${expected_up_osds}"
test "${in_osds}" -eq 3
test "${running_rgw}" -eq "${expected_running_rgw}"
test "${running_haproxy}" -eq 2
test "${running_keepalived}" -eq 2
test "${inactive_pgs}" -eq 0
test "${health_status}" = "${expected_health}"
if test "${action}" = healthy; then
    test "${unclean_pgs}" -eq 0
else
    test "${unclean_pgs}" -gt 0
fi

printf 'storage_vm_audit state=%s quorum=%s osds_up=%s/3 rgw=%s ingress=2 inactive_pgs=0 unclean_pgs=%s health=%s\n' \
    "${action}" "$(wc -l <<<"${quorum_names}" | tr -d ' ')" \
    "${up_osds}" "${running_rgw}" "${unclean_pgs}" "${health_status}"
