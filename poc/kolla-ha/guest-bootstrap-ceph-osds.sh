#!/usr/bin/env bash

set -Eeuo pipefail

primary_hostname="coffer-rgw-ha-stage5-storage-1"
hostnames=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)
device_path="/dev/vdb"
device_size_bytes=68719476736

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f /etc/ceph/coffer-stage5-release.txt
grep -Fqx 'release=20.2.2' /etc/ceph/coffer-stage5-release.txt

host_document="$(
    cephadm shell -- ceph orch host ls --format json </dev/null
)"
test "$(jq 'length' <<<"${host_document}")" -eq 3
test "$(
    jq '[.[] | select(
        (
            .hostname == "coffer-rgw-ha-stage5-storage-1" or
            .hostname == "coffer-rgw-ha-stage5-storage-2" or
            .hostname == "coffer-rgw-ha-stage5-storage-3"
        ) and .status == ""
    )] | length' <<<"${host_document}"
)" -eq 3
test "$(
    cephadm shell -- ceph quorum_status --format json </dev/null |
        jq '.quorum_names | length'
)" -eq 3
test "$(
    cephadm shell -- ceph orch ps --daemon_type mgr --format json \
        </dev/null |
        jq '[.[] | select(.status_desc == "running")] | length'
)" -eq 2
test "$(
    cephadm shell -- ceph orch ls --format json </dev/null |
        jq '[.[] | select(.service_type == "rgw")] | length'
)" -eq 0

config_document="$(
    cephadm shell -- ceph config dump --format json </dev/null
)"
for pair in \
    osd_pool_default_size:3 \
    osd_pool_default_min_size:2 \
    mon_target_pg_per_osd:50; do
    option_name="${pair%%:*}"
    option_value="${pair##*:}"
    test "$(
        jq -r --arg name "${option_name}" \
            '[.[] | select(
                .section == "global" and .name == $name
            )][0].value' <<<"${config_document}"
    )" = "${option_value}"
done

for _ in $(seq 1 120); do
    osd_document="$(
        cephadm shell -- ceph osd metadata --format json </dev/null
    )"
    osd_count="$(
        cephadm shell -- ceph osd stat --format json </dev/null |
            jq -r '.num_osds'
    )"
    if test "$(jq 'length' <<<"${osd_document}")" -eq "${osd_count}"; then
        break
    fi
    sleep 2
done
test "$(jq 'length' <<<"${osd_document}")" -eq "${osd_count}"
test "${osd_count}" -le 3
test "$(
    jq '[.[] | select(
        .hostname != "coffer-rgw-ha-stage5-storage-1" and
        .hostname != "coffer-rgw-ha-stage5-storage-2" and
        .hostname != "coffer-rgw-ha-stage5-storage-3"
    )] | length' <<<"${osd_document}"
)" -eq 0
test "$(
    jq 'group_by(.hostname) | map(select(length > 1)) | length' \
        <<<"${osd_document}"
)" -eq 0

for storage_hostname in "${hostnames[@]}"; do
    host_osd_count="$(
        jq --arg host "${storage_hostname}" \
            '[.[] | select(.hostname == $host)] | length' \
            <<<"${osd_document}"
    )"
    test "${host_osd_count}" -le 1
    if test "${host_osd_count}" -eq 0; then
        device_document="$(
            cephadm shell -- ceph orch device ls --refresh --format json \
                </dev/null
        )"
        candidate="$(
            jq -c \
                --arg host "${storage_hostname}" \
                --arg path "${device_path}" \
                '[.[] | select(.name == $host) | .devices[] |
                    select(.path == $path)]' \
                <<<"${device_document}"
        )"
        test "$(jq 'length' <<<"${candidate}")" -eq 1
        test "$(jq -r '.[0].available' <<<"${candidate}")" = true
        test "$(jq '.[0].rejected_reasons | length' <<<"${candidate}")" -eq 0
        test "$(
            jq -r '.[0].sys_api.size | floor' <<<"${candidate}"
        )" -eq "${device_size_bytes}"

        cephadm shell -- ceph orch daemon add osd \
            "${storage_hostname}:${device_path}" </dev/null

        for _ in $(seq 1 180); do
            osd_document="$(
                cephadm shell -- ceph osd metadata --format json </dev/null
            )"
            host_osd_count="$(
                jq --arg host "${storage_hostname}" \
                    '[.[] | select(.hostname == $host)] | length' \
                    <<<"${osd_document}"
            )"
            running_host_osds="$(
                cephadm shell -- ceph orch ps --daemon_type osd \
                    --format json </dev/null |
                    jq --arg host "${storage_hostname}" \
                        '[.[] | select(
                            .hostname == $host and
                            .status_desc == "running"
                        )] | length'
            )"
            if test "${host_osd_count}" -eq 1 &&
                test "${running_host_osds}" -eq 1; then
                break
            fi
            sleep 2
        done
        test "${host_osd_count}" -eq 1
        test "${running_host_osds}" -eq 1
    fi
done

for _ in $(seq 1 180); do
    osd_status="$(
        cephadm shell -- ceph osd stat --format json </dev/null
    )"
    osd_document="$(
        cephadm shell -- ceph osd metadata --format json </dev/null
    )"
    running_osds="$(
        cephadm shell -- ceph orch ps --daemon_type osd --format json \
            </dev/null |
            jq '[.[] | select(.status_desc == "running")] | length'
    )"
    health_status="$(
        cephadm shell -- ceph status --format json </dev/null |
            jq -r '.health.status'
    )"
    if test "$(jq -r '.num_osds' <<<"${osd_status}")" -eq 3 &&
        test "$(jq -r '.num_up_osds' <<<"${osd_status}")" -eq 3 &&
        test "$(jq -r '.num_in_osds' <<<"${osd_status}")" -eq 3 &&
        test "${running_osds}" -eq 3 &&
        test "${health_status}" = HEALTH_OK; then
        break
    fi
    sleep 2
done

test "$(jq -r '.num_osds' <<<"${osd_status}")" -eq 3
test "$(jq -r '.num_up_osds' <<<"${osd_status}")" -eq 3
test "$(jq -r '.num_in_osds' <<<"${osd_status}")" -eq 3
test "${running_osds}" -eq 3
test "${health_status}" = HEALTH_OK
test "$(
    jq -r '[.[].hostname] | sort | join(",")' <<<"${osd_document}"
)" = "$(
    printf '%s\n' "${hostnames[@]}" | sort | paste -sd, -
)"
test "$(
    cephadm shell -- ceph orch ls --format json </dev/null |
        jq '[.[] | select(.service_type == "rgw")] | length'
)" -eq 0

printf 'ceph_osds hosts=3 osds=3 up=3 in=3 health=%s rgw=0\n' \
    "${health_status}"
