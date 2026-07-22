#!/usr/bin/env bash

set -euo pipefail

config_section="client.rgw.coffer"
barbican_env="/etc/coffer-rgw/barbican.env"
runner="/tmp/guest-run-distribution.sh"
config_helper="/tmp/guest-ceph-kms-config.py"
scanner="/tmp/guest-assert-secrets-absent.py"

test "$(id -u)" -eq 0
test -f "${barbican_env}"
test -f "${runner}"
test -f "${config_helper}"
test -f "${scanner}"
cephadm shell \
  --mount "${config_helper}:${config_helper}" \
    "${barbican_env}:/tmp/coffer-barbican.env" \
  -- python3 "${config_helper}" remove >/dev/null
cephadm shell -- ceph config dump --format json | jq -e \
  --arg section "${config_section}" \
  '[.[] | select(.section == $section) | .name |
    select(startswith("rgw_crypt") or startswith("rgw_barbican") or
      startswith("rgw_keystone"))] | length == 0' >/dev/null

bash /tmp/guest-restart-rgw.sh
bash "${runner}" >/dev/null
if grep -Eq '^[[:space:]]+(encrypt|keyid):' \
  /etc/coffer-rgw/distribution-config.yml; then
  printf 'Distribution KMS setting remained after rollback\n' >&2
  exit 60
fi
test -n "$(skopeo inspect --format '{{.Digest}}' \
  docker://coffer-rgw-poc:5443/p/00000000-0000-0000-0000-000000000003/real-rgw:image)"

log_file="$(mktemp /tmp/coffer-rgw-kms-rollback-log.XXXXXX)"
trap 'rm -f "${log_file}"' EXIT
container="$(podman ps --filter 'name=ceph-.*-rgw-coffer' \
  --format '{{.Names}}' | head -1)"
podman logs "${container}" >"${log_file}" 2>&1
podman logs coffer-distribution-rgw >>"${log_file}" 2>&1
python3 "${scanner}" scan "${log_file}" >/dev/null
rm -f "${log_file}"
trap - EXIT
printf 'RGW and Distribution returned to the non-KMS baseline\n'
