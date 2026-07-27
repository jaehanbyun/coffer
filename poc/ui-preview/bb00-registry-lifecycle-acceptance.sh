#!/usr/bin/env bash

set -Eeuo pipefail

registry_fqdn="bb00.tail23b778.ts.net"
registry_port="18788"
registry_host="${registry_fqdn}:${registry_port}"
registry_url="https://${registry_host}"
registry_ca="/home/jh.byun/coffer-registry-tls/registry-ca.crt"
identity_file="/home/jh.byun/coffer-registry-restart-identity.json"
evidence_file="/home/jh.byun/coffer-registry-acceptance-v2.json"
docker_config="$(
    mktemp -d /home/jh.byun/coffer-registry-restart-docker.XXXXXX
)"

cleanup() {
    local exit_status=$?
    trap - EXIT
    rm -rf -- "${docker_config}"
    exit "${exit_status}"
}
trap cleanup EXIT

test "$(id -u)" -eq 1004
test "$(hostname -s)" = "bb00"
test ! -L "${docker_config}"
chmod 0700 "${docker_config}"
for path in "${registry_ca}" "${identity_file}" "${evidence_file}"; do
    test -s "${path}"
    test ! -L "${path}"
    test "$(stat -c '%U:%G:%a' "${path}")" = \
        "jh.byun:jh.byun:600"
done
for command_name in curl docker jq ss; do
    command -v "${command_name}" >/dev/null
done

credential_id="$(
    jq -er '.project_a.application_credential_id' "${identity_file}"
)"
jq -er '.project_a.application_credential_secret' "${identity_file}" |
    docker --config "${docker_config}" login \
        --username "${credential_id}" \
        --password-stdin "${registry_host}" >/dev/null 2>&1
repository="$(jq -er '.repository' "${evidence_file}")"
image="${registry_host}/${repository}:user-docker"
docker --config "${docker_config}" pull --quiet "${image}" >/dev/null
digest="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' "${image}" |
        grep -E "^${registry_host}/${repository}@sha256:[0-9a-f]{64}$" |
        head -n 1 |
        cut -d@ -f2
)"
test "${digest}" = "$(
    jq -er '.clients.docker.digest' "${evidence_file}"
)"
docker image rm --force "${image}" >/dev/null

for path in \
    /v1/internal/maintenance/registry-token \
    /healthz \
    /readyz \
    /metrics \
    /debug; do
    test "$(
        curl --silent --show-error \
            --cacert "${registry_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${registry_url}${path}"
    )" = 403
done
ss -H -ltn |
    awk '
      $4 == "100.123.168.66:18788" { count++ }
      END { exit count != 1 }
    '
if ss -H -ltn |
    grep -Eq '(^|:)(8787|8788|8789|18888|18889)([[:space:]]|$)'; then
    echo "private registry listener exposed" >&2
    exit 1
fi

echo "restart_digest=${digest}"
echo "host_registry_boundary=verified"
