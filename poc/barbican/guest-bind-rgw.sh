#!/usr/bin/env bash

set -euo pipefail

state_directory="/etc/coffer-rgw"
runtime_env="${state_directory}/barbican.env"
public_ca="${state_directory}/devstack-ca.pem"
combined_ca="${state_directory}/devstack-ca-bundle.crt"
input_ca="/tmp/coffer-devstack-ca.pem"
barbican_url="https://localhost:19311/key-manager/v1"
keystone_url="https://localhost:19311/identity/v3"
install_candidate=""
install_bundle_candidate=""

test "$(id -u)" -eq 0
test "$(hostname)" = coffer-rgw-poc

validate_runtime() {
  local path="$1"
  test -f "${path}"
  test "$(wc -l <"${path}" | tr -d ' ')" -eq 7
  test "$(cut -d= -f1 "${path}" | sort -u | wc -l | tr -d ' ')" -eq 7
  grep -Eq '^COFFER_KMS_USERNAME=coffer-rgw-kms-poc$' "${path}"
  grep -Eq '^COFFER_KMS_USER_PASSWORD=[[:alnum:]]{32,}$' "${path}"
  grep -Eq '^COFFER_KMS_PROJECT=coffer-rgw-kms-poc$' "${path}"
  grep -Eq '^COFFER_KMS_DOMAIN=Default$' "${path}"
  grep -Eq '^COFFER_KMS_PROJECT_ID=[0-9a-f]{32}$' "${path}"
  grep -Eq '^COFFER_KMS_USER_ID=[0-9a-f]{32}$' "${path}"
  grep -Eq '^COFFER_KMS_KEY_ID=[0-9a-f-]{32,36}$' "${path}"
}

cleanup_install() {
  rm -f "${install_candidate}" "${install_bundle_candidate}"
}

install_binding() {
  umask 077
  install_candidate="$(mktemp /tmp/coffer-barbican-binding.XXXXXX)"
  install_bundle_candidate="$(mktemp /tmp/coffer-devstack-ca-bundle.XXXXXX)"
  trap cleanup_install EXIT
  cat >"${install_candidate}"
  chmod 0600 "${install_candidate}"
  validate_runtime "${install_candidate}"

  test -f "${input_ca}"
  openssl x509 -in "${input_ca}" -noout -checkend 86400

  install -d -m 0700 "${state_directory}"
  install -m 0600 "${install_candidate}" "${runtime_env}"
  install -m 0644 "${input_ca}" "${public_ca}"
  {
    cat /etc/ssl/certs/ca-certificates.crt
    printf '\n'
    cat "${public_ca}"
  } >"${install_bundle_candidate}"
  install -m 0644 "${install_bundle_candidate}" "${combined_ca}"
  rm -f "${input_ca}"
  validate_runtime "${runtime_env}"
  test "$(stat -c '%a' "${state_directory}")" = 700
  test "$(stat -c '%a' "${runtime_env}")" = 600
  cleanup_install
  trap - EXIT
  printf 'Owner-only RGW Barbican binding installed\n'
}

verify_binding() {
  local barbican_status keystone_status container
  validate_runtime "${runtime_env}"
  test "$(stat -c '%a' "${runtime_env}")" = 600
  test -f "${public_ca}"
  test -f "${combined_ca}"

  barbican_status="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --connect-timeout 3 --max-time 10 \
    --cacert "${public_ca}" "${barbican_url}")"
  test "${barbican_status}" = 401
  keystone_status="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --connect-timeout 3 --max-time 10 \
    --cacert "${public_ca}" "${keystone_url}")"
  test "${keystone_status}" = 200
  if SSL_CERT_FILE=/dev/null curl --silent --show-error --output /dev/null \
    --connect-timeout 3 --max-time 10 "${barbican_url}" 2>/dev/null; then
    printf 'Barbican unexpectedly trusted without the installed CA\n' >&2
    exit 31
  fi

  container="$(podman ps --filter 'name=ceph-.*-rgw-coffer' \
    --format '{{.Names}}' | head -1)"
  test -n "${container}"
  podman inspect "${container}" --format '{{json .Mounts}}' | jq -e \
    --arg source "${combined_ca}" \
    'any(.[]; .Source == $source and
      .Destination == "/etc/pki/tls/certs/ca-bundle.crt" and
      .RW == false)' >/dev/null

  barbican_status="$(podman exec "${container}" curl --silent --show-error \
    --output /dev/null --write-out '%{http_code}' --connect-timeout 3 \
    --max-time 10 "${barbican_url}")"
  test "${barbican_status}" = 401
  keystone_status="$(podman exec "${container}" curl --silent --show-error \
    --output /dev/null --write-out '%{http_code}' --connect-timeout 3 \
    --max-time 10 "${keystone_url}")"
  test "${keystone_status}" = 200
  printf 'RGW host and daemon container trust the Barbican/Keystone TLS path\n'
}

case "${1:-}" in
  install)
    install_binding
    ;;
  verify)
    verify_binding
    ;;
  *)
    printf 'usage: %s {install|verify}\n' "$0" >&2
    exit 2
    ;;
esac
