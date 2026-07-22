#!/usr/bin/env bash

set -euo pipefail

integration_directory="/etc/coffer-rgw/integration"
credential_file="${integration_directory}/client-credentials.json"
ca_bundle="${integration_directory}/ca-bundle.crt"
evidence_file="/tmp/coffer-integration-evidence.json"
registry_host="coffer-rgw-poc:5443"
temporary_directory="$(mktemp -d /tmp/coffer-broker-restart.XXXXXX)"

cleanup() {
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test -f "${credential_file}"
test -f "${evidence_file}"
credential_id="$(jq -er '.project_a.application_credential_id' \
  "${credential_file}")"
image_ref="${registry_host}/$(jq -er '.repository' "${evidence_file}"):keystone"
expected_digest="$(jq -er '.digest' "${evidence_file}")"
authfile="${temporary_directory}/auth.json"

jq -er '.project_a.application_credential_secret' "${credential_file}" | \
  SSL_CERT_FILE="${ca_bundle}" skopeo login --authfile "${authfile}" \
    --username "${credential_id}" --password-stdin "${registry_host}" \
    >/dev/null
chmod 0600 "${authfile}"
actual_digest="$(
  SSL_CERT_FILE="${ca_bundle}" skopeo inspect --authfile "${authfile}" \
    --format '{{.Digest}}' "docker://${image_ref}"
)"
test "${actual_digest}" = "${expected_digest}"

updated_evidence="${temporary_directory}/evidence.json"
jq --arg digest "${actual_digest}" '.coffer_restart_digest = $digest' \
  "${evidence_file}" >"${updated_evidence}"
install -m 0644 "${updated_evidence}" "${evidence_file}"

printf 'Post-Coffer-restart pull passed digest=%s\n' "${actual_digest}"
