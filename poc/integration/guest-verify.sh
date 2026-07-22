#!/usr/bin/env bash

set -euo pipefail

integration_directory="/etc/coffer-rgw/integration"
credential_file="${integration_directory}/client-credentials.json"
token_ca="${integration_directory}/token-ca.crt"
ca_bundle="${integration_directory}/ca-bundle.crt"
registry_host="coffer-rgw-poc:5443"
registry_url="https://${registry_host}"
registry_ca="/etc/coffer-rgw/distribution-tls/ca.crt"
token_url="https://127.0.0.1:18081/auth/token"
token_service="coffer-registry-poc"
repository_name="real-rgw"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
temporary_directory="$(mktemp -d /tmp/coffer-real-integration.XXXXXX)"
podman_image="${registry_host}/pending:podman"

cleanup() {
  if [[ "${podman_image}" != *pending* ]]; then
    podman rmi --force "${podman_image}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${temporary_directory}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test -f "${credential_file}"
test "$(stat -c '%a' "${credential_file}")" = 600
test -f "${token_ca}"
test -f "${ca_bundle}"
test "$(podman inspect coffer-distribution-rgw --format '{{.State.Running}}')" = true

project_a_id="$(jq -er '.project_a.project_id' "${credential_file}")"
project_b_id="$(jq -er '.project_b.project_id' "${credential_file}")"
credential_a_id="$(jq -er '.project_a.application_credential_id' \
  "${credential_file}")"
credential_b_id="$(jq -er '.project_b.application_credential_id' \
  "${credential_file}")"
test "${project_a_id}" != "${project_b_id}"

repository_a="p/${project_a_id}/${repository_name}"
image_a="${registry_host}/${repository_a}:keystone"
podman_image="${registry_host}/${repository_a}:podman"
authfile_a="${temporary_directory}/auth-a.json"
authfile_b="${temporary_directory}/auth-b.json"

for _attempt in $(seq 1 30); do
  token_status="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 2 --max-time 5 --cacert "${token_ca}" \
      --get --data-urlencode "service=${token_service}" "${token_url}" || true
  )"
  if test "${token_status}" = 401; then
    break
  fi
  sleep 1
done
test "${token_status}" = 401
if curl --silent --show-error --output /dev/null --connect-timeout 2 \
  --max-time 5 "${token_url}" 2>/dev/null; then
  printf 'token realm unexpectedly trusted without its lab CA\n' >&2
  exit 30
fi

challenge_headers="${temporary_directory}/registry-challenge.headers"
registry_status="$(
  curl --silent --show-error --output /dev/null --dump-header "${challenge_headers}" \
    --write-out '%{http_code}' --cacert "${registry_ca}" \
    "${registry_url}/v2/"
)"
test "${registry_status}" = 401
grep -Fq 'realm="https://127.0.0.1:18081/auth/token"' \
  "${challenge_headers}"
grep -Fq 'service="coffer-registry-poc"' "${challenge_headers}"

jq -er '.project_a.application_credential_secret' "${credential_file}" | \
  SSL_CERT_FILE="${ca_bundle}" skopeo login --authfile "${authfile_a}" \
    --username "${credential_a_id}" --password-stdin "${registry_host}" \
    >/dev/null
jq -er '.project_b.application_credential_secret' "${credential_file}" | \
  SSL_CERT_FILE="${ca_bundle}" skopeo login --authfile "${authfile_b}" \
    --username "${credential_b_id}" --password-stdin "${registry_host}" \
    >/dev/null
chmod 0600 "${authfile_a}" "${authfile_b}"

test "$(skopeo inspect "docker://${busybox_ref}" | jq -r '.Digest')" = \
  'sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028'
SSL_CERT_FILE="${ca_bundle}" skopeo copy --retry-times 3 \
  --dest-authfile "${authfile_a}" \
  "docker://${busybox_ref}" "docker://${image_a}" >/dev/null
subject_digest="$(
  SSL_CERT_FILE="${ca_bundle}" skopeo inspect --authfile "${authfile_a}" \
    --format '{{.Digest}}' "docker://${image_a}"
)"
test -n "${subject_digest}"

SSL_CERT_FILE="${ca_bundle}" skopeo copy --retry-times 3 \
  --src-authfile "${authfile_a}" "docker://${image_a}" \
  "oci:${temporary_directory}/pull-before:keystone" >/dev/null
before_digest="$(
  skopeo inspect --format '{{.Digest}}' \
    "oci:${temporary_directory}/pull-before:keystone"
)"
test "${before_digest}" = "${subject_digest}"

podman pull "${busybox_ref}" >/dev/null
podman tag "${busybox_ref}" "${podman_image}"
SSL_CERT_FILE="${ca_bundle}" podman push --authfile "${authfile_a}" \
  --digestfile "${temporary_directory}/podman-push.digest" \
  "${podman_image}" >/dev/null
podman_push_digest="$(tr -d '\n' <"${temporary_directory}/podman-push.digest")"
case "${podman_push_digest}" in
  sha256:[0-9a-f][0-9a-f]*) ;;
  *) exit 34 ;;
esac
podman rmi "${podman_image}" >/dev/null
SSL_CERT_FILE="${ca_bundle}" podman pull --authfile "${authfile_a}" \
  "${podman_image}" >/dev/null
podman_digest="$(
  podman image inspect "${podman_image}" --format '{{json .RepoDigests}}' | \
    jq -er '.[0] | split("@") | .[1]'
)"
test "${podman_digest}" = "${podman_push_digest}"

podman restart coffer-distribution-rgw >/dev/null
for _attempt in $(seq 1 30); do
  registry_status="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --cacert "${registry_ca}" "${registry_url}/v2/" || true
  )"
  if test "${registry_status}" = 401; then
    break
  fi
  sleep 1
done
test "${registry_status}" = 401
SSL_CERT_FILE="${ca_bundle}" skopeo copy --retry-times 3 \
  --src-authfile "${authfile_a}" "docker://${image_a}" \
  "oci:${temporary_directory}/pull-after:keystone" >/dev/null
after_digest="$(
  skopeo inspect --format '{{.Digest}}' \
    "oci:${temporary_directory}/pull-after:keystone"
)"
test "${after_digest}" = "${subject_digest}"

if SSL_CERT_FILE="${ca_bundle}" skopeo copy --retry-times 1 \
  --dest-authfile "${authfile_b}" "docker://${busybox_ref}" \
  "docker://${registry_host}/${repository_a}:project-b-denied" \
  >"${temporary_directory}/project-b-push.log" 2>&1; then
  printf 'project B unexpectedly pushed into project A namespace\n' >&2
  exit 31
fi

make_curl_config() {
  local fixture_name="$1"
  local output_path="$2"
  local credential_id
  local credential_secret
  credential_id="$(jq -er ".${fixture_name}.application_credential_id" \
    "${credential_file}")"
  credential_secret="$(jq -er ".${fixture_name}.application_credential_secret" \
    "${credential_file}")"
  printf 'user = "%s:%s"\n' "${credential_id}" "${credential_secret}" \
    >"${output_path}"
  chmod 0600 "${output_path}"
  unset credential_secret
}

make_curl_config project_a "${temporary_directory}/token-a.curl"
make_curl_config project_b "${temporary_directory}/token-b.curl"
for fixture_name in a b; do
  curl --fail --silent --show-error \
    --config "${temporary_directory}/token-${fixture_name}.curl" \
    --cacert "${token_ca}" \
    --dump-header "${temporary_directory}/token-${fixture_name}.headers" \
    --output "${temporary_directory}/token-${fixture_name}.json" \
    --get --data-urlencode "service=${token_service}" \
    --data-urlencode "scope=repository:${repository_a}:pull,push" \
    "${token_url}"
done

request_a_id="$(awk -F': ' 'tolower($1) == "x-openstack-request-id" {gsub("\\r", "", $2); print $2}' \
  "${temporary_directory}/token-a.headers")"
request_b_id="$(awk -F': ' 'tolower($1) == "x-openstack-request-id" {gsub("\\r", "", $2); print $2}' \
  "${temporary_directory}/token-b.headers")"
test -n "${request_a_id}"
test -n "${request_b_id}"
test "${request_a_id}" != "${request_b_id}"

make_bearer_config() {
  local token_file="$1"
  local output_path="$2"
  local bearer_token
  bearer_token="$(jq -er '.token' "${token_file}")"
  printf 'header = "Authorization: Bearer %s"\n' "${bearer_token}" \
    >"${output_path}"
  chmod 0600 "${output_path}"
  unset bearer_token
}

make_bearer_config "${temporary_directory}/token-a.json" \
  "${temporary_directory}/bearer-a.curl"
make_bearer_config "${temporary_directory}/token-b.json" \
  "${temporary_directory}/bearer-b.curl"
status_a="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --config "${temporary_directory}/bearer-a.curl" --cacert "${registry_ca}" \
    "${registry_url}/v2/${repository_a}/tags/list"
)"
status_b="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --config "${temporary_directory}/bearer-b.curl" --cacert "${registry_ca}" \
    "${registry_url}/v2/${repository_a}/tags/list"
)"
test "${status_a}" = 200
test "${status_b}" = 401

podman logs coffer-distribution-rgw \
  >/tmp/coffer-integration-distribution.log 2>&1
cp "${temporary_directory}/project-b-push.log" \
  /tmp/coffer-integration-project-b-push.log
chmod 0644 \
  /tmp/coffer-integration-distribution.log \
  /tmp/coffer-integration-project-b-push.log

while IFS= read -r secret_value; do
  test -n "${secret_value}"
  if grep -Fq -- "${secret_value}" \
    /tmp/coffer-integration-distribution.log \
    /tmp/coffer-integration-project-b-push.log; then
    printf 'application-credential secret leaked into guest logs\n' >&2
    exit 32
  fi
done < <(jq -r \
  '.project_a.application_credential_secret, .project_b.application_credential_secret' \
  "${credential_file}")
if grep -Eq 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  /tmp/coffer-integration-distribution.log \
  /tmp/coffer-integration-project-b-push.log; then
  printf 'registry bearer token leaked into guest logs\n' >&2
  exit 33
fi

jq -n \
  --arg project_a_id "${project_a_id}" \
  --arg project_b_id "${project_b_id}" \
  --arg repository "${repository_a}" \
  --arg digest "${subject_digest}" \
  --arg request_a_id "${request_a_id}" \
  --arg request_b_id "${request_b_id}" \
  --arg podman_digest "${podman_digest}" \
  --argjson project_a_status "${status_a}" \
  --argjson project_b_status "${status_b}" \
  '{keystone: "real DevStack", storage: "real Ceph RGW", distribution: "unmodified v3.1.1", clients: ["Skopeo", "Podman"], project_a_id: $project_a_id, project_b_id: $project_b_id, repository: $repository, digest: $digest, distribution_restart_digest: $digest, podman_digest: $podman_digest, project_a_status: $project_a_status, project_b_cross_project_status: $project_b_status, project_b_push: "denied", project_a_token_request_id: $request_a_id, project_b_token_request_id: $request_b_id}' \
  >/tmp/coffer-integration-evidence.json
chmod 0644 /tmp/coffer-integration-evidence.json

printf 'Real Keystone/Coffer/RGW integration passed digest=%s A=%s B=%s\n' \
  "${subject_digest}" "${status_a}" "${status_b}"
