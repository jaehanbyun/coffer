#!/usr/bin/env bash

set -euo pipefail

runner="/tmp/guest-run-distribution.sh"
state_dir="/etc/coffer-rgw"
user_state="${state_dir}/registry-user.json"
distribution_env="${state_dir}/distribution.env"
uid="coffer-registry-poc"
baseline="docker://coffer-rgw-poc:5443/p/00000000-0000-0000-0000-000000000003/real-rgw:image"
candidate_user=""
candidate_env=""
old_env=""
new_access=""
old_access=""
new_created=false
old_removed=false

test "$(id -u)" -eq 0
test -f "${runner}"
test -f "${user_state}"
test -f "${distribution_env}"
test "$(stat -c '%a' "${user_state}")" = 600
test "$(stat -c '%a' "${distribution_env}")" = 600

umask 077
candidate_user="$(mktemp "${state_dir}/registry-user-rotate.XXXXXX")"
candidate_env="$(mktemp "${state_dir}/distribution-rotate.XXXXXX")"
old_env="$(mktemp "${state_dir}/distribution-old.XXXXXX")"
install -m 0600 "${distribution_env}" "${old_env}"
old_access="$(jq -er '.keys | select(length == 1) | .[0].access_key' "${user_state}")"

cleanup() {
  local status=$?
  trap - EXIT
  if test "${status}" -ne 0 && test "${new_created}" = true &&
    test "${old_removed}" != true; then
    install -m 0600 "${old_env}" "${distribution_env}" || true
    bash "${runner}" >/dev/null 2>&1 || true
    if test -n "${new_access}"; then
      cephadm shell -- radosgw-admin key rm --uid="${uid}" \
        --access-key="${new_access}" >/dev/null 2>&1 || true
    fi
  fi
  rm -f -- "${candidate_user}" "${candidate_env}" "${old_env}"
  unset old_access new_access
  exit "${status}"
}
trap cleanup EXIT

cephadm shell -- radosgw-admin key create --uid="${uid}" \
  --key-type=s3 --gen-access-key >"${candidate_user}" 2>/dev/null
new_created=true
cephadm shell -- radosgw-admin user info --uid="${uid}" \
  >"${candidate_user}" 2>/dev/null
jq -e --arg old "${old_access}" \
  '.user_id == "coffer-registry-poc" and (.caps | length) == 0 and
   (.keys | length) == 2 and any(.keys[]; .access_key == $old)' \
  "${candidate_user}" >/dev/null
new_access="$(jq -er --arg old "${old_access}" \
  '.keys[] | select(.access_key != $old) | .access_key' "${candidate_user}")"
new_secret="$(jq -er --arg access "${new_access}" \
  '.keys[] | select(.access_key == $access) | .secret_key' "${candidate_user}")"
{
  printf 'REGISTRY_STORAGE_S3_ACCESSKEY=%s\n' "${new_access}"
  printf 'REGISTRY_STORAGE_S3_SECRETKEY=%s\n' "${new_secret}"
} >"${candidate_env}"
unset new_secret
install -m 0600 "${candidate_env}" "${distribution_env}"
bash "${runner}" >/dev/null
test -n "$(skopeo inspect --format '{{.Digest}}' "${baseline}")"

# RGW exposes an access-key identifier (not its secret key) as the selector for
# bounded removal. The secret key never enters argv, output, or retained logs.
cephadm shell -- radosgw-admin key rm --uid="${uid}" \
  --access-key="${old_access}" >/dev/null 2>&1
old_removed=true
cephadm shell -- radosgw-admin user info --uid="${uid}" \
  >"${candidate_user}" 2>/dev/null
jq -e --arg access "${new_access}" \
  '.user_id == "coffer-registry-poc" and (.caps | length) == 0 and
   (.keys | length) == 1 and .keys[0].access_key == $access' \
  "${candidate_user}" >/dev/null
install -m 0600 "${candidate_user}" "${user_state}"
test -n "$(skopeo inspect --format '{{.Digest}}' "${baseline}")"

printf 'Registry S3 key rotation passed with one active key\n'
