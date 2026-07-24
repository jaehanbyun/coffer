#!/usr/bin/env bash

set -Eeuo pipefail

primary_hostname="coffer-rgw-ha-stage5-storage-1"
hostnames=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)
addresses=(
    192.168.253.31
    192.168.253.32
    192.168.253.33
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f /etc/ceph/coffer-stage5-release.txt
grep -Fqx 'release=20.2.2' /etc/ceph/coffer-stage5-release.txt

host_document="$(
    cephadm shell -- ceph orch host ls --format json </dev/null
)"
for index in "${!hostnames[@]}"; do
    storage_hostname="${hostnames[$index]}"
    storage_address="${addresses[$index]}"
    registered_address="$(
        printf '%s' "${host_document}" |
            jq -r --arg host "${storage_hostname}" \
                '.[] | select(.hostname == $host) | .addr'
    )"
    if test -z "${registered_address}"; then
        cephadm shell -- ceph orch host add \
            "${storage_hostname}" "${storage_address}" </dev/null
    else
        test "${registered_address}" = "${storage_address}"
    fi
done

for storage_hostname in "${hostnames[@]}"; do
    for label in mon mgr rgw osd; do
        cephadm shell -- ceph orch host label add \
            "${storage_hostname}" "${label}" </dev/null
    done
done

mon_placement="$(
    IFS=,
    printf '%s' "${hostnames[*]}"
)"
mgr_placement="$(
    IFS=,
    printf '%s' "${hostnames[0]},${hostnames[1]}"
)"
cephadm shell -- ceph orch apply mon \
    --placement="${mon_placement}" --dry-run --format json-pretty \
    </dev/null >/dev/null
cephadm shell -- ceph orch apply mgr \
    --placement="${mgr_placement}" --dry-run --format json-pretty \
    </dev/null >/dev/null
cephadm shell -- ceph orch apply mon --placement="${mon_placement}" </dev/null
cephadm shell -- ceph orch apply mgr --placement="${mgr_placement}" </dev/null

for _ in $(seq 1 180); do
    quorum_count="$(
        cephadm shell -- ceph quorum_status --format json \
            </dev/null 2>/dev/null |
            jq '.quorum_names | length' 2>/dev/null || true
    )"
    running_mgrs="$(
        cephadm shell -- ceph orch ps --daemon_type mgr --format json \
            </dev/null |
            jq '[.[] | select(.status_desc == "running")] | length'
    )"
    if test "${quorum_count:-0}" -eq 3 &&
        test "${running_mgrs}" -eq 2; then
        break
    fi
    sleep 2
done
test "${quorum_count:-0}" -eq 3
test "${running_mgrs}" -eq 2

host_document="$(
    cephadm shell -- ceph orch host ls --format json </dev/null
)"
test "$(
    printf '%s' "${host_document}" |
        jq '[.[] | select(
            .hostname == "coffer-rgw-ha-stage5-storage-1" or
            .hostname == "coffer-rgw-ha-stage5-storage-2" or
            .hostname == "coffer-rgw-ha-stage5-storage-3"
        )] | length'
)" -eq 3
test "$(
    printf '%s' "${host_document}" |
        jq '[.[] | select(.status != "")] | length'
)" -eq 0
test "$(
    cephadm shell -- ceph osd stat --format json </dev/null |
        jq -r '.num_osds'
)" -eq 0
test "$(
    cephadm shell -- ceph orch ls --format json </dev/null |
        jq '[.[] | select(.service_type == "rgw")] | length'
)" -eq 0

printf 'ceph_control hosts=3 mons=%s mgrs=%s osds=0 rgw=0\n' \
    "${quorum_count}" "${running_mgrs}"
