#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
work_directory="${repository_root}/work/quota"
docker_config="${work_directory}/docker-config"
edge_host="127.0.0.1:5002"
edge_url="http://${edge_host}"
token_url="${edge_url}/auth/token"

cleanup() {
  docker compose --project-directory "${script_dir}" logs --no-color \
    edge registry docker-daemon \
    >"${work_directory}/services.log" 2>&1 || true
  docker compose --project-directory "${script_dir}" --profile client down \
    --volumes --remove-orphans >/dev/null 2>&1 || true
  docker logout "${edge_host}" >/dev/null 2>&1 || true
  rm -f "${work_directory}/fixture.env" "${work_directory}/private.pem" \
    "${work_directory}/client.env" \
    "${work_directory}/concurrent-a.json" \
    "${work_directory}/concurrent-b.json" \
    "${work_directory}/concurrent-a.status" \
    "${work_directory}/concurrent-b.status" \
    "${work_directory}/concurrent-a.response" \
    "${work_directory}/concurrent-b.response" \
    "${work_directory}/manifest.json" "${work_directory}/upload.bin" \
    "${work_directory}/forged.json" \
    "${work_directory}/headers.txt" "${work_directory}/jwks.json"
  rm -rf "${docker_config}"
}
trap cleanup EXIT

for command_name in curl docker jq rg shasum uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

mkdir -p "${work_directory}" "${docker_config}"
chmod 700 "${work_directory}" "${docker_config}"
docker_host="${DOCKER_HOST:-}"
if test -z "${docker_host}"; then
  docker_host="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
fi
export DOCKER_CONFIG="${docker_config}"
export DOCKER_HOST="${docker_host}"

docker compose --project-directory "${script_dir}" build edge
uv run --project "${repository_root}" python \
  "${script_dir}/generate_fixture.py" "${work_directory}"
set -a
# Generated only for this disposable fixture.
# shellcheck disable=SC1091
source "${work_directory}/fixture.env"
set +a
docker compose --project-directory "${script_dir}" up --detach minio minio-init registry edge
for _attempt in $(seq 1 90); do
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    "${edge_url}/v2/" || true)"
  if test "${status}" = 401; then
    break
  fi
  sleep 2
done
test "${status}" = 401

registry_state="$(docker compose --project-directory "${script_dir}" ps registry \
  --format json)"
registry_publisher_count="$(printf '%s' "${registry_state}" | \
  jq -s '[.. | objects | .Publishers[]? | select((.PublishedPort // 0) > 0)] | length')"
registry_port_bindings="$(docker compose --project-directory "${script_dir}" \
  ps --quiet registry | xargs docker inspect --format '{{json .HostConfig.PortBindings}}')"
printf 'Quota edge ready status=%s registry_publishers=%s bindings=%s\n' \
  "${status}" "${registry_publisher_count}" "${registry_port_bindings}"
test "${registry_publisher_count}" -eq 0
test "$(printf '%s' "${registry_port_bindings}" | jq 'length')" -eq 0
topology="$(docker compose --project-directory "${script_dir}" \
  --profile client config --format json)"
printf '%s' "${topology}" | jq -e '
  (.services.edge.networks | keys | sort) == ["backend", "client"] and
  (.services.registry.networks | keys | sort) == ["backend", "storage"] and
  (.services.minio.networks | keys) == ["storage"] and
  (.services["docker-daemon"].networks | keys) == ["client"] and
  (.services.podman.networks | keys) == ["client"] and
  (.services.skopeo.networks | keys) == ["client"]' >/dev/null

docker_repository="p/${COFFER_QUOTA_PROJECT_A}/docker-proof"
docker compose --project-directory "${script_dir}" --profile client up \
  --detach docker-daemon
for _attempt in $(seq 1 60); do
  if docker compose --project-directory "${script_dir}" exec -T docker-daemon \
    docker info >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose --project-directory "${script_dir}" exec -T docker-daemon \
  sh -ec 'command -v getent >/dev/null; ! getent hosts registry >/dev/null 2>&1; ! getent hosts minio >/dev/null 2>&1; test ! -e /runtime/private.pem; test ! -e /runtime/fixture.env; test "$(wc -l </runtime/client.env | tr -d " ")" -eq 3'
docker compose --project-directory "${script_dir}" exec -T docker-daemon \
  sh -ec '. /runtime/client.env; printf "%s" "$COFFER_QUOTA_MEMBER_SECRET" | docker login edge:5000 --username "$COFFER_QUOTA_MEMBER_ID" --password-stdin >/dev/null; docker pull "docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028" >/dev/null; docker tag "docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028" "edge:5000/p/$COFFER_QUOTA_PROJECT_A/docker-proof:docker"; docker push "edge:5000/p/$COFFER_QUOTA_PROJECT_A/docker-proof:docker" >/dev/null'

docker compose --project-directory "${script_dir}" --profile client run --rm \
  podman '. /runtime/client.env; printf "%s" "$COFFER_QUOTA_MEMBER_SECRET" | podman --root /tmp/podman-root --runroot /tmp/podman-runroot --storage-driver=vfs login --tls-verify=false --username "$COFFER_QUOTA_MEMBER_ID" --password-stdin edge:5000 >/dev/null; podman --root /tmp/podman-root --runroot /tmp/podman-runroot --storage-driver=vfs pull "docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028" >/dev/null; podman --root /tmp/podman-root --runroot /tmp/podman-runroot --storage-driver=vfs tag "docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028" "edge:5000/p/$COFFER_QUOTA_PROJECT_A/podman-proof:podman"; podman --root /tmp/podman-root --runroot /tmp/podman-runroot --storage-driver=vfs push --tls-verify=false "edge:5000/p/$COFFER_QUOTA_PROJECT_A/podman-proof:podman" >/dev/null'

docker compose --project-directory "${script_dir}" --profile client run --rm \
  skopeo '. /runtime/client.env; skopeo copy --retry-times 1 --dest-tls-verify=false --dest-creds "$COFFER_QUOTA_MEMBER_ID:$COFFER_QUOTA_MEMBER_SECRET" "docker://docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028" "docker://edge:5000/p/$COFFER_QUOTA_PROJECT_A/skopeo-proof:skopeo" >/dev/null'

token_for() {
  local credential_id="$1"
  local credential_secret="$2"
  local repository="$3"
  local actions="$4"
  curl --fail --silent --show-error \
    --user "${credential_id}:${credential_secret}" \
    --get --data-urlencode 'service=coffer-quota-registry' \
    --data-urlencode "scope=repository:${repository}:${actions}" \
    "${token_url}" | jq -er '.token'
}

token_for_mount() {
  local credential_id="$1"
  local credential_secret="$2"
  local source_repository="$3"
  local target_repository="$4"
  curl --fail --silent --show-error \
    --user "${credential_id}:${credential_secret}" \
    --get --data-urlencode 'service=coffer-quota-registry' \
    --data-urlencode "scope=repository:${source_repository}:pull" \
    --data-urlencode "scope=repository:${target_repository}:pull,push" \
    "${token_url}" | jq -er '.token'
}

physical_object_count() {
  docker compose --project-directory "${script_dir}" run --rm minio-init \
    'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null; mc find local/coffer-registry | wc -l' \
    | tail -1 | tr -d ' '
}

docker_pull_token="$(token_for \
  "${COFFER_QUOTA_MEMBER_ID}" "${COFFER_QUOTA_MEMBER_SECRET}" \
  "${docker_repository}" pull)"
curl --fail --silent --show-error \
  --header "Authorization: Bearer ${docker_pull_token}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
  "${edge_url}/v2/${docker_repository}/manifests/docker" \
  >"${work_directory}/manifest.json"
jq -c '.mediaType="application/vnd.oci.image.manifest.v1+json" | .annotations={"org.opencontainers.image.title":"a"}' \
  "${work_directory}/manifest.json" >"${work_directory}/concurrent-a.json"
jq -c '.mediaType="application/vnd.oci.image.manifest.v1+json" | .annotations={"org.opencontainers.image.title":"b"}' \
  "${work_directory}/manifest.json" >"${work_directory}/concurrent-b.json"
concurrent_a="p/${COFFER_QUOTA_PROJECT_A}/concurrent-a"
concurrent_b="p/${COFFER_QUOTA_PROJECT_A}/concurrent-b"
for target_repository in "${concurrent_a}" "${concurrent_b}"; do
  mount_token="$(token_for_mount \
    "${COFFER_QUOTA_MEMBER_ID}" "${COFFER_QUOTA_MEMBER_SECRET}" \
    "${docker_repository}" "${target_repository}")"
  while IFS= read -r descriptor_digest; do
    mount_status="$(curl --silent --show-error --output /dev/null \
      --write-out '%{http_code}' --request POST \
      --header "Authorization: Bearer ${mount_token}" \
      --url-query "mount=${descriptor_digest}" \
      --url-query "from=${docker_repository}" \
      "${edge_url}/v2/${target_repository}/blobs/uploads/")"
    test "${mount_status}" = 201
  done < <(jq -r '.config.digest, .layers[].digest' \
    "${work_directory}/manifest.json")
done
manifest_bytes="$(wc -c <"${work_directory}/concurrent-a.json" | tr -d ' ')"
test "${manifest_bytes}" -eq "$(wc -c <"${work_directory}/concurrent-b.json" | tr -d ' ')"
docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py set-headroom "$1"' \
  sh "${manifest_bytes}" \
  >"${work_directory}/quota-before-concurrency.json"

token_a="$(token_for "${COFFER_QUOTA_MEMBER_ID}" \
  "${COFFER_QUOTA_MEMBER_SECRET}" "${concurrent_a}" pull,push)"
token_b="$(token_for "${COFFER_QUOTA_MEMBER_ID}" \
  "${COFFER_QUOTA_MEMBER_SECRET}" "${concurrent_b}" pull,push)"
usage_before_bypass="$(docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py usage' | jq -c .)"
jq -c '.config.size=0' "${work_directory}/concurrent-a.json" \
  >"${work_directory}/forged.json"
forged_status="$(curl --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --request PUT \
  --header "Authorization: Bearer ${token_a}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --data-binary "@${work_directory}/forged.json" \
  "${edge_url}/v2/${concurrent_a}/manifests/forged")"
test "${forged_status}" = 400
encoded_path="/v2/p%252F${COFFER_QUOTA_PROJECT_A}%252Fconcurrent-a%252Fmanifests%252Fencoded"
encoded_status="$(curl --path-as-is --silent --show-error --output /dev/null \
  --write-out '%{http_code}' --request PUT \
  --header "Authorization: Bearer ${token_a}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --data-binary "@${work_directory}/concurrent-a.json" \
  "${edge_url}${encoded_path}")"
test "${encoded_status}" = 400
usage_after_bypass="$(docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py usage' | jq -c .)"
test "${usage_before_bypass}" = "${usage_after_bypass}"
curl --silent --show-error --output "${work_directory}/concurrent-a.response" \
  --write-out '%{http_code}' --request PUT \
  --header "Authorization: Bearer ${token_a}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --header 'X-Openstack-Request-Id: req-concurrent-a' \
  --data-binary "@${work_directory}/concurrent-a.json" \
  "${edge_url}/v2/${concurrent_a}/manifests/latest" \
  >"${work_directory}/concurrent-a.status" &
pid_a="$!"
curl --silent --show-error --output "${work_directory}/concurrent-b.response" \
  --write-out '%{http_code}' --request PUT \
  --header "Authorization: Bearer ${token_b}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --header 'X-Openstack-Request-Id: req-concurrent-b' \
  --data-binary "@${work_directory}/concurrent-b.json" \
  "${edge_url}/v2/${concurrent_b}/manifests/latest" \
  >"${work_directory}/concurrent-b.status" &
pid_b="$!"
wait "${pid_a}"
wait "${pid_b}"
status_a="$(cat "${work_directory}/concurrent-a.status")"
status_b="$(cat "${work_directory}/concurrent-b.status")"
test "$(printf '%s\n%s\n' "${status_a}" "${status_b}" | sort | tr '\n' ' ')" = '201 429 '

if test "${status_a}" = 201; then
  admitted_repository="${concurrent_a}"
  admitted_token="${token_a}"
  admitted_body="${work_directory}/concurrent-a.json"
  admitted_request_id=req-concurrent-a
  denied_response="${work_directory}/concurrent-b.response"
else
  admitted_repository="${concurrent_b}"
  admitted_token="${token_b}"
  admitted_body="${work_directory}/concurrent-b.json"
  admitted_request_id=req-concurrent-b
  denied_response="${work_directory}/concurrent-a.response"
fi
jq -e '.errors == [{"code":"TOOMANYREQUESTS","message":"project logical quota exceeded"}]' \
  "${denied_response}" >/dev/null
retry_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --request PUT --header "Authorization: Bearer ${admitted_token}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --header "X-Openstack-Request-Id: ${admitted_request_id}" \
  --data-binary "@${admitted_body}" \
  "${edge_url}/v2/${admitted_repository}/manifests/latest")"
test "${retry_status}" = 201
docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py usage' \
  >"${work_directory}/quota-after-concurrency.json"
jq -e '.reserved_bytes == 0 and .used_bytes <= .limit_bytes' \
  "${work_directory}/quota-after-concurrency.json" >/dev/null

unavailable_repository="p/${COFFER_QUOTA_PROJECT_B}/unavailable"
unavailable_token="$(token_for \
  "${COFFER_QUOTA_PROJECT_B_MEMBER_ID}" \
  "${COFFER_QUOTA_PROJECT_B_MEMBER_SECRET}" \
  "${unavailable_repository}" pull,push)"
unavailable_status="$(curl --silent --show-error \
  --output "${work_directory}/unavailable.response" --write-out '%{http_code}' \
  --request PUT --header "Authorization: Bearer ${unavailable_token}" \
  --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
  --data-binary "@${work_directory}/concurrent-a.json" \
  "${edge_url}/v2/${unavailable_repository}/manifests/latest")"
test "${unavailable_status}" = 503
jq -e '.errors[0].code == "UNAVAILABLE"' \
  "${work_directory}/unavailable.response" >/dev/null

staging_repository="p/${COFFER_QUOTA_PROJECT_A}/staging"
staging_token="$(token_for "${COFFER_QUOTA_MEMBER_ID}" \
  "${COFFER_QUOTA_MEMBER_SECRET}" "${staging_repository}" pull,push)"
printf 'coffer-unpublished-physical-staging-proof\n' \
  >"${work_directory}/upload.bin"
upload_digest="sha256:$(shasum -a 256 "${work_directory}/upload.bin" | awk '{print $1}')"
usage_before_staging="$(docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py usage' | jq -c .)"
physical_before="$(physical_object_count)"
curl --silent --show-error --dump-header "${work_directory}/headers.txt" \
  --output /dev/null --request POST --header 'Content-Length: 0' \
  --header "Authorization: Bearer ${staging_token}" \
  "${edge_url}/v2/${staging_repository}/blobs/uploads/"
upload_location="$(awk -F': ' 'tolower($1) == "location" {gsub("\r", "", $2); print $2}' \
  "${work_directory}/headers.txt")"
test -n "${upload_location}"
case "${upload_location}" in
  http://*|https://*) upload_url="${upload_location}" ;;
  *) upload_url="${edge_url}${upload_location}" ;;
esac
curl --fail --silent --show-error --dump-header "${work_directory}/headers.txt" \
  --output /dev/null --request PATCH \
  --header "Authorization: Bearer ${staging_token}" \
  --header 'Content-Type: application/octet-stream' \
  --data-binary "@${work_directory}/upload.bin" "${upload_url}"
upload_location="$(awk -F': ' 'tolower($1) == "location" {gsub("\r", "", $2); print $2}' \
  "${work_directory}/headers.txt")"
case "${upload_location}" in
  http://*|https://*) upload_url="${upload_location}" ;;
  *) upload_url="${edge_url}${upload_location}" ;;
esac
separator='?'
[[ "${upload_url}" == *\?* ]] && separator='&'
curl --fail --silent --show-error --output /dev/null --request PUT \
  --header "Authorization: Bearer ${staging_token}" \
  --header 'Content-Length: 0' \
  "${upload_url}${separator}digest=${upload_digest}"
usage_after_staging="$(docker compose --project-directory "${script_dir}" exec -T edge \
  sh -ec 'set -a; . /runtime/fixture.env; exec python /app/poc/quota/fixture_admin.py usage' | jq -c .)"
physical_after="$(physical_object_count)"
test "${usage_before_staging}" = "${usage_after_staging}"
test "${physical_after}" -gt "${physical_before}"

docker compose --project-directory "${script_dir}" logs --no-color \
  edge registry docker-daemon \
  >"${work_directory}/services.log"
if rg --fixed-strings --quiet \
  -e "${COFFER_QUOTA_MEMBER_SECRET}" \
  -e "${COFFER_QUOTA_PROJECT_B_MEMBER_SECRET}" \
  "${work_directory}/services.log" \
  "${work_directory}/concurrent-a.response" \
  "${work_directory}/concurrent-b.response" \
  "${work_directory}/unavailable.response"; then
  printf 'quota fixture credential leaked into retained logs\n' >&2
  exit 70
fi
if rg --quiet 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${work_directory}/services.log"; then
  printf 'quota fixture bearer token leaked into retained logs\n' >&2
  exit 71
fi

printf 'Quota edge passed clients=docker,podman,skopeo statuses=%s/%s physical=%s->%s\n' \
  "${status_a}" "${status_b}" "${physical_before}" "${physical_after}"
