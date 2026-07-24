#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|cleanup}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status|cleanup)
        ;;
    *)
        echo "refusing an unknown Ceph S3 cleanup action" >&2
        exit 64
        ;;
esac

primary_hostname="coffer-rgw-ha-stage5-storage-1"
state_directory="/etc/coffer-stage5-rgw"
registry_uid="coffer-stage5-registry"
denial_uid="coffer-stage5-denial"
registry_state="${state_directory}/registry-user.json"
denial_state="${state_directory}/denial-user.json"
distribution_env="${state_directory}/distribution.env"
registry_bucket="coffer-stage5-registry"
denial_bucket="coffer-stage5-denial"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"

ceph_json() {
    cephadm shell -- "$@" --format json </dev/null
}

require_cluster_healthy() {
    test "$(
        ceph_json ceph status |
            jq -r '.health.status'
    )" = HEALTH_OK
    test "$(
        ceph_json ceph orch ps --service_name rgw.coffer |
            jq '[.[] | select(
                .daemon_type == "rgw" and .status_desc == "running"
            )] | length'
    )" -eq 3
    test "$(
        ceph_json ceph orch ps --service_name ingress.rgw.coffer |
            jq '[.[] | select(
                .daemon_type == "haproxy" and .status_desc == "running"
            )] | length'
    )" -eq 2
}

user_list() {
    ceph_json radosgw-admin user list | jq -r 'sort | .[]'
}

bucket_list() {
    ceph_json radosgw-admin bucket list | jq -r 'sort | .[]'
}

require_clean_boundary() {
    test ! -e "${state_directory}"
    test -z "$(user_list)"
    test -z "$(bucket_list)"
}

require_state_file() {
    local path="$1"

    test -f "${path}"
    test "$(stat -c '%U:%G:%a' "${path}")" = root:root:600
}

require_user_state() {
    local uid="$1"
    local state_path="$2"
    local live_state

    live_state="$(
        ceph_json radosgw-admin user info --uid="${uid}"
    )"
    jq -e --arg uid "${uid}" \
        '.user_id == $uid and
         .max_buckets == 1 and
         (.caps | length) == 0 and
         (.keys | length) == 1 and
         (.keys[0].access_key | type == "string" and length > 0) and
         (.keys[0].secret_key | type == "string" and length > 0)' \
        "${state_path}" >/dev/null
    test "$(
        jq -r '.keys[0].access_key' "${state_path}" | sha256sum
    )" = "$(
        jq -r '.keys[0].access_key' <<<"${live_state}" | sha256sum
    )"
    test "$(
        jq -r '.keys[0].secret_key' "${state_path}" | sha256sum
    )" = "$(
        jq -r '.keys[0].secret_key' <<<"${live_state}" | sha256sum
    )"
}

require_bucket_owner() {
    local bucket="$1"
    local uid="$2"

    test "$(
        ceph_json radosgw-admin bucket stats --bucket="${bucket}" |
            jq -r '.owner'
    )" = "${uid}"
}

require_prepared_boundary() {
    test "$(stat -c '%U:%G:%a' "${state_directory}")" = root:root:700
    require_state_file "${registry_state}"
    require_state_file "${denial_state}"
    require_state_file "${distribution_env}"
    test "$(user_list)" = "$(
        printf '%s\n' "${denial_uid}" "${registry_uid}" | sort
    )"
    test "$(bucket_list)" = "$(
        printf '%s\n' "${denial_bucket}" "${registry_bucket}" | sort
    )"
    require_user_state "${registry_uid}" "${registry_state}"
    require_user_state "${denial_uid}" "${denial_state}"
    require_bucket_owner "${registry_bucket}" "${registry_uid}"
    require_bucket_owner "${denial_bucket}" "${denial_uid}"
}

classify_boundary() {
    if test -e "${state_directory}"; then
        require_prepared_boundary
        fixture_state=prepared
    else
        require_clean_boundary
        fixture_state=clean
    fi
}

require_cluster_healthy
classify_boundary

if test "${action}" = status; then
    printf 'ceph_s3_cleanup state=%s users=%s buckets=%s mutation=none\n' \
        "${fixture_state}" "$(
            if test "${fixture_state}" = prepared; then printf 2; else printf 0; fi
        )" "$(
            if test "${fixture_state}" = prepared; then printf 2; else printf 0; fi
        )"
    exit 0
fi

exec 9>/run/lock/coffer-stage5-ceph-s3-cleanup.lock
if ! flock -n 9; then
    echo "refusing concurrent Ceph S3 cleanup" >&2
    exit 75
fi

if test "${fixture_state}" = clean; then
    printf 'ceph_s3_cleanup phase=cleanup result=passed idempotent=yes\n'
    exit 0
fi

cephadm shell -- radosgw-admin bucket rm \
    --bucket="${denial_bucket}" --purge-objects </dev/null >/dev/null
cephadm shell -- radosgw-admin bucket rm \
    --bucket="${registry_bucket}" --purge-objects </dev/null >/dev/null
test -z "$(bucket_list)"

cephadm shell -- radosgw-admin user rm \
    --uid="${denial_uid}" </dev/null >/dev/null
cephadm shell -- radosgw-admin user rm \
    --uid="${registry_uid}" </dev/null >/dev/null
test -z "$(user_list)"

rm -f -- "${distribution_env}"
rm -f -- "${denial_state}"
rm -f -- "${registry_state}"
rmdir -- "${state_directory}"

require_clean_boundary
require_cluster_healthy
printf 'ceph_s3_cleanup phase=cleanup result=passed users=0 buckets=0 residue=none\n'
