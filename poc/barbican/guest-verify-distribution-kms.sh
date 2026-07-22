#!/usr/bin/env bash

set -euo pipefail

container_name="coffer-distribution-rgw"
registry="coffer-rgw-poc:5443"
repository="p/00000000-0000-0000-0000-000000000003/kms-proof"
baseline_repository="p/00000000-0000-0000-0000-000000000003/real-rgw"
layout="/tmp/coffer-kms-oci-proof"
barbican_env="/etc/coffer-rgw/barbican.env"
s3_env="/etc/coffer-rgw/distribution.env"
config_path="/etc/coffer-rgw/distribution-config.yml"
registry_ca="/etc/coffer-rgw/distribution-tls/ca.crt"
python_helper="/tmp/guest-inspect-distribution-kms.py"
layout_helper="/tmp/guest-create-oci-layout.py"
storage_helper="/tmp/guest-kms-scenario-storage.py"
scanner="/tmp/guest-assert-secrets-absent.py"
restart_helper="/tmp/guest-restart-rgw.sh"

test "$(id -u)" -eq 0
test -f "${barbican_env}"
test -f "${s3_env}"
test -f "${python_helper}"
test -f "${layout_helper}"
test -f "${storage_helper}"
test -f "${scanner}"
test -f "${restart_helper}"
# shellcheck disable=SC1090
source "${barbican_env}"
# shellcheck disable=SC1090
source "${s3_env}"
grep -Fqx '    encrypt: true' "${config_path}"

wait_for_distribution() {
  local status_code
  for _attempt in $(seq 1 90); do
    status_code="$(curl --silent --show-error --output /dev/null \
      --write-out '%{http_code}' --connect-timeout 3 --max-time 5 \
      --cacert "${registry_ca}" "https://${registry}/v2/" || true)"
    if test "${status_code}" = 200; then
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_for_distribution
baseline_digest="$(skopeo inspect --format '{{.Digest}}' \
  "docker://${registry}/${baseline_repository}:image")"
test -n "${baseline_digest}"
python3 "${layout_helper}" "${layout}" proof >/dev/null
export COFFER_KMS_KEY_ID
export REGISTRY_STORAGE_S3_ACCESSKEY REGISTRY_STORAGE_S3_SECRETKEY
python3 "${storage_helper}" assert-empty "${repository}" "${layout}" >/dev/null
start_epoch="$(date +%s)"
skopeo copy --retry-times 1 "oci:${layout}:image" \
  "docker://${registry}/${repository}:barbican" >/dev/null
kms_digest="$(skopeo inspect --format '{{.Digest}}' \
  "docker://${registry}/${repository}:barbican")"
test -n "${kms_digest}"

python3 "${python_helper}" \
  "${start_epoch}" "${repository}" "${layout}" "${kms_digest}"

podman restart "${container_name}" >/dev/null
wait_for_distribution
test "$(skopeo inspect --format '{{.Digest}}' \
  "docker://${registry}/${repository}:barbican")" = "${kms_digest}"

bash "${restart_helper}" >/dev/null
wait_for_distribution
test "$(skopeo inspect --format '{{.Digest}}' \
  "docker://${registry}/${repository}:barbican")" = "${kms_digest}"
test "$(skopeo inspect --format '{{.Digest}}' \
  "docker://${registry}/${baseline_repository}:image")" = "${baseline_digest}"

log_file="$(mktemp /tmp/coffer-distribution-kms-log.XXXXXX)"
trap 'rm -f "${log_file}"' EXIT
podman logs "${container_name}" >"${log_file}" 2>&1
python3 "${scanner}" scan "${log_file}" >/dev/null
rm -f "${log_file}"
trap - EXIT
unset COFFER_KMS_USER_PASSWORD COFFER_KMS_KEY_ID
unset REGISTRY_STORAGE_S3_ACCESSKEY REGISTRY_STORAGE_S3_SECRETKEY

printf 'Distribution Barbican SSE-KMS passed digest=%s baseline=%s\n' \
  "${kms_digest}" "${baseline_digest}"
