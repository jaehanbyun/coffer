#!/usr/bin/env bash

set -Eeuo pipefail

python_helper="$1"
primary_hostname="coffer-rgw-ha-stage5-storage-1"
state_directory="/etc/coffer-stage5-rgw"
registry_uid="coffer-stage5-registry"
denial_uid="coffer-stage5-denial"
registry_state="${state_directory}/registry-user.json"
denial_state="${state_directory}/denial-user.json"
distribution_env="${state_directory}/distribution.env"
ingress_ca="/etc/ceph/coffer-stage5-ingress/ca.crt"
registry_bucket="coffer-stage5-registry"
denial_bucket="coffer-stage5-denial"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f "${python_helper}"
test -f "${ingress_ca}"
test "$(
    cephadm shell -- ceph status --format json </dev/null |
        jq -r '.health.status'
)" = HEALTH_OK
test "$(
    cephadm shell -- ceph orch ps --service_name rgw.coffer \
        --format json </dev/null |
        jq '[.[] | select(
            .daemon_type == "rgw" and .status_desc == "running"
        )] | length'
)" -eq 3
test "$(
    cephadm shell -- ceph orch ps --service_name ingress.rgw.coffer \
        --format json </dev/null |
        jq '[.[] | select(
            .daemon_type == "haproxy" and .status_desc == "running"
        )] | length'
)" -eq 2

if ! python3 -c 'import boto3, botocore' 2>/dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y python3-boto3
fi
python3 -c 'import boto3, botocore'

umask 077
install -d -o root -g root -m 0700 "${state_directory}"
temporary_files=()
cleanup_temporary_files() {
    local path

    for path in "${temporary_files[@]}"; do
        rm -f -- "${path}"
    done
}
trap cleanup_temporary_files EXIT

ensure_user() {
    local uid="$1"
    local display_name="$2"
    local state_path="$3"
    local temporary_state
    local user_exists=false

    temporary_state="$(mktemp "${state_directory}/user.XXXXXX")"
    temporary_files+=("${temporary_state}")
    if cephadm shell -- radosgw-admin user info \
        --uid="${uid}" </dev/null >"${temporary_state}" 2>/dev/null; then
        user_exists=true
    fi

    if ${user_exists} && test ! -f "${state_path}"; then
        echo "refusing an unowned pre-existing S3 fixture identity" >&2
        exit 20
    fi
    if ! ${user_exists} && test -f "${state_path}"; then
        echo "refusing credential state without its RGW identity" >&2
        exit 21
    fi

    if ${user_exists}; then
        cephadm shell -- radosgw-admin user modify \
            --uid="${uid}" --max-buckets=1 \
            </dev/null >"${temporary_state}" 2>/dev/null
    else
        cephadm shell -- radosgw-admin user create \
            --uid="${uid}" \
            --display-name="${display_name}" \
            --max-buckets=1 \
            --generate-key=true \
            </dev/null >"${temporary_state}" 2>/dev/null
    fi
    cephadm shell -- radosgw-admin user info \
        --uid="${uid}" </dev/null >"${temporary_state}" 2>/dev/null
    jq -e \
        --arg uid "${uid}" \
        '.user_id == $uid and
         .max_buckets == 1 and
         (.caps | length) == 0 and
         (.keys | length) == 1 and
         (.keys[0].access_key | type == "string" and length > 0) and
         (.keys[0].secret_key | type == "string" and length > 0)' \
        "${temporary_state}" >/dev/null

    if test -f "${state_path}"; then
        test "$(
            jq -r '.keys[0].access_key' "${state_path}" |
                sha256sum | awk '{print $1}'
        )" = "$(
            jq -r '.keys[0].access_key' "${temporary_state}" |
                sha256sum | awk '{print $1}'
        )"
        test "$(
            jq -r '.keys[0].secret_key' "${state_path}" |
                sha256sum | awk '{print $1}'
        )" = "$(
            jq -r '.keys[0].secret_key' "${temporary_state}" |
                sha256sum | awk '{print $1}'
        )"
    fi
    install -o root -g root -m 0600 "${temporary_state}" "${state_path}"
    rm -f -- "${temporary_state}"
}

ensure_user "${registry_uid}" 'Coffer Stage 5 registry' "${registry_state}"
ensure_user "${denial_uid}" 'Coffer Stage 5 denial' "${denial_state}"

registry_access_key="$(jq -r '.keys[0].access_key' "${registry_state}")"
registry_secret_key="$(jq -r '.keys[0].secret_key' "${registry_state}")"
test -n "${registry_access_key}"
test -n "${registry_secret_key}"
{
    printf 'REGISTRY_STORAGE_S3_REGION=us-east-1\n'
    printf 'REGISTRY_STORAGE_S3_REGIONENDPOINT=https://192.168.253.30:8443\n'
    printf 'REGISTRY_STORAGE_S3_BUCKET=%s\n' "${registry_bucket}"
    printf 'REGISTRY_STORAGE_S3_ACCESSKEY=%s\n' "${registry_access_key}"
    printf 'REGISTRY_STORAGE_S3_SECRETKEY=%s\n' "${registry_secret_key}"
    printf 'REGISTRY_STORAGE_S3_ROOTDIRECTORY=/registry\n'
    printf 'REGISTRY_STORAGE_S3_SECURE=true\n'
    printf 'REGISTRY_STORAGE_S3_V4AUTH=true\n'
    printf 'REGISTRY_STORAGE_S3_FORCEPATHSTYLE=true\n'
    printf 'REGISTRY_STORAGE_S3_CA=%s\n' "${ingress_ca}"
} >"${distribution_env}"
chmod 0600 "${distribution_env}"

python3 "${python_helper}" "${registry_state}" "${denial_state}"

users="$(
    cephadm shell -- radosgw-admin user list --format json </dev/null
)"
test "$(jq 'length' <<<"${users}")" -eq 2
test "$(
    jq -r 'sort | join(",")' <<<"${users}"
)" = "${denial_uid},${registry_uid}"

registry_stats="$(
    cephadm shell -- radosgw-admin bucket stats \
        --bucket "${registry_bucket}" --format json </dev/null
)"
denial_stats="$(
    cephadm shell -- radosgw-admin bucket stats \
        --bucket "${denial_bucket}" --format json </dev/null
)"
test "$(jq -r '.owner' <<<"${registry_stats}")" = "${registry_uid}"
test "$(jq -r '.owner' <<<"${denial_stats}")" = "${denial_uid}"
test "$(stat -c '%a' "${registry_state}")" = 600
test "$(stat -c '%a' "${denial_state}")" = 600
test "$(stat -c '%a' "${distribution_env}")" = 600

for _ in $(seq 1 120); do
    inactive_pgs="$(
        cephadm shell -- ceph pg stat --format json </dev/null |
            jq '[.pg_summary.num_pg_by_state[]? |
                select(.name != "active+clean") | .num] | add // 0'
    )"
    health_status="$(
        cephadm shell -- ceph status --format json </dev/null |
            jq -r '.health.status'
    )"
    if test "${inactive_pgs}" -eq 0 &&
        test "${health_status}" = HEALTH_OK; then
        break
    fi
    sleep 2
done
test "${inactive_pgs}" -eq 0
test "${health_status}" = HEALTH_OK

cleanup_temporary_files
trap - EXIT
printf 'ceph_s3 users=2 buckets=2 credential_files=3 health=%s\n' \
    "${health_status}"
