#!/usr/bin/env bash

set -euo pipefail

distribution_image="docker.io/library/registry@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
container_name="coffer-distribution-rgw"
gc_container_name="coffer-distribution-gc-dry-run"
state_directory="/etc/coffer-rgw"
config_path="${state_directory}/distribution-config.yml"
runtime_env_path="${state_directory}/distribution-runtime.env"
tls_directory="${state_directory}/distribution-tls"
registry_host="coffer-rgw-poc:5443"
registry_url="https://${registry_host}"
registry_ca="${tls_directory}/ca.crt"
integration_evidence="/tmp/coffer-gc-integration-evidence.json"
gc_log="/tmp/coffer-gc-dry-run.log"
gc_evidence="/tmp/coffer-gc-dry-run-evidence.json"
registry_stopped=0

wait_for_registry() {
  local status_code=""
  for _attempt in $(seq 1 60); do
    status_code="$(
      curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 3 --max-time 5 --cacert "${registry_ca}" \
        "${registry_url}/v2/" || true
    )"
    if test "${status_code}" = 200; then
      return 0
    fi
    sleep 2
  done
  printf 'registry did not return after GC dry-run; last status=%s\n' \
    "${status_code}" >&2
  return 1
}

restore_registry() {
  local exit_status=$?
  trap - EXIT
  if (( registry_stopped )); then
    podman start "${container_name}" >/dev/null 2>&1 || true
    wait_for_registry >/dev/null 2>&1 || true
  fi
  exit "${exit_status}"
}
trap restore_registry EXIT

test "$(id -u)" -eq 0
test -f "${integration_evidence}"
test -f "${config_path}"
test -f "${runtime_env_path}"
test -f "${registry_ca}"
test "$(stat -c '%a' "${runtime_env_path}")" = 600
test "$(podman inspect "${container_name}" --format '{{.State.Running}}')" = true
if grep -Eq '^auth:' "${config_path}"; then
  printf 'GC dry-run requires the restored unauthenticated fixture\n' >&2
  exit 20
fi
wait_for_registry

baseline_repository="p/00000000-0000-0000-0000-000000000003/real-rgw"
baseline_ref="${registry_host}/${baseline_repository}:image"
integration_repository="$(jq -er '.repository' "${integration_evidence}")"
integration_ref="${registry_host}/${integration_repository}:keystone"
podman_ref="${registry_host}/${integration_repository}:podman"

baseline_digest_before="$(
  skopeo inspect --format '{{.Digest}}' "docker://${baseline_ref}"
)"
integration_digest_before="$(
  skopeo inspect --format '{{.Digest}}' "docker://${integration_ref}"
)"
podman_digest_before="$(
  skopeo inspect --format '{{.Digest}}' "docker://${podman_ref}"
)"
test "${baseline_digest_before}" = \
  'sha256:7a3ebe5bfd1a4a19797d20b0c0bb39d44393e9a03fd852c0865b0f540d868df0'
test "${integration_digest_before}" = \
  "$(jq -er '.digest' "${integration_evidence}")"
test "${podman_digest_before}" = \
  "$(jq -er '.podman_digest' "${integration_evidence}")"

object_count_before="$(
  cephadm shell -- radosgw-admin bucket stats --bucket coffer-registry-poc | \
    jq -er '.usage["rgw.main"].num_objects'
)"

podman stop --time 30 "${container_name}" >/dev/null
registry_stopped=1
test "$(podman inspect "${container_name}" --format '{{.State.Running}}')" = false
if podman container exists "${gc_container_name}"; then
  podman rm --force "${gc_container_name}" >/dev/null
fi

podman run --rm \
  --name "${gc_container_name}" \
  --label io.coffer.poc=distribution-gc-dry-run \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
  --cap-drop=all \
  --security-opt no-new-privileges \
  --network host \
  --env-file "${runtime_env_path}" \
  --env SSL_CERT_FILE=/etc/distribution/rgw-ca.crt \
  --volume "${config_path}:/etc/distribution/config.yml:ro" \
  --volume "/etc/ceph/coffer-rgw-root-ca.crt:/etc/distribution/rgw-ca.crt:ro" \
  --volume "${tls_directory}:/etc/distribution/tls:ro" \
  "${distribution_image}" \
  garbage-collect /etc/distribution/config.yml --dry-run \
  >"${gc_log}" 2>&1
chmod 0644 "${gc_log}"

if ! grep -Eq 'marking manifest|eligible for deletion|blobs marked' "${gc_log}"; then
  printf 'GC dry-run log did not contain collector evidence\n' >&2
  exit 21
fi
while IFS='=' read -r _name secret_value; do
  test -n "${secret_value}"
  if grep -Fq -- "${secret_value}" "${gc_log}"; then
    printf 'GC dry-run log contains a runtime secret\n' >&2
    exit 22
  fi
done <"${runtime_env_path}"
if grep -Eq 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${gc_log}"; then
  printf 'GC dry-run log contains a registry bearer token\n' >&2
  exit 23
fi

object_count_after_dry_run="$(
  cephadm shell -- radosgw-admin bucket stats --bucket coffer-registry-poc | \
    jq -er '.usage["rgw.main"].num_objects'
)"
test "${object_count_after_dry_run}" -eq "${object_count_before}"

podman start "${container_name}" >/dev/null
registry_stopped=0
wait_for_registry
baseline_digest_after="$(
  skopeo inspect --format '{{.Digest}}' "docker://${baseline_ref}"
)"
integration_digest_after="$(
  skopeo inspect --format '{{.Digest}}' "docker://${integration_ref}"
)"
podman_digest_after="$(
  skopeo inspect --format '{{.Digest}}' "docker://${podman_ref}"
)"
test "${baseline_digest_after}" = "${baseline_digest_before}"
test "${integration_digest_after}" = "${integration_digest_before}"
test "${podman_digest_after}" = "${podman_digest_before}"

eligible_blob_lines="$(grep -Ec 'blob eligible for deletion' "${gc_log}" || true)"
eligible_manifest_lines="$(grep -Ec 'manifest eligible for deletion' "${gc_log}" || true)"
jq -n \
  --arg baseline_digest "${baseline_digest_after}" \
  --arg integration_digest "${integration_digest_after}" \
  --arg podman_digest "${podman_digest_after}" \
  --argjson objects_before "${object_count_before}" \
  --argjson objects_after "${object_count_after_dry_run}" \
  --argjson eligible_blob_lines "${eligible_blob_lines}" \
  --argjson eligible_manifest_lines "${eligible_manifest_lines}" \
  '{mode: "dry-run", writes: "stopped", deletion_executed: false, objects_before: $objects_before, objects_after: $objects_after, eligible_blob_lines: $eligible_blob_lines, eligible_manifest_lines: $eligible_manifest_lines, baseline_digest: $baseline_digest, integration_digest: $integration_digest, podman_digest: $podman_digest, referenced_content: "preserved"}' \
  >"${gc_evidence}"
chmod 0644 "${gc_evidence}"

printf 'Distribution GC dry-run passed objects=%s candidates=%s referenced=preserved\n' \
  "${object_count_before}" "${eligible_blob_lines}"
