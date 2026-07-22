#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
remote="${COFFER_RGW_REMOTE:-bb00}"
guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
guest_script="${repository_root}/poc/rgw/guest-verify-distribution-ha.sh"
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
jq -e '.repository and .digest and .project_a_status == 200' \
  "${integration_evidence}" >/dev/null
mkdir -p "${work_directory}"

scp "${ssh_options[@]}" "${guest_script}" \
  "${guest}:/tmp/guest-verify-distribution-ha.sh"
scp "${ssh_options[@]}" "${integration_evidence}" \
  "${guest}:/tmp/coffer-ha-integration-evidence.json"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-verify-distribution-ha.sh'
scp "${ssh_options[@]}" "${guest}:/tmp/coffer-distribution-ha.log" \
  "${work_directory}/distribution-ha.log"
scp "${ssh_options[@]}" "${guest}:/tmp/coffer-distribution-ha-evidence.json" \
  "${work_directory}/distribution-ha-evidence.json"
ssh "${ssh_options[@]}" "${guest}" \
  'sudo rm -f /tmp/coffer-ha-integration-evidence.json /tmp/coffer-distribution-ha.log /tmp/coffer-distribution-ha-evidence.json' \
  >/dev/null

jq -e '
  .topology == "two Distribution processes on one VM" and
  .shared_backend == "Ceph RGW" and
  .shared_http_secret == true and
  .primary_stopped_before_finalize == true and
  .secondary_finalize_status == 201 and
  .primary_blob_status_after_restart == 200 and
  .secondary_blob_status == 200 and
  .result == "cross-replica upload resume passed" and
  .host_level_ha == false
' "${work_directory}/distribution-ha-evidence.json" >/dev/null
jq . "${work_directory}/distribution-ha-evidence.json"
