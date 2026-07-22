#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
registry_host="127.0.0.1:5000"
registry_url="http://${registry_host}"
repository="coffer/m0"
image_ref="${registry_host}/${repository}:image"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
oras_image="ghcr.io/oras-project/oras:v1.3.3@sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8"
artifact_type="application/vnd.coffer.m0.evidence.v1+json"
temporary_dir="$(mktemp -d /tmp/coffer-m0.XXXXXX)"

cleanup() {
  rm -f "${temporary_dir}/evidence.json" "${temporary_dir}/referrers.json"
  rmdir "${temporary_dir}" 2>/dev/null || true
}
trap cleanup EXIT

for command_name in curl docker jq; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

run_oras() {
  docker run --rm \
    --add-host host.docker.internal:host-gateway \
    --volume "${temporary_dir}:/workspace:ro" \
    --workdir /workspace \
    "${oras_image}" "$@"
}

wait_for_registry() {
  local _
  for _ in {1..30}; do
    if curl --fail --silent "${registry_url}/v2/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf 'registry did not become ready\n' >&2
  return 1
}

printf 'Checking unmodified Distribution endpoint...\n'
wait_for_registry

printf 'Pushing a pinned OCI-compatible image with Docker...\n'
docker pull "${busybox_ref}" >/dev/null
docker tag "${busybox_ref}" "${image_ref}"
docker push "${image_ref}" >/dev/null

subject_digest="$({
  curl --fail --silent --show-error --head \
    --header 'Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
    "${registry_url}/v2/${repository}/manifests/image"
} | awk -F': ' 'tolower($1) == "docker-content-digest" {gsub("\\r", "", $2); print $2}')"
test -n "${subject_digest}"
printf 'Image digest: %s\n' "${subject_digest}"

printf 'Pulling by digest before and after a registry restart...\n'
docker pull "${registry_host}/${repository}@${subject_digest}" >/dev/null
docker compose --project-directory "${script_dir}" restart registry >/dev/null
wait_for_registry
docker pull "${registry_host}/${repository}@${subject_digest}" >/dev/null

printf '{"kind":"coffer-m0-evidence","subject":"%s"}\n' "${subject_digest}" >"${temporary_dir}/evidence.json"

printf 'Attaching an OCI artifact with ORAS v1.3.3...\n'
run_oras attach \
  --plain-http \
  --artifact-type "${artifact_type}" \
  "host.docker.internal:5000/${repository}@${subject_digest}" \
  'evidence.json:application/json'

printf 'Discovering the artifact through the ORAS client...\n'
discovery_json="$(run_oras discover --plain-http --format json \
  "host.docker.internal:5000/${repository}@${subject_digest}")"
printf '%s\n' "${discovery_json}" | jq .
printf '%s\n' "${discovery_json}" | jq -e --arg artifact_type "${artifact_type}" \
  '.. | strings | select(. == $artifact_type)' >/dev/null

printf 'Probing the native OCI 1.1 referrers endpoint...\n'
referrers_status="$(curl --silent --show-error \
  --output "${temporary_dir}/referrers.json" \
  --write-out '%{http_code}' \
  --header 'Accept: application/vnd.oci.image.index.v1+json' \
  "${registry_url}/v2/${repository}/referrers/${subject_digest}")"
case "${referrers_status}" in
  200)
    printf 'Native referrers API: supported\n'
    jq . "${temporary_dir}/referrers.json"
    ;;
  404)
    printf 'Native referrers API: unavailable; ORAS used its fallback tag scheme\n'
    ;;
  *)
    printf 'Unexpected referrers API status: %s\n' "${referrers_status}" >&2
    cat "${temporary_dir}/referrers.json" >&2
    exit 1
    ;;
esac

printf 'Confirming content exists in the S3-compatible bucket...\n'
object_count="$(
  docker compose --project-directory "${script_dir}" run --rm --no-deps \
    --entrypoint /bin/sh minio-init -ec '
      mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
      mc find local/coffer-registry | wc -l
    '
)"
test "${object_count}" -gt 0
printf 'S3 object count: %s\n' "${object_count}"

printf 'M0 functional verification passed.\n'
