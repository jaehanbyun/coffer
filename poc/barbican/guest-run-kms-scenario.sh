#!/usr/bin/env bash

set -euo pipefail

mode="${1:-}"
registry="coffer-rgw-poc:5443"
project_prefix="p/00000000-0000-0000-0000-000000000003"
barbican_env="/etc/coffer-rgw/barbican.env"
s3_env="/etc/coffer-rgw/distribution.env"
runner="/tmp/guest-run-distribution.sh"
storage_helper="/tmp/guest-kms-scenario-storage.py"
inspect_helper="/tmp/guest-inspect-distribution-kms.py"
direct_helper="/tmp/guest-verify-rgw-kms.py"
layout_helper="/tmp/guest-create-oci-layout.py"
scanner="/tmp/guest-assert-secrets-absent.py"
temporary_logs=()

test "$(id -u)" -eq 0
for path in "${barbican_env}" "${s3_env}" "${runner}" "${storage_helper}" \
  "${layout_helper}" "${scanner}"; do
  test -f "${path}"
done
# shellcheck disable=SC1090
source "${barbican_env}"
# shellcheck disable=SC1090
source "${s3_env}"
export COFFER_KMS_KEY_ID
export REGISTRY_STORAGE_S3_ACCESSKEY REGISTRY_STORAGE_S3_SECRETKEY

cleanup() {
  rm -f -- "${temporary_logs[@]}"
}
trap cleanup EXIT

run_distribution() {
  local key_id="$1"
  COFFER_DISTRIBUTION_S3_ENCRYPT=true \
    COFFER_DISTRIBUTION_S3_KEY_ID="${key_id}" bash "${runner}" >/dev/null
}

assert_failed_push() {
  local repository="$1"
  local scenario="$2"
  local layout="/tmp/coffer-kms-oci-${scenario}"
  local client_log server_log started rgw_container
  python3 "${layout_helper}" "${layout}" "${scenario}" >/dev/null
  python3 "${storage_helper}" assert-empty "${repository}" "${layout}" >/dev/null
  client_log="$(mktemp /tmp/coffer-kms-client-failure.XXXXXX)"
  server_log="$(mktemp /tmp/coffer-kms-server-failure.XXXXXX)"
  temporary_logs+=("${client_log}" "${server_log}")
  started="$(date +%s)"
  if skopeo copy --retry-times 0 "oci:${layout}:image" \
    "docker://${registry}/${repository}:failure" >"${client_log}" 2>&1; then
    printf 'KMS-negative registry push unexpectedly succeeded\n' >&2
    exit 50
  fi
  rgw_container="$(podman ps --filter 'name=ceph-.*-rgw-coffer' \
    --format '{{.Names}}' | head -1)"
  test -n "${rgw_container}"
  podman logs --since "${started}" coffer-distribution-rgw >"${server_log}" 2>&1 || true
  podman logs --since "${started}" "${rgw_container}" >>"${server_log}" 2>&1 || true
  python3 "${scanner}" scan "${client_log}" >/dev/null
  python3 "${scanner}" kms-failure "${server_log}" >/dev/null
  python3 "${storage_helper}" assert-empty "${repository}" "${layout}"
}

case "${mode}" in
  zero-byte)
    headers="$(mktemp /tmp/coffer-zero-byte-headers.XXXXXX)"
    body="$(mktemp /tmp/coffer-zero-byte-body.XXXXXX)"
    server_log="$(mktemp /tmp/coffer-zero-byte-server.XXXXXX)"
    temporary_logs+=("${headers}" "${body}" "${server_log}")
    python3 "${storage_helper}" assert-zero-empty >/dev/null
    curl --silent --show-error --dump-header "${headers}" --output /dev/null \
      --request POST --cacert /etc/coffer-rgw/distribution-tls/ca.crt \
      "https://${registry}/v2/${project_prefix}/kms-zero-byte/blobs/uploads/"
    location="$(awk 'tolower($1) == "location:" {sub(/\r$/, "", $2); print $2}' \
      "${headers}")"
    test -n "${location}"
    started="$(date +%s)"
    status="$(curl --silent --show-error --output "${body}" \
      --write-out '%{http_code}' --request PUT --upload-file /dev/null \
      --cacert /etc/coffer-rgw/distribution-tls/ca.crt \
      "${location}&digest=sha256%3Ae3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")"
    test "${status}" = 500
    rgw_container="$(podman ps --filter 'name=ceph-.*-rgw-coffer' \
      --format '{{.Names}}' | head -1)"
    podman logs --since "${started}" coffer-distribution-rgw >"${server_log}" 2>&1 || true
    podman logs --since "${started}" "${rgw_container}" >>"${server_log}" 2>&1 || true
    python3 "${scanner}" scan "${headers}" "${body}" "${server_log}" >/dev/null
    grep -Eq 'NotImplemented|status code:[[:space:]]*501' "${server_log}"
    python3 "${storage_helper}" cleanup-zero >/dev/null
    python3 "${storage_helper}" assert-zero-empty >/dev/null
    printf 'Tentacle zero-byte encrypted CopyObject limitation failed closed\n'
    ;;
  wrong-key)
    wrong_key="$(python3 -c 'import uuid; print(uuid.uuid4())')"
    run_distribution "${wrong_key}"
    assert_failed_push "${project_prefix}/kms-wrong-key" wrong-key
    run_distribution "${COFFER_KMS_KEY_ID}"
    printf 'Wrong Barbican key failed closed and the correct key was restored\n'
    ;;
  outage)
    assert_failed_push "${project_prefix}/kms-outage" outage
    printf 'Unavailable fresh-process identity/KMS path failed closed\n'
    ;;
  recovery)
    test -f "${inspect_helper}"
    test -f "${direct_helper}"
    run_distribution "${COFFER_KMS_KEY_ID}"
    repository="${project_prefix}/kms-recovery"
    layout="/tmp/coffer-kms-oci-recovery"
    python3 "${layout_helper}" "${layout}" recovery >/dev/null
    python3 "${storage_helper}" assert-empty "${repository}" "${layout}" >/dev/null
    started="$(date +%s)"
    skopeo copy --retry-times 1 "oci:${layout}:image" \
      "docker://${registry}/${repository}:recovered" >/dev/null
    digest="$(skopeo inspect --format '{{.Digest}}' \
      "docker://${registry}/${repository}:recovered")"
    test -n "${digest}"
    python3 "${inspect_helper}" \
      "${started}" "${repository}" "${layout}" "${digest}"
    python3 "${direct_helper}"
    test -n "$(skopeo inspect --format '{{.Digest}}' \
      "docker://${registry}/${project_prefix}/kms-proof:barbican")"
    printf 'Barbican recovery restored encrypted writes and reads digest=%s\n' \
      "${digest}"
    ;;
  cleanup)
    run_distribution "${COFFER_KMS_KEY_ID}"
    python3 "${storage_helper}" cleanup
    for layout in \
      /tmp/coffer-kms-oci-proof \
      /tmp/coffer-kms-oci-wrong-key \
      /tmp/coffer-kms-oci-outage \
      /tmp/coffer-kms-oci-recovery; do
      if test -d "${layout}"; then
        find "${layout}" -depth -delete
      fi
    done
    ;;
  *)
    printf 'usage: %s {zero-byte|wrong-key|outage|recovery|cleanup}\n' "$0" >&2
    exit 2
    ;;
esac

unset COFFER_KMS_USER_PASSWORD COFFER_KMS_KEY_ID
unset REGISTRY_STORAGE_S3_ACCESSKEY REGISTRY_STORAGE_S3_SECRETKEY
cleanup
trap - EXIT
