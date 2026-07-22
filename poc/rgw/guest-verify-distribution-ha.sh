#!/usr/bin/env bash

set -euo pipefail

distribution_image="docker.io/library/registry@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
primary_container="coffer-distribution-rgw"
secondary_container="coffer-distribution-rgw-2"
state_directory="/etc/coffer-rgw"
config_path="${state_directory}/distribution-config.yml"
runtime_env_path="${state_directory}/distribution-runtime.env"
tls_directory="${state_directory}/distribution-tls"
registry_ca="${tls_directory}/ca.crt"
primary_url="https://coffer-rgw-poc:5443"
secondary_url="https://coffer-rgw-poc:5444"
integration_evidence="/tmp/coffer-ha-integration-evidence.json"
ha_log="/tmp/coffer-distribution-ha.log"
ha_evidence="/tmp/coffer-distribution-ha-evidence.json"
temporary_directory="$(mktemp -d /tmp/coffer-distribution-ha.XXXXXX)"
primary_stopped=0

wait_for_endpoint() {
  local endpoint="$1"
  local status_code=""
  for _attempt in $(seq 1 60); do
    status_code="$(
      curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 3 --max-time 5 --cacert "${registry_ca}" \
        "${endpoint}/v2/" || true
    )"
    if test "${status_code}" = 200; then
      return 0
    fi
    sleep 2
  done
  printf 'Distribution endpoint did not become ready: %s status=%s\n' \
    "${endpoint}" "${status_code}" >&2
  return 1
}

location_path() {
  local location="$1"
  case "${location}" in
    http://*|https://*)
      location="${location#*://}"
      printf '/%s\n' "${location#*/}"
      ;;
    /*) printf '%s\n' "${location}" ;;
    *)
      printf 'unsupported upload location: %s\n' "${location}" >&2
      return 1
      ;;
  esac
}

cleanup() {
  local exit_status=$?
  trap - EXIT
  if (( primary_stopped )); then
    podman start "${primary_container}" >/dev/null 2>&1 || true
    wait_for_endpoint "${primary_url}" >/dev/null 2>&1 || true
  fi
  if podman container exists "${secondary_container}"; then
    podman rm --force "${secondary_container}" >/dev/null 2>&1 || true
  fi
  rm -rf -- "${temporary_directory}"
  exit "${exit_status}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test -f "${integration_evidence}"
test -f "${config_path}"
test -f "${runtime_env_path}"
test -f "${registry_ca}"
test "$(stat -c '%a' "${runtime_env_path}")" = 600
test "$(podman inspect "${primary_container}" --format '{{.State.Running}}')" = true
if grep -Eq '^auth:' "${config_path}"; then
  printf 'two-replica storage test requires the restored unauthenticated fixture\n' >&2
  exit 20
fi

if podman container exists "${secondary_container}"; then
  podman rm --force "${secondary_container}" >/dev/null
fi
install -d -m 0755 /etc/containers/certs.d/coffer-rgw-poc:5444
install -m 0644 "${registry_ca}" \
  /etc/containers/certs.d/coffer-rgw-poc:5444/ca.crt
podman run --detach \
  --name "${secondary_container}" \
  --label io.coffer.poc=distribution-rgw-secondary \
  --restart=no \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop=all \
  --security-opt no-new-privileges \
  --env-file "${runtime_env_path}" \
  --env SSL_CERT_FILE=/etc/distribution/rgw-ca.crt \
  --publish 5444:5443 \
  --volume "${config_path}:/etc/distribution/config.yml:ro" \
  --volume "/etc/ceph/coffer-rgw-root-ca.crt:/etc/distribution/rgw-ca.crt:ro" \
  --volume "${tls_directory}:/etc/distribution/tls:ro" \
  "${distribution_image}" >/dev/null
wait_for_endpoint "${primary_url}"
wait_for_endpoint "${secondary_url}"

integration_repository="$(jq -er '.repository' "${integration_evidence}")"
expected_integration_digest="$(jq -er '.digest' "${integration_evidence}")"
for endpoint in "${primary_url}" "${secondary_url}"; do
  manifest_headers="${temporary_directory}/manifest-$((RANDOM)).headers"
  manifest_status="$(
    curl --silent --show-error --output /dev/null \
      --dump-header "${manifest_headers}" --write-out '%{http_code}' \
      --cacert "${registry_ca}" \
      --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
      "${endpoint}/v2/${integration_repository}/manifests/keystone"
  )"
  test "${manifest_status}" = 200
  endpoint_digest="$(awk -F': ' 'tolower($1) == "docker-content-digest" {gsub("\\r", "", $2); print $2}' \
    "${manifest_headers}")"
  test "${endpoint_digest}" = "${expected_integration_digest}"
done

openssl rand 2097152 >"${temporary_directory}/blob"
dd if="${temporary_directory}/blob" of="${temporary_directory}/part-1" \
  bs=1048576 count=1 status=none
dd if="${temporary_directory}/blob" of="${temporary_directory}/part-2" \
  bs=1048576 skip=1 count=1 status=none
blob_digest="sha256:$(sha256sum "${temporary_directory}/blob" | cut -d' ' -f1)"
upload_repository="p/00000000-0000-0000-0000-000000000003/ha-resume"

post_headers="${temporary_directory}/post.headers"
post_status="$(
  curl --silent --show-error --output /dev/null --dump-header "${post_headers}" \
    --write-out '%{http_code}' --request POST --header 'Content-Length: 0' \
    --cacert "${registry_ca}" \
    "${primary_url}/v2/${upload_repository}/blobs/uploads/"
)"
test "${post_status}" = 202
post_location="$(awk -F': ' 'tolower($1) == "location" {gsub("\\r", "", $2); print $2}' \
  "${post_headers}")"
test -n "${post_location}"

patch_headers="${temporary_directory}/patch.headers"
patch_url="${primary_url}$(location_path "${post_location}")"
patch_status="$(
  curl --silent --show-error --output /dev/null --dump-header "${patch_headers}" \
    --write-out '%{http_code}' --request PATCH \
    --header 'Content-Type: application/octet-stream' \
    --data-binary "@${temporary_directory}/part-1" \
    --cacert "${registry_ca}" "${patch_url}"
)"
test "${patch_status}" = 202
patch_location="$(awk -F': ' 'tolower($1) == "location" {gsub("\\r", "", $2); print $2}' \
  "${patch_headers}")"
patch_range="$(awk -F': ' 'tolower($1) == "range" {gsub("\\r", "", $2); print $2}' \
  "${patch_headers}")"
test -n "${patch_location}"
test "${patch_range}" = '0-1048575'

podman stop --time 15 "${primary_container}" >/dev/null
primary_stopped=1
if curl --silent --show-error --output /dev/null --connect-timeout 2 \
  --max-time 3 --cacert "${registry_ca}" "${primary_url}/v2/" \
  2>/dev/null; then
  printf 'primary endpoint remained reachable after its process stopped\n' >&2
  exit 21
fi

finalize_path="$(location_path "${patch_location}")"
case "${finalize_path}" in
  *\?*) finalize_separator='&' ;;
  *) finalize_separator='?' ;;
esac
finalize_url="${secondary_url}${finalize_path}${finalize_separator}digest=${blob_digest}"
finalize_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request PUT --header 'Content-Type: application/octet-stream' \
    --data-binary "@${temporary_directory}/part-2" \
    --cacert "${registry_ca}" "${finalize_url}"
)"
test "${finalize_status}" = 201
secondary_blob_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --head --cacert "${registry_ca}" \
    "${secondary_url}/v2/${upload_repository}/blobs/${blob_digest}"
)"
test "${secondary_blob_status}" = 200

podman start "${primary_container}" >/dev/null
primary_stopped=0
wait_for_endpoint "${primary_url}"
primary_blob_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --head --cacert "${registry_ca}" \
    "${primary_url}/v2/${upload_repository}/blobs/${blob_digest}"
)"
test "${primary_blob_status}" = 200

{
  printf 'primary replica logs\n'
  podman logs "${primary_container}"
  printf 'secondary replica logs\n'
  podman logs "${secondary_container}"
} >"${ha_log}" 2>&1
chmod 0644 "${ha_log}"
while IFS='=' read -r _name secret_value; do
  test -n "${secret_value}"
  if grep -Fq -- "${secret_value}" "${ha_log}"; then
    printf 'two-replica log contains a runtime secret\n' >&2
    exit 22
  fi
done <"${runtime_env_path}"
if grep -Eq 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${ha_log}"; then
  printf 'two-replica log contains a registry bearer token\n' >&2
  exit 23
fi

jq -n \
  --arg upload_digest "${blob_digest}" \
  --arg manifest_digest "${expected_integration_digest}" \
  --argjson first_chunk_bytes 1048576 \
  --argjson total_blob_bytes 2097152 \
  '{topology: "two Distribution processes on one VM", shared_backend: "Ceph RGW", shared_http_secret: true, first_chunk_bytes: $first_chunk_bytes, total_blob_bytes: $total_blob_bytes, primary_stopped_before_finalize: true, secondary_finalize_status: 201, primary_blob_status_after_restart: 200, secondary_blob_status: 200, upload_digest: $upload_digest, manifest_digest_both_replicas: $manifest_digest, result: "cross-replica upload resume passed", host_level_ha: false}' \
  >"${ha_evidence}"
chmod 0644 "${ha_evidence}"

printf 'Two-replica Distribution resume passed blob=%s bytes=%s host_ha=false\n' \
  "${blob_digest}" 2097152
