#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
guest_script="${repository_root}/poc/rgw/guest-verify-gc-dry-run.sh"
integration_evidence="${repository_root}/work/integration/evidence.json"
work_directory="${repository_root}/work/rgw"

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${remote}"
)

for command_name in jq scp ssh; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
test -f "${known_hosts}"
test -f "${integration_evidence}"
jq -e '
  .digest and .podman_digest and .repository and
  .project_a_status == 200 and
  .project_b_cross_project_status == 401
' "${integration_evidence}" >/dev/null
mkdir -p "${work_directory}"

scp "${ssh_options[@]}" "${guest_script}" \
  "${guest}:/tmp/guest-verify-gc-dry-run.sh"
scp "${ssh_options[@]}" "${integration_evidence}" \
  "${guest}:/tmp/coffer-gc-integration-evidence.json"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-verify-gc-dry-run.sh'
scp "${ssh_options[@]}" "${guest}:/tmp/coffer-gc-dry-run.log" \
  "${work_directory}/gc-dry-run.log"
scp "${ssh_options[@]}" "${guest}:/tmp/coffer-gc-dry-run-evidence.json" \
  "${work_directory}/gc-dry-run-evidence.json"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo rm -f /tmp/coffer-gc-integration-evidence.json /tmp/coffer-gc-dry-run.log /tmp/coffer-gc-dry-run-evidence.json' \
  >/dev/null

jq -e '
  .mode == "dry-run" and
  .writes == "stopped" and
  .deletion_executed == false and
  .objects_before == .objects_after and
  .referenced_content == "preserved"
' "${work_directory}/gc-dry-run-evidence.json" >/dev/null
jq '{mode, writes, deletion_executed, objects_before, objects_after, eligible_blob_lines, eligible_manifest_lines, baseline_digest, integration_digest, podman_digest, referenced_content}' \
  "${work_directory}/gc-dry-run-evidence.json"
