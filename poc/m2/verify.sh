#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/../.." && pwd)"
work_dir="${repo_dir}/work/m2"
docker_config="${work_dir}/docker-config"
registry_host="127.0.0.1:5001"
registry_url="http://${registry_host}"
token_url="http://127.0.0.1:8081/auth/token"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
server_pid=""

cleanup() {
  docker compose --project-directory "${script_dir}" logs --no-color registry \
    >"${work_dir}/registry.log" 2>&1 || true
  docker compose --project-directory "${script_dir}" down --volumes \
    --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${server_pid}" ]]; then
    kill "${server_pid}" >/dev/null 2>&1 || true
    wait "${server_pid}" 2>/dev/null || true
  fi
  rm -f "${work_dir}/fixture.env" "${work_dir}/negative-tokens.json" \
    "${work_dir}/private.pem" "${work_dir}/next-private.pem" \
    "${work_dir}/pulled-layer" "${work_dir}/coffer.sqlite"
  rm -rf "${docker_config}"
}
trap cleanup EXIT

for command_name in curl docker jq rg shasum uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

mkdir -p "${work_dir}" "${docker_config}"
uv run --project "${repo_dir}" python "${script_dir}/generate_fixture.py" "${work_dir}"
docker_host="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
set -a
# Generated at runtime by generate_fixture.py; no static source file exists.
# shellcheck disable=SC1091
source "${work_dir}/fixture.env"
set +a
export DOCKER_CONFIG="${docker_config}"
export DOCKER_HOST="${docker_host}"

uv run --project "${repo_dir}" gunicorn \
  --bind 127.0.0.1:8081 \
  --workers 1 \
  --worker-class gthread \
  --threads 2 \
  --chdir "${script_dir}" \
  fixture_server:application >"${work_dir}/token-server.log" 2>&1 &
server_pid="$!"

for attempt in {1..30}; do
  if curl --silent --output /dev/null --write-out '%{http_code}' \
    "${token_url}" | grep -q '400'; then
    break
  fi
  if [[ "${attempt}" == 30 ]]; then
    printf 'token service did not become ready\n' >&2
    exit 1
  fi
  sleep 1
done

docker compose --project-directory "${script_dir}" up --detach

challenge_file="${work_dir}/challenge.headers"
for attempt in {1..60}; do
  registry_status="$(curl --silent --show-error --output /dev/null \
    --dump-header "${challenge_file}" --write-out '%{http_code}' \
    "${registry_url}/v2/" || true)"
  if [[ "${registry_status}" == 401 ]]; then
    break
  fi
  if [[ "${attempt}" == 60 ]]; then
    printf 'authenticated registry did not become ready\n' >&2
    docker compose --project-directory "${script_dir}" logs registry >&2
    exit 1
  fi
  sleep 1
done

rg -q 'realm="http://host.docker.internal:8081/auth/token"' "${challenge_file}"
rg -q 'service="coffer-m2-registry"' "${challenge_file}"
test "$(jq '.keys | length' "${work_dir}/jwks.json")" -eq 2

printf '%s' "${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" | \
  docker login "${registry_host}" \
    --username "${COFFER_M2_MEMBER_CREDENTIAL_ID}" \
    --password-stdin >/dev/null
offline_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode 'offline_token=true' "${token_url}")"
test "$(printf '%s' "${offline_response}" | jq -r 'has("refresh_token")')" = false

repository="p/${COFFER_M2_PROJECT_ID}/demo"
image_ref="${registry_host}/${repository}:authenticated"
docker pull "${busybox_ref}" >/dev/null
docker tag "${busybox_ref}" "${image_ref}"
docker push "${image_ref}" >/dev/null
docker pull "${image_ref}" >/dev/null

pull_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${repository}:pull" "${token_url}")"
pull_token="$(printf '%s' "${pull_response}" | jq -er '.token')"
subject_digest="$(curl --fail --silent --show-error --head \
  --header "Authorization: Bearer ${pull_token}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "${registry_url}/v2/${repository}/manifests/authenticated" | \
  awk -F': ' 'tolower($1) == "docker-content-digest" {gsub("\\r", "", $2); print $2}')"
test -n "${subject_digest}"
manifest_response="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer ${pull_token}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "${registry_url}/v2/${repository}/manifests/authenticated")"
layer_digest="$(printf '%s' "${manifest_response}" | jq -er '.layers[0].digest')"

delete_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${repository}:delete" "${token_url}")"
test "$(printf '%s' "${delete_response}" | jq '.refresh_token? // empty' | wc -c)" -eq 0
delete_token="$(printf '%s' "${delete_response}" | jq -er '.token')"
delete_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request DELETE --header "Authorization: Bearer ${delete_token}" \
  "${registry_url}/v2/${repository}/manifests/${subject_digest}")"
test "${delete_status}" = 401

docker compose --project-directory "${script_dir}" restart registry >/dev/null
for attempt in {1..30}; do
  if curl --silent --output /dev/null --write-out '%{http_code}' \
    "${registry_url}/v2/" | grep -q '401'; then
    break
  fi
  sleep 1
done
docker pull "${image_ref}" >/dev/null
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${pull_token}" \
  --output "${work_dir}/pulled-layer" \
  "${registry_url}/v2/${repository}/blobs/${layer_digest}"
layer_sha256="sha256:$(shasum -a 256 "${work_dir}/pulled-layer" | awk '{print $1}')"
test "${layer_sha256}" = "${layer_digest}"

unauthorized_ref="${registry_host}/p/${COFFER_M2_PROJECT_B_ID}/demo:denied"
docker tag "${busybox_ref}" "${unauthorized_ref}"
if docker push "${unauthorized_ref}" >"${work_dir}/cross-project.log" 2>&1; then
  printf 'cross-project push unexpectedly succeeded\n' >&2
  exit 1
fi
missing_repository="p/${COFFER_M2_PROJECT_ID}/missing"
missing_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${missing_repository}:pull,push" \
  "${token_url}")"
missing_token="$(printf '%s' "${missing_response}" | jq -er '.token')"
missing_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer ${missing_token}" \
  "${registry_url}/v2/${missing_repository}/tags/list")"
test "${missing_status}" = 401

printf '%s' "${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET}" | \
  docker login "${registry_host}" \
    --username "${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_ID}" \
    --password-stdin >/dev/null
source_repository="p/${COFFER_M2_PROJECT_B_ID}/mount-source"
source_ref="${registry_host}/${source_repository}:source"
docker tag "${busybox_ref}" "${source_ref}"
docker push "${source_ref}" >/dev/null
source_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_ID}:${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${source_repository}:pull" "${token_url}")"
source_token="$(printf '%s' "${source_response}" | jq -er '.token')"
source_manifest="$(curl --fail --silent --show-error \
  --header "Authorization: Bearer ${source_token}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "${registry_url}/v2/${source_repository}/manifests/source")"
source_blob_digest="$(printf '%s' "${source_manifest}" | jq -er '.layers[0].digest')"

project_b_target_repository="p/${COFFER_M2_PROJECT_B_ID}/mount-target"
project_b_mount_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_ID}:${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${project_b_target_repository}:pull,push" \
  --data-urlencode "scope=repository:${source_repository}:pull" "${token_url}")"
project_b_mount_token="$(printf '%s' "${project_b_mount_response}" | jq -er '.token')"
project_b_mount_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request POST --get --header 'Content-Length: 0' \
  --header "Authorization: Bearer ${project_b_mount_token}" \
  --data-urlencode "mount=${source_blob_digest}" \
  --data-urlencode "from=${source_repository}" \
  "${registry_url}/v2/${project_b_target_repository}/blobs/uploads/")"
if [[ "${project_b_mount_status}" != 201 ]]; then
  printf 'same-project mount returned %s\n' "${project_b_mount_status}" >&2
  exit 1
fi
project_b_target_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --head --header "Authorization: Bearer ${project_b_mount_token}" \
  "${registry_url}/v2/${project_b_target_repository}/blobs/${source_blob_digest}")"
test "${project_b_target_status}" = 200

target_repository="p/${COFFER_M2_PROJECT_ID}/mount-target"
mount_response="$(curl --fail --silent --show-error \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=coffer-m2-registry' \
  --data-urlencode "scope=repository:${target_repository}:pull,push" \
  --data-urlencode "scope=repository:${source_repository}:pull" "${token_url}")"
mount_token="$(printf '%s' "${mount_response}" | jq -er '.token')"
for mount_digest in \
  "${source_blob_digest}" \
  'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; do
  mount_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST --get --header 'Content-Length: 0' \
    --header "Authorization: Bearer ${mount_token}" \
    --data-urlencode "mount=${mount_digest}" \
    --data-urlencode "from=${source_repository}" \
    "${registry_url}/v2/${target_repository}/blobs/uploads/")"
  if [[ "${mount_status}" != 401 ]]; then
    printf 'cross-project mount returned %s for %s\n' \
      "${mount_status}" "${mount_digest}" >&2
    exit 1
  fi
  target_blob_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --head --header "Authorization: Bearer ${mount_token}" \
    "${registry_url}/v2/${target_repository}/blobs/${mount_digest}")"
  if [[ "${target_blob_status}" != 404 ]]; then
    printf 'cross-project blob became visible with status %s for %s\n' \
      "${target_blob_status}" "${mount_digest}" >&2
    exit 1
  fi
done

printf '%s' "${COFFER_M2_READER_CREDENTIAL_SECRET}" | \
  docker login "${registry_host}" \
    --username "${COFFER_M2_READER_CREDENTIAL_ID}" \
    --password-stdin >/dev/null
docker pull "${image_ref}" >/dev/null
reader_denied_ref="${registry_host}/p/${COFFER_M2_PROJECT_ID}/reader-denied:latest"
docker tag "${busybox_ref}" "${reader_denied_ref}"
if docker push "${reader_denied_ref}" >"${work_dir}/reader-push.log" 2>&1; then
  printf 'reader push unexpectedly succeeded\n' >&2
  exit 1
fi

invalid_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:wrong-fixture-secret" \
  --get --data-urlencode 'service=coffer-m2-registry' "${token_url}")"
test "${invalid_status}" = 401

wrong_service_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --user "${COFFER_M2_MEMBER_CREDENTIAL_ID}:${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  --get --data-urlencode 'service=wrong-service' "${token_url}")"
test "${wrong_service_status}" = 400

uv run --project "${repo_dir}" python "${script_dir}/generate_negative_tokens.py" \
  "${work_dir}/negative-tokens.json"
for token_case in expired future tampered wrong_algorithm wrong_audience wrong_issuer; do
  negative_token="$(jq -er --arg token_case "${token_case}" '.[$token_case]' \
    "${work_dir}/negative-tokens.json")"
  negative_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    --header "Authorization: Bearer ${negative_token}" \
    "${registry_url}/v2/${repository}/tags/list")"
  if [[ "${negative_status}" != 401 ]]; then
    printf 'negative bearer case %s returned %s\n' \
      "${token_case}" "${negative_status}" >&2
    exit 1
  fi
done
rotated_token="$(jq -er '.rotated' "${work_dir}/negative-tokens.json")"
rotated_status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Bearer ${rotated_token}" \
  "${registry_url}/v2/${repository}/tags/list")"
if [[ "${rotated_status}" != 200 ]]; then
  printf 'overlapping JWKS token returned %s\n' "${rotated_status}" >&2
  exit 1
fi

docker compose --project-directory "${script_dir}" logs --no-color registry \
  >"${work_dir}/registry.log"
rg -q 'Registry token decision request_id=req-.* result=issued' \
  "${work_dir}/token-server.log"

if rg --fixed-strings --quiet \
  -e "${COFFER_M2_MEMBER_CREDENTIAL_SECRET}" \
  -e "${COFFER_M2_READER_CREDENTIAL_SECRET}" \
  -e "${COFFER_M2_PROJECT_B_MEMBER_CREDENTIAL_SECRET}" \
  "${work_dir}/token-server.log" "${work_dir}/cross-project.log" \
  "${work_dir}/reader-push.log" "${work_dir}/registry.log"; then
  printf 'fixture credential leaked into captured logs\n' >&2
  exit 1
fi
if rg --quiet 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${work_dir}/token-server.log" "${work_dir}/cross-project.log" \
  "${work_dir}/reader-push.log" "${work_dir}/registry.log"; then
  printf 'registry bearer token leaked into captured logs\n' >&2
  exit 1
fi

printf 'M2 authenticated Distribution verification passed.\n'
