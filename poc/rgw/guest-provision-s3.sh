#!/usr/bin/env bash

set -euo pipefail

python_helper="${1:-/tmp/guest-provision-s3.py}"
state_directory="/etc/coffer-rgw"
registry_uid="coffer-registry-poc"
denial_uid="coffer-denial-poc"
registry_state="${state_directory}/registry-user.json"
denial_state="${state_directory}/denial-user.json"
distribution_env="${state_directory}/distribution.env"

test "$(id -u)" -eq 0
test -f "${python_helper}"
test -f /etc/ceph/coffer-rgw-root-ca.crt
python3 -c 'import boto3, botocore'

umask 077
install -d -m 0700 "${state_directory}"
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

  temporary_state="$(mktemp "${state_directory}/user.XXXXXX")"
  temporary_files+=("${temporary_state}")
  if cephadm shell -- radosgw-admin user info --uid="${uid}" >"${temporary_state}" 2>/dev/null; then
    cephadm shell -- radosgw-admin user modify \
      --uid="${uid}" --max-buckets=1 >"${temporary_state}" 2>/dev/null
  else
    cephadm shell -- radosgw-admin user create \
      --uid="${uid}" \
      --display-name="${display_name}" \
      --max-buckets=1 \
      --generate-key=true >"${temporary_state}" 2>/dev/null
  fi
  cephadm shell -- radosgw-admin user info --uid="${uid}" >"${temporary_state}" 2>/dev/null
  jq -e \
    --arg uid "${uid}" \
    '.user_id == $uid and .max_buckets == 1 and (.caps | length) == 0 and (.keys | length) == 1' \
    "${temporary_state}" >/dev/null
  install -m 0600 "${temporary_state}" "${state_path}"
  rm -f "${temporary_state}"
}

ensure_user "${registry_uid}" 'Coffer registry PoC' "${registry_state}"
ensure_user "${denial_uid}" 'Coffer denial bucket PoC' "${denial_state}"

registry_access_key="$(jq -r '.keys[0].access_key' "${registry_state}")"
registry_secret_key="$(jq -r '.keys[0].secret_key' "${registry_state}")"
test -n "${registry_access_key}"
test -n "${registry_secret_key}"
{
  printf 'REGISTRY_STORAGE_S3_ACCESSKEY=%s\n' "${registry_access_key}"
  printf 'REGISTRY_STORAGE_S3_SECRETKEY=%s\n' "${registry_secret_key}"
} >"${distribution_env}"
chmod 0600 "${distribution_env}"

python3 "${python_helper}" "${registry_state}" "${denial_state}"

cephadm shell -- radosgw-admin bucket stats --bucket coffer-registry-poc | \
  jq '{bucket, owner, num_shards, usage}'
cephadm shell -- radosgw-admin bucket stats --bucket coffer-denial-poc | \
  jq '{bucket, owner, num_shards, usage}'

cleanup_temporary_files
trap - EXIT
