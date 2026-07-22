#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
work_dir="${repository_root}/work/barbican"

limactl copy "${script_dir}/guest-provision.sh" \
  "${instance}:/tmp/coffer-barbican-guest-provision.sh"
limactl copy "${script_dir}/provision_runtime.py" \
  "${instance}:/tmp/coffer-barbican-provision-runtime.py"
limactl shell "${instance}" chmod 700 \
  /tmp/coffer-barbican-guest-provision.sh \
  /tmp/coffer-barbican-provision-runtime.py
limactl shell "${instance}" \
  /tmp/coffer-barbican-guest-provision.sh

mkdir -p "${work_dir}"
chmod 700 "${work_dir}"
limactl copy "${instance}:/tmp/coffer-barbican-provision-evidence.json" \
  "${work_dir}/provision-evidence.json"
chmod 600 "${work_dir}/provision-evidence.json"
limactl shell "${instance}" rm -f \
  /tmp/coffer-barbican-provision-evidence.json \
  /tmp/coffer-barbican-guest-provision.sh \
  /tmp/coffer-barbican-provision-runtime.py

jq -e '.key_bytes == 32 and .algorithm == "aes" and
  .bit_length == 256 and .role == "creator" and
  .effective_role_assignments == 1 and
  .caller_binding_retained == true and
  .credential_in_host_evidence == false and
  .key_id_format_valid == true and .key_id_retained == false and
  .secret_payload_retained == false and (has("key_id") | not)' \
  "${work_dir}/provision-evidence.json" >/dev/null

printf 'Disposable Barbican provisioning passed\n'
