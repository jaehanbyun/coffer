#!/usr/bin/env bash

set -euo pipefail

state_file="/root/coffer-kolla-aio-stage4-identities.json"
evidence_file="/root/coffer-kolla-aio-stage4-tenant-evidence.json"
registry_host="192.168.122.220:8788"
registry_url="https://${registry_host}"
keystone_url="https://192.168.122.220:5000/v3"
external_ca="/etc/kolla/certificates-stage4/ca/root.crt"
repository_name="stage4-proof"
token_service="coffer-registry"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
docker_ca_directory="/etc/docker/certs.d/${registry_host}"
temporary_directory="$(mktemp -d /root/coffer-stage4-tenant.XXXXXX)"
docker_ca_created=0
source_image_preexisting=0
source_image_checked=0
repository_image=""
denied_image=""

cleanup() {
  local exit_status=$?
  trap - EXIT
  if [[ -n "${denied_image}" ]]; then
    docker image rm --force "${denied_image}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${repository_image}" ]]; then
    docker image rm --force "${repository_image}" >/dev/null 2>&1 || true
  fi
  if (( source_image_checked && ! source_image_preexisting )); then
    docker image rm --force "${busybox_ref}" >/dev/null 2>&1 || true
  fi
  if (( docker_ca_created )); then
    rm -f -- "${docker_ca_directory}/ca.crt"
    rmdir -- "${docker_ca_directory}" 2>/dev/null || true
  fi
  rm -rf -- "${temporary_directory}"
  exit "${exit_status}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test -s "${state_file}"
test "$(stat -c '%a' "${state_file}")" = 600
test -s "${external_ca}"
test ! -e "${evidence_file}"
for command_name in curl docker jq openstack; do
  command -v "${command_name}" >/dev/null
done

if docker image inspect "${busybox_ref}" >/dev/null 2>&1; then
  source_image_preexisting=1
fi
source_image_checked=1
if test -e "${docker_ca_directory}"; then
  test -d "${docker_ca_directory}"
  test ! -e "${docker_ca_directory}/ca.crt"
else
  install -d -m 0755 "${docker_ca_directory}"
fi
install -m 0644 "${external_ca}" "${docker_ca_directory}/ca.crt"
docker_ca_created=1

project_a_id="$(jq -er '.project_a.project_id' "${state_file}")"
project_b_id="$(jq -er '.project_b.project_id' "${state_file}")"
credential_a_id="$(
  jq -er '.project_a.application_credential_id' "${state_file}"
)"
credential_b_id="$(
  jq -er '.project_b.application_credential_id' "${state_file}"
)"
test "${project_a_id}" != "${project_b_id}"

issue_keystone_token() {
  local fixture_name="$1"
  local token_path="$2"
  local credential_id
  local credential_secret
  credential_id="$(
    jq -er ".${fixture_name}.application_credential_id" "${state_file}"
  )"
  credential_secret="$(
    jq -er ".${fixture_name}.application_credential_secret" "${state_file}"
  )"
  env -u OS_TOKEN \
    OS_AUTH_TYPE=v3applicationcredential \
    OS_AUTH_URL="${keystone_url}" \
    OS_APPLICATION_CREDENTIAL_ID="${credential_id}" \
    OS_APPLICATION_CREDENTIAL_SECRET="${credential_secret}" \
    OS_CACERT="${external_ca}" \
    openstack token issue -f value -c id >"${token_path}"
  chmod 0600 "${token_path}"
  unset credential_secret
}

make_keystone_curl_config() {
  local token_path="$1"
  local output_path="$2"
  local token
  token="$(tr -d '\n' <"${token_path}")"
  test -n "${token}"
  printf 'header = "X-Auth-Token: %s"\n' "${token}" >"${output_path}"
  chmod 0600 "${output_path}"
  unset token
}

issue_keystone_token project_a "${temporary_directory}/keystone-a.token"
issue_keystone_token project_b "${temporary_directory}/keystone-b.token"
make_keystone_curl_config \
  "${temporary_directory}/keystone-a.token" \
  "${temporary_directory}/keystone-a.curl"
make_keystone_curl_config \
  "${temporary_directory}/keystone-b.token" \
  "${temporary_directory}/keystone-b.curl"

curl --fail --silent --show-error \
  --output "${temporary_directory}/repositories.json" \
  --config "${temporary_directory}/keystone-a.curl" \
  --cacert "${external_ca}" \
  "${registry_url}/v1/repositories"
matching_repositories="$(
  jq --arg name "${repository_name}" \
    '[.repositories[] | select(.name == $name)] | length' \
    "${temporary_directory}/repositories.json"
)"
case "${matching_repositories}" in
  0)
    control_status="$(
      curl --silent --show-error \
        --output "${temporary_directory}/repository.json" \
        --write-out '%{http_code}' \
        --config "${temporary_directory}/keystone-a.curl" \
        --cacert "${external_ca}" \
        --header 'Content-Type: application/json' \
        --data "{\"name\":\"${repository_name}\"}" \
        "${registry_url}/v1/repositories"
    )"
    test "${control_status}" = 201
    ;;
  1)
    control_status=200
    jq --arg name "${repository_name}" \
      '{repository: [.repositories[] | select(.name == $name)][0]}' \
      "${temporary_directory}/repositories.json" \
      >"${temporary_directory}/repository.json"
    ;;
  *)
    echo "multiple Stage 4 repositories matched the exact name" >&2
    exit 33
    ;;
esac
test "$(
  jq -er '.repository.project_id' "${temporary_directory}/repository.json"
)" = "${project_a_id}"
test "$(
  jq -er '.repository.name' "${temporary_directory}/repository.json"
)" = "${repository_name}"
repository_id="$(
  jq -er '.repository.id' "${temporary_directory}/repository.json"
)"
repository="p/${project_a_id}/${repository_name}"
repository_image="${registry_host}/${repository}:stage4"
denied_image="${registry_host}/${repository}:project-b-denied"

project_b_control_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --config "${temporary_directory}/keystone-b.curl" \
    --cacert "${external_ca}" \
    "${registry_url}/v1/repositories/${repository_id}"
)"
test "${project_b_control_status}" = 404

docker exec -i coffer_edge /usr/local/bin/python3 - "${project_a_id}" <<'PY'
import sys

from coffer.config import parse_config
from coffer.quota import QuotaStore

configuration = parse_config(
    args=["--config-file", "/etc/coffer/coffer.conf"]
)
QuotaStore(configuration.database.connection).set_limit(
    sys.argv[1],
    1024 * 1024 * 1024,
)
PY

make_basic_curl_config() {
  local fixture_name="$1"
  local output_path="$2"
  local credential_id
  local credential_secret
  credential_id="$(
    jq -er ".${fixture_name}.application_credential_id" "${state_file}"
  )"
  credential_secret="$(
    jq -er ".${fixture_name}.application_credential_secret" "${state_file}"
  )"
  printf 'user = "%s:%s"\n' "${credential_id}" "${credential_secret}" \
    >"${output_path}"
  chmod 0600 "${output_path}"
  unset credential_secret
}

make_bearer_curl_config() {
  local token_path="$1"
  local output_path="$2"
  local bearer
  bearer="$(jq -er '.token' "${token_path}")"
  printf 'header = "Authorization: Bearer %s"\n' "${bearer}" >"${output_path}"
  chmod 0600 "${output_path}"
  unset bearer
}

request_registry_token() {
  local fixture_name="$1"
  local output_path="$2"
  local basic_config="${temporary_directory}/basic-${fixture_name}.curl"
  make_basic_curl_config "${fixture_name}" "${basic_config}"
  curl --fail --silent --show-error \
    --config "${basic_config}" \
    --cacert "${external_ca}" \
    --output "${output_path}" \
    --get \
    --data-urlencode "service=${token_service}" \
    --data-urlencode "scope=repository:${repository}:pull,push,delete" \
    "${registry_url}/auth/token"
  chmod 0600 "${output_path}"
}

install -d -m 0700 \
  "${temporary_directory}/docker-a" \
  "${temporary_directory}/docker-b"
jq -er '.project_a.application_credential_secret' "${state_file}" |
  docker --config "${temporary_directory}/docker-a" login \
    --username "${credential_a_id}" --password-stdin "${registry_host}" \
    >/dev/null 2>&1
jq -er '.project_b.application_credential_secret' "${state_file}" |
  docker --config "${temporary_directory}/docker-b" login \
    --username "${credential_b_id}" --password-stdin "${registry_host}" \
    >/dev/null 2>&1
find \
  "${temporary_directory}/docker-a" \
  "${temporary_directory}/docker-b" \
  -type f -exec chmod 0600 {} +

docker pull --quiet "${busybox_ref}" >/dev/null
docker tag "${busybox_ref}" "${repository_image}"
docker --config "${temporary_directory}/docker-a" push --quiet \
  "${repository_image}" >/dev/null

request_registry_token project_a "${temporary_directory}/registry-a.json"
request_registry_token project_b "${temporary_directory}/registry-b.json"
make_bearer_curl_config \
  "${temporary_directory}/registry-a.json" \
  "${temporary_directory}/bearer-a.curl"
make_bearer_curl_config \
  "${temporary_directory}/registry-b.json" \
  "${temporary_directory}/bearer-b.curl"

curl --fail --silent --show-error \
  --config "${temporary_directory}/bearer-a.curl" \
  --cacert "${external_ca}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
  --header 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
  --dump-header "${temporary_directory}/manifest-a.headers" \
  --output /dev/null \
  "${registry_url}/v2/${repository}/manifests/stage4"
subject_digest="$(
  awk -F': ' '
    tolower($1) == "docker-content-digest" {
      gsub("\r", "", $2)
      print $2
    }
  ' "${temporary_directory}/manifest-a.headers"
)"
case "${subject_digest}" in
  sha256:[0-9a-f][0-9a-f]*) ;;
  *) exit 34 ;;
esac

docker image rm --force "${repository_image}" >/dev/null
docker --config "${temporary_directory}/docker-a" pull --quiet \
  "${repository_image}" >/dev/null
docker image inspect "${repository_image}" \
  --format '{{json .RepoDigests}}' |
  jq -e --arg expected "${registry_host}/${repository}@${subject_digest}" \
    'index($expected) != null' >/dev/null

if docker --config "${temporary_directory}/docker-b" pull \
  "${repository_image}" >"${temporary_directory}/project-b-pull.log" 2>&1; then
  echo "project B unexpectedly pulled project A content" >&2
  exit 35
fi
docker tag "${busybox_ref}" "${denied_image}"
if docker --config "${temporary_directory}/docker-b" push \
  "${denied_image}" >"${temporary_directory}/project-b-push.log" 2>&1; then
  echo "project B unexpectedly pushed into project A repository" >&2
  exit 36
fi

project_a_tags_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --config "${temporary_directory}/bearer-a.curl" \
    --cacert "${external_ca}" \
    "${registry_url}/v2/${repository}/tags/list"
)"
project_b_tags_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --config "${temporary_directory}/bearer-b.curl" \
    --cacert "${external_ca}" \
    "${registry_url}/v2/${repository}/tags/list"
)"
project_b_mount_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request POST \
    --config "${temporary_directory}/bearer-b.curl" \
    --cacert "${external_ca}" \
    --get \
    --data-urlencode "mount=${subject_digest}" \
    --data-urlencode "from=${repository}" \
    "${registry_url}/v2/${repository}/blobs/uploads/"
)"
project_b_overwrite_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request PUT \
    --config "${temporary_directory}/bearer-b.curl" \
    --cacert "${external_ca}" \
    --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
    --data '{}' \
    "${registry_url}/v2/${repository}/manifests/stage4"
)"
project_b_delete_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request DELETE \
    --config "${temporary_directory}/bearer-b.curl" \
    --cacert "${external_ca}" \
    "${registry_url}/v2/${repository}/manifests/${subject_digest}"
)"
test "${project_a_tags_status}" = 200
test "${project_b_tags_status}" = 401
test "${project_b_mount_status}" = 401
test "${project_b_overwrite_status}" = 401
test "${project_b_delete_status}" = 401

for backend_port in 8787 8789; do
  if curl --silent --show-error --connect-timeout 2 --max-time 4 \
    --output /dev/null --cacert "${external_ca}" \
    "https://192.168.122.220:${backend_port}/" 2>/dev/null; then
    echo "external backend bypass unexpectedly succeeded on ${backend_port}" >&2
    exit 37
  fi
done

while IFS= read -r secret_value; do
  test -n "${secret_value}"
  if docker logs coffer_api 2>&1 |
      grep -Fq -- "${secret_value}" ||
    docker logs coffer_edge 2>&1 |
      grep -Fq -- "${secret_value}" ||
    docker logs coffer_registry 2>&1 |
      grep -Fq -- "${secret_value}"; then
    echo "application credential secret leaked into Coffer logs" >&2
    exit 38
  fi
done < <(
  jq -r '
    .project_a.application_credential_secret,
    .project_b.application_credential_secret
  ' "${state_file}"
)

jq -n \
  --arg repository "${repository}" \
  --arg digest "${subject_digest}" \
  --argjson project_a_tags_status "${project_a_tags_status}" \
  --argjson project_b_control_status "${project_b_control_status}" \
  --argjson project_b_tags_status "${project_b_tags_status}" \
  --argjson project_b_mount_status "${project_b_mount_status}" \
  --argjson project_b_overwrite_status "${project_b_overwrite_status}" \
  --argjson project_b_delete_status "${project_b_delete_status}" \
  '{
    client: "Docker",
    repository: $repository,
    digest: $digest,
    project_a_push_pull: "passed",
    project_a_tags_status: $project_a_tags_status,
    project_b_control_status: $project_b_control_status,
    project_b_pull: "denied",
    project_b_push: "denied",
    project_b_tags_status: $project_b_tags_status,
    project_b_mount_status: $project_b_mount_status,
    project_b_overwrite_status: $project_b_overwrite_status,
    project_b_delete_status: $project_b_delete_status,
    external_backend_bypass: "denied"
  }' >"${evidence_file}"
chmod 0600 "${evidence_file}"

printf 'Stage 4 tenant OCI acceptance passed digest=%s A=%s B=%s\n' \
  "${subject_digest}" "${project_a_tags_status}" "${project_b_tags_status}"
