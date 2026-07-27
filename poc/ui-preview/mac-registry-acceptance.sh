#!/usr/bin/env bash

set -Eeuo pipefail

bb00="jh.byun@100.123.168.66"
guest="ubuntu@192.168.122.204"
guest_jump="jh.byun@100.123.168.66"
guest_staging="/home/ubuntu/coffer-registry-acceptance-identities.json"
host_staging="/home/jh.byun/coffer-registry-acceptance-identities.json"
host_evidence="/home/jh.byun/coffer-registry-acceptance-v2.json"
host_runner="/home/jh.byun/coffer-ui-preview-proxy/bb00-registry-acceptance.sh"
registry_ca="${HOME}/Library/Application Support/Coffer/preview-tls/registry-ca.crt"
local_identity="$(mktemp)"
primary_stopped=0

cleanup() {
    local exit_status=$?
    trap - EXIT
    if ((primary_stopped)); then
        ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
            "sudo docker start coffer_registry coffer_edge >/dev/null" || true
    fi
    ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
        "sudo unlink '${guest_staging}' 2>/dev/null || true" || true
    ssh -o BatchMode=yes "${bb00}" \
        "unlink '${host_staging}' 2>/dev/null || true" || true
    trash "${local_identity}" 2>/dev/null || true
    exit "${exit_status}"
}
trap cleanup EXIT

test "$(uname -s)" = Darwin
test -s "${registry_ca}"
test ! -L "${registry_ca}"
for command_name in curl scp ssh trash; do
    command -v "${command_name}" >/dev/null
done
ssh -o BatchMode=yes "${bb00}" \
    "test ! -e '${host_evidence}'; test -x '${host_runner}'"

ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "sudo jq -c '{
      project_a: {
        project_id: .project_a.project_id,
        application_credential_id: .project_a.application_credential_id,
        application_credential_secret: .project_a.application_credential_secret
      },
      project_b: {
        project_id: .project_b.project_id,
        application_credential_id: .project_b.application_credential_id,
        application_credential_secret: .project_b.application_credential_secret
      }
    }' /root/coffer-ui-preview-identities.json |
    sudo tee '${guest_staging}' >/dev/null;
    sudo chown ubuntu:ubuntu '${guest_staging}';
    sudo chmod 0600 '${guest_staging}'"
scp -q -o ProxyJump="${guest_jump}" \
    "${guest}:${guest_staging}" "${local_identity}"
chmod 0600 "${local_identity}"
scp -q "${local_identity}" "${bb00}:${host_staging}"
ssh -o BatchMode=yes "${bb00}" \
    "chmod 0600 '${host_staging}';
    test \"\$(stat -c '%U:%G:%a' '${host_staging}')\" = \
      'jh.byun:jh.byun:600'"
echo "credential_staging=verified"

test "$(
    curl --silent --show-error \
        --cacert "${registry_ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        "https://bb00.tail23b778.ts.net:18788/v2/"
)" = 401
echo "normal_public_path=verified"

ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "sudo docker stop coffer_edge coffer_registry >/dev/null"
primary_stopped=1
ssh -o BatchMode=yes "${bb00}" \
    "COFFER_PRIMARY_STOPPED=1 '${host_runner}'"
ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "sudo docker start coffer_registry coffer_edge >/dev/null"
primary_stopped=0

for _attempt in $(seq 1 60); do
    if ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
        "test \"\$(sudo docker inspect --format '{{.State.Health.Status}}' coffer_edge)\" = healthy &&
         test \"\$(sudo docker inspect --format '{{.State.Health.Status}}' coffer_registry)\" = healthy" \
        >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "test \"\$(sudo docker inspect --format '{{.State.Health.Status}}' coffer_edge)\" = healthy;
     test \"\$(sudo docker inspect --format '{{.State.Health.Status}}' coffer_registry)\" = healthy"
ssh -o BatchMode=yes "${bb00}" \
    "test -s '${host_evidence}';
     test \"\$(stat -c '%U:%G:%a' '${host_evidence}')\" = \
       'jh.byun:jh.byun:600';
     jq -er '.tls_verified and .project_b_pull_denied and
       .project_b_push_denied and
       .primary_pair_stopped' '${host_evidence}' >/dev/null"
echo "mac_registry_acceptance=passed"
