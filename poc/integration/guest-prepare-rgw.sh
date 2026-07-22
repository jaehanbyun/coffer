#!/usr/bin/env bash

set -euo pipefail

integration_directory="/etc/coffer-rgw/integration"
command_name="${1:-prepare}"

test "$(id -u)" -eq 0

case "${command_name}" in
  cleanup)
    rm -f \
      "${integration_directory}/client-credentials.json" \
      "${integration_directory}/jwks.json" \
      "${integration_directory}/token-ca.crt" \
      "${integration_directory}/ca-bundle.crt"
    rmdir "${integration_directory}" 2>/dev/null || true
    rm -f \
      /tmp/coffer-integration-client-credentials.json \
      /tmp/coffer-integration-jwks.json \
      /tmp/coffer-integration-token-ca.crt \
      /tmp/coffer-integration-evidence.json \
      /tmp/coffer-integration-distribution.log \
      /tmp/coffer-integration-project-b-push.log
    exit 0
    ;;
  prepare) ;;
  *)
    printf 'unknown command: %s\n' "${command_name}" >&2
    exit 2
    ;;
esac

for source_file in \
  /tmp/coffer-integration-client-credentials.json \
  /tmp/coffer-integration-jwks.json \
  /tmp/coffer-integration-token-ca.crt; do
  test -f "${source_file}"
done

umask 077
install -d -m 0700 "${integration_directory}"
install -m 0600 /tmp/coffer-integration-client-credentials.json \
  "${integration_directory}/client-credentials.json"
install -m 0644 /tmp/coffer-integration-jwks.json \
  "${integration_directory}/jwks.json"
install -m 0644 /tmp/coffer-integration-token-ca.crt \
  "${integration_directory}/token-ca.crt"
cat /etc/ssl/certs/ca-certificates.crt \
  "${integration_directory}/token-ca.crt" \
  >"${integration_directory}/ca-bundle.crt"
chmod 0644 "${integration_directory}/ca-bundle.crt"

jq -e '
  .project_a.application_credential_id and
  .project_a.application_credential_secret and
  .project_a.project_id and
  .project_b.application_credential_id and
  .project_b.application_credential_secret and
  .project_b.project_id and
  (.project_a.project_id != .project_b.project_id)
' "${integration_directory}/client-credentials.json" >/dev/null
jq -e '.keys | type == "array" and length == 1' \
  "${integration_directory}/jwks.json" >/dev/null
openssl verify -CAfile "${integration_directory}/token-ca.crt" \
  "${integration_directory}/token-ca.crt" >/dev/null

rm -f \
  /tmp/coffer-integration-client-credentials.json \
  /tmp/coffer-integration-jwks.json \
  /tmp/coffer-integration-token-ca.crt

COFFER_DISTRIBUTION_AUTH_REALM='https://127.0.0.1:18081/auth/token' \
COFFER_DISTRIBUTION_AUTH_SERVICE='coffer-registry-poc' \
COFFER_DISTRIBUTION_AUTH_ISSUER='coffer-real-poc' \
COFFER_DISTRIBUTION_AUTH_JWKS="${integration_directory}/jwks.json" \
  bash /tmp/guest-run-distribution.sh >/dev/null

status_code="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --cacert /etc/coffer-rgw/distribution-tls/ca.crt \
    https://coffer-rgw-poc:5443/v2/
)"
test "${status_code}" = 401
