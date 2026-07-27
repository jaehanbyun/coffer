#!/usr/bin/env bash

set -Eeuo pipefail

bb00="jh.byun@100.123.168.66"
guest="ubuntu@192.168.122.204"
guest_jump="jh.byun@100.123.168.66"
guest_staging="/home/ubuntu/coffer-registry-restart-identity.json"
host_staging="/home/jh.byun/coffer-registry-restart-identity.json"
host_runner="$(
    printf '%s' \
        /home/jh.byun/coffer-ui-preview-proxy/ \
        bb00-registry-lifecycle-acceptance.sh
)"
guest_runner="$(
    printf '%s' \
        /home/ubuntu/coffer/poc/ui-preview/ \
        guest-registry-lifecycle-acceptance.sh
)"
registry_ca="$(
    printf '%s' \
        "${HOME}/Library/Application Support/Coffer/" \
        preview-tls/registry-ca.crt
)"
local_identity="$(mktemp)"

cleanup() {
    local exit_status=$?
    trap - EXIT
    ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
        "sudo unlink '${guest_staging}' 2>/dev/null || true" \
        >/dev/null 2>&1 || true
    ssh -o BatchMode=yes "${bb00}" \
        "unlink '${host_staging}' 2>/dev/null || true" \
        >/dev/null 2>&1 || true
    trash "${local_identity}" 2>/dev/null || true
    exit "${exit_status}"
}
trap cleanup EXIT

test "$(uname -s)" = Darwin
test -s "${registry_ca}"
test ! -L "${registry_ca}"
for command_name in curl nc scp ssh trash; do
    command -v "${command_name}" >/dev/null
done
ssh -o BatchMode=yes "${bb00}" \
    "test -x '${host_runner}'; test ! -e '${host_staging}'"
ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "test -x '${guest_runner}'; test ! -e '${guest_staging}'"

ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "sudo jq -c '{
      project_a: {
        application_credential_id:
          .project_a.application_credential_id,
        application_credential_secret:
          .project_a.application_credential_secret
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

before_output="$(
    ssh -o BatchMode=yes "${bb00}" "${host_runner}"
)"
printf '%s\n' "${before_output}"
before_digest="$(
    printf '%s\n' "${before_output}" |
        awk -F= '$1 == "restart_digest" { print $2 }'
)"
[[ "${before_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]

ssh -o BatchMode=yes -J "${guest_jump}" "${guest}" \
    "sudo '${guest_runner}'"
for _attempt in $(seq 1 30); do
    if test "$(
        curl --silent --show-error \
            --cacert "${registry_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "https://bb00.tail23b778.ts.net:18788/v2/" || true
    )" = 401; then
        break
    fi
    sleep 1
done
test "$(
    curl --silent --show-error \
        --cacert "${registry_ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        "https://bb00.tail23b778.ts.net:18788/v2/"
)" = 401

after_output="$(
    ssh -o BatchMode=yes "${bb00}" "${host_runner}"
)"
printf '%s\n' "${after_output}"
after_digest="$(
    printf '%s\n' "${after_output}" |
        awk -F= '$1 == "restart_digest" { print $2 }'
)"
test "${after_digest}" = "${before_digest}"

for port in 8787 8788 8789 18888 18889; do
    if nc -z -w 2 100.123.168.66 "${port}" >/dev/null 2>&1; then
        echo "unexpected public listener on port ${port}" >&2
        exit 1
    fi
done

echo "client_network_backend_ports=closed"
echo "restart_persistence=passed"
