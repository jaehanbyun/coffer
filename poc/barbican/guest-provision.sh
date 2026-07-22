#!/usr/bin/env bash
set -euo pipefail

devstack_dir="${COFFER_DEVSTACK_DIR:-${HOME}/devstack}"
runtime_python="/tmp/coffer-barbican-provision-runtime.py"
state_dir="/etc/coffer-barbican"
runtime_env="${state_dir}/rgw.env"
metadata_file="$(mktemp /tmp/coffer-barbican-metadata.XXXXXX)"
generated_password=""
runtime_copy=""
runtime_candidate=""

cleanup() {
  rm -f "${metadata_file}"
  if test -n "${runtime_copy}"; then
    rm -f "${runtime_copy}"
  fi
  if test -n "${runtime_candidate}"; then
    rm -f "${runtime_candidate}"
  fi
  unset generated_password COFFER_KMS_USER_PASSWORD OS_PASSWORD
}
trap cleanup EXIT

test "$(id -u)" -ne 0
test -x /opt/stack/data/venv/bin/python
test -f "${runtime_python}"
test "$(stat -c '%a' "${runtime_python}")" = 700

set +u
# DevStack generates this runtime file inside the guest.
# shellcheck disable=SC1091
source "${devstack_dir}/openrc" admin admin
set -u
export OS_CACERT="/opt/stack/data/CA/int-ca/ca-chain.pem"

if sudo test -f "${runtime_env}"; then
  runtime_copy="$(mktemp /tmp/coffer-barbican-runtime.XXXXXX)"
  sudo install -m 0600 "${runtime_env}" "${runtime_copy}"
  sudo chown "$(id -u):$(id -g)" "${runtime_copy}"
  # shellcheck disable=SC1090
  source "${runtime_copy}"
  rm -f "${runtime_copy}"
  runtime_copy=""
  generated_password="${COFFER_KMS_USER_PASSWORD}"
else
  generated_password="$(openssl rand -hex 24)"
  COFFER_KMS_KEY_ID=""
  COFFER_KMS_PROJECT_ID=""
  COFFER_KMS_USER_ID=""
fi

export COFFER_KMS_USER_PASSWORD="${generated_password}"
export COFFER_KMS_KEY_ID="${COFFER_KMS_KEY_ID:-}"
export COFFER_KMS_PROJECT_ID="${COFFER_KMS_PROJECT_ID:-}"
export COFFER_KMS_USER_ID="${COFFER_KMS_USER_ID:-}"
umask 077
/opt/stack/data/venv/bin/python "${runtime_python}" >"${metadata_file}"

project_id="$(jq -er '.project_id' "${metadata_file}")"
user_id="$(jq -er '.user_id' "${metadata_file}")"
key_id="$(jq -er '.key_id' "${metadata_file}")"
test "$(jq -er '.key_bytes' "${metadata_file}")" = 32
[[ "${project_id}" =~ ^[0-9a-f]{32}$ ]]
[[ "${user_id}" =~ ^[0-9a-f]{32}$ ]]
[[ "${key_id}" =~ ^[0-9a-f-]{32,36}$ ]]

runtime_candidate="$(mktemp /tmp/coffer-barbican-rgw-env.XXXXXX)"
{
  printf 'COFFER_KMS_USERNAME=%s\n' 'coffer-rgw-kms-poc'
  printf 'COFFER_KMS_USER_PASSWORD=%s\n' "${generated_password}"
  printf 'COFFER_KMS_PROJECT=%s\n' 'coffer-rgw-kms-poc'
  printf 'COFFER_KMS_DOMAIN=%s\n' 'Default'
  printf 'COFFER_KMS_PROJECT_ID=%s\n' "${project_id}"
  printf 'COFFER_KMS_USER_ID=%s\n' "${user_id}"
  printf 'COFFER_KMS_KEY_ID=%s\n' "${key_id}"
} >"${runtime_candidate}"
chmod 600 "${runtime_candidate}"
sudo install -d -m 0700 "${state_dir}"
sudo install -m 0600 "${runtime_candidate}" "${runtime_env}"
rm -f "${runtime_candidate}"
runtime_candidate=""

jq 'del(.key_id) + {
  caller_binding_retained:true,
  credential_in_host_evidence:false,
  key_id_format_valid:true,
  key_id_retained:false,
  secret_payload_retained:false
}' \
  "${metadata_file}" >/tmp/coffer-barbican-provision-evidence.json
chmod 600 /tmp/coffer-barbican-provision-evidence.json

printf 'Disposable Barbican RGW identity and 256-bit key are ready\n'
