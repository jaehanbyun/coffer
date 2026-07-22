#!/usr/bin/env bash

set -euo pipefail

runtime_env="/etc/coffer-rgw/barbican.env"
config_section="client.rgw.coffer"
config_helper="/tmp/guest-ceph-kms-config.py"
restart_helper="/tmp/guest-restart-rgw.sh"

test "$(id -u)" -eq 0
test -f "${runtime_env}"
test -f "${config_helper}"
test -f "${restart_helper}"
test "$(stat -c '%a' "${runtime_env}")" = 600
test "$(wc -l <"${runtime_env}" | tr -d ' ')" -eq 7
grep -Eq '^COFFER_KMS_USERNAME=coffer-rgw-kms-poc$' "${runtime_env}"
grep -Eq '^COFFER_KMS_USER_PASSWORD=[[:alnum:]]{32,}$' "${runtime_env}"
grep -Eq '^COFFER_KMS_PROJECT=coffer-rgw-kms-poc$' "${runtime_env}"
grep -Eq '^COFFER_KMS_DOMAIN=Default$' "${runtime_env}"
grep -Eq '^COFFER_KMS_KEY_ID=[0-9a-f-]{32,36}$' "${runtime_env}"

completed=false
run_config_helper() {
  local action="$1"
  cephadm shell \
    --mount "${config_helper}:${config_helper}" \
      "${runtime_env}:/tmp/coffer-barbican.env" \
    -- python3 "${config_helper}" "${action}" >/dev/null
}
rollback_partial_config() {
  local status=$?
  trap - EXIT
  if test "${completed}" != true; then
    run_config_helper remove >/dev/null 2>&1 || true
  fi
  exit "${status}"
}
trap rollback_partial_config EXIT

# The protected binding is mounted directly into the cephadm shell. The bounded
# helper opens it only for reading and sends values over librados, so no secret
# enters the host or container process argument vector.
run_config_helper set

expected_names='[
  "rgw_barbican_url",
  "rgw_crypt_require_ssl",
  "rgw_crypt_s3_kms_backend",
  "rgw_keystone_barbican_domain",
  "rgw_keystone_barbican_password",
  "rgw_keystone_barbican_project",
  "rgw_keystone_barbican_user",
  "rgw_keystone_url",
  "rgw_keystone_verify_ssl"
]'
cephadm shell -- ceph config dump --format json | jq -e \
  --arg section "${config_section}" \
  --argjson expected "${expected_names}" \
  '[.[] | select(.section == $section) | .name |
    select(startswith("rgw_crypt") or startswith("rgw_barbican") or
      startswith("rgw_keystone"))] | sort == ($expected | sort)' >/dev/null

bash "${restart_helper}" >/dev/null

completed=true
trap - EXIT
printf 'RGW Barbican KMS option names applied and service restarted\n'
