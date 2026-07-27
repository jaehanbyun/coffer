#!/usr/bin/env bash

set -Eeuo pipefail

registry_fqdn="bb00.tail23b778.ts.net"
registry_port="18788"
registry_host="${registry_fqdn}:${registry_port}"
registry_url="https://${registry_host}"
registry_ca="/home/jh.byun/coffer-registry-tls/registry-ca.crt"
identity_staging="/home/jh.byun/coffer-registry-acceptance-identities.json"
evidence_file="/home/jh.byun/coffer-registry-acceptance.json"
repository_name="preview-proof"
busybox_ref="docker.io/library/busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
podman_image="quay.io/podman/stable@sha256:663e0dbf407987b7db3f20d3588c283a8228db17b282d2029a482d4d47e36964"
oras_image="ghcr.io/oras-project/oras@sha256:a4c54befd87d0366e0ba3ac3a9536a5288c8a3735acd3b635cdace59a2c559c8"
temporary_root="$(mktemp -d /home/jh.byun/coffer-registry-acceptance.XXXXXX)"
identity_file="${temporary_root}/identities.json"
docker_a="${temporary_root}/docker-a"
docker_b="${temporary_root}/docker-b"
oras_root="${temporary_root}/oras"
busybox_preexisting=0
busybox_checked=0
docker_image=""
failover_image=""

cleanup() {
    local exit_status=$?
    trap - EXIT
    for image in "${docker_image}" "${failover_image}"; do
        if test -n "${image}"; then
            docker image rm --force "${image}" >/dev/null 2>&1 || true
        fi
    done
    if ((busybox_checked && ! busybox_preexisting)); then
        docker image rm --force "${busybox_ref}" >/dev/null 2>&1 || true
    fi
    rm -rf -- "${temporary_root}"
    rm -f -- "${identity_staging}"
    exit "${exit_status}"
}
trap cleanup EXIT

test "$(id -u)" -eq 1004
test "$(hostname -s)" = "bb00"
test ! -L "${temporary_root}"
chmod 0700 "${temporary_root}"
test -s "${registry_ca}"
test "$(stat -c '%U:%G:%a' "${registry_ca}")" = \
    "jh.byun:jh.byun:600"
test ! -e "${evidence_file}"
for command_name in curl docker jq openssl; do
    command -v "${command_name}" >/dev/null
done
test "${COFFER_PRIMARY_STOPPED:-}" = 1
test -s "${identity_staging}"
test ! -L "${identity_staging}"
test "$(stat -c '%U:%G:%a' "${identity_staging}")" = \
    "jh.byun:jh.byun:600"
docker_version="$(docker version --format '{{.Client.Version}}')"
podman_version="$(
    docker run --rm --privileged --network host \
        "${podman_image}" podman --version |
        awk '{print $3}'
)"
oras_version="$(
    docker run --rm --network host "${oras_image}" version |
        awk '$1 == "Version:" {print $2}'
)"
test -n "${docker_version}"
test "${podman_version}" = "5.8.2"
test "${oras_version}" = "1.3.3"
echo "client_versions=verified"

install -m 0600 "${identity_staging}" "${identity_file}"
chmod 0600 "${identity_file}"
test "$(stat -c '%U:%G:%a' "${identity_file}")" = \
    "jh.byun:jh.byun:600"

project_a_id="$(jq -er '.project_a.project_id' "${identity_file}")"
project_b_id="$(jq -er '.project_b.project_id' "${identity_file}")"
credential_a_id="$(
    jq -er '.project_a.application_credential_id' "${identity_file}"
)"
credential_b_id="$(
    jq -er '.project_b.application_credential_id' "${identity_file}"
)"
test "${project_a_id}" != "${project_b_id}"
repository="p/${project_a_id}/${repository_name}"
echo "project_credentials=loaded"

challenge_headers="${temporary_root}/challenge.headers"
challenge_status=""
for _attempt in $(seq 1 30); do
    challenge_status="$(
        curl --silent --show-error \
            --cacert "${registry_ca}" \
            --dump-header "${challenge_headers}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${registry_url}/v2/" || true
    )"
    if test "${challenge_status}" = 401 &&
        grep -Fqi \
            "realm=\"${registry_url}/auth/token\"" \
            "${challenge_headers}"; then
        break
    fi
    sleep 1
done
test "${challenge_status}" = 401
grep -Fqi \
    "realm=\"${registry_url}/auth/token\"" \
    "${challenge_headers}"
openssl s_client \
    -connect "${registry_host}" \
    -servername "${registry_fqdn}" \
    -CAfile "${registry_ca}" \
    -verify_hostname "${registry_fqdn}" \
    -verify_return_error </dev/null >/dev/null 2>&1
echo "endpoint_tls_and_challenge=verified"

install -d -m 0700 "${docker_a}" "${docker_b}"
jq -er '.project_a.application_credential_secret' "${identity_file}" |
    docker --config "${docker_a}" login \
        --username "${credential_a_id}" \
        --password-stdin "${registry_host}" >/dev/null 2>&1
jq -er '.project_b.application_credential_secret' "${identity_file}" |
    docker --config "${docker_b}" login \
        --username "${credential_b_id}" \
        --password-stdin "${registry_host}" >/dev/null 2>&1
find "${docker_a}" "${docker_b}" -type f -exec chmod 0600 {} +
echo "docker_logins=verified"

if docker image inspect "${busybox_ref}" >/dev/null 2>&1; then
    busybox_preexisting=1
fi
busybox_checked=1
docker pull --quiet "${busybox_ref}" >/dev/null
docker_image="${registry_host}/${repository}:user-docker"
docker tag "${busybox_ref}" "${docker_image}"
docker --config "${docker_a}" push --quiet "${docker_image}" >/dev/null
docker image rm --force "${docker_image}" >/dev/null
docker --config "${docker_a}" pull --quiet "${docker_image}" >/dev/null
docker_digest="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' "${docker_image}" |
        grep -E "^${registry_host}/${repository}@sha256:[0-9a-f]{64}$" |
        head -n 1 |
        cut -d@ -f2
)"
test -n "${docker_digest}"

denial_log="${temporary_root}/project-b-denial.log"
if docker --config "${docker_b}" pull "${docker_image}" \
    >"${denial_log}" 2>&1; then
    echo "project B unexpectedly pulled project A content" >&2
    exit 1
fi
test ! -s "${denial_log}" ||
    ! grep -Fq "$(
        jq -er '.project_b.application_credential_secret' "${identity_file}"
    )" "${denial_log}"
echo "docker_push_pull_and_isolation=verified"

podman_ref="${registry_host}/${repository}:user-podman"
jq -er '.project_a.application_credential_secret' "${identity_file}" |
    docker run --rm --interactive --privileged --network host \
        --volume "${registry_ca}:/work/ca.crt:ro" \
        --entrypoint /bin/bash \
        "${podman_image}" \
        -ceu '
          read -r secret
          printf "%s\n" "${secret}" |
              podman login \
                  --authfile /tmp/auth.json \
                  --cert-dir /work \
                  --tls-verify=true \
                  --username "$1" \
                  --password-stdin "$2" >/dev/null
          unset secret
          podman pull --quiet "$3" >/dev/null
          podman tag "$3" "$4"
          podman push \
              --authfile /tmp/auth.json \
              --cert-dir /work \
              --tls-verify=true "$4" >/dev/null
          podman image rm --force "$4" >/dev/null
          podman pull \
              --authfile /tmp/auth.json \
              --cert-dir /work \
              --tls-verify=true --quiet "$4" >/dev/null
          podman image inspect --format "{{.Digest}}" "$4"
        ' podman-acceptance \
        "${credential_a_id}" "${registry_host}" \
        "${busybox_ref}" "${podman_ref}" \
        >"${temporary_root}/podman.digest"
podman_digest="$(tail -n 1 "${temporary_root}/podman.digest")"
[[ "${podman_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
echo "podman_push_pull=verified"

install -d -m 0700 "${oras_root}"
install -m 0600 "${registry_ca}" "${oras_root}/ca.crt"
printf '%s\n' "coffer user endpoint acceptance" \
    >"${oras_root}/artifact.txt"
chmod 0600 "${oras_root}/artifact.txt"
jq -er '.project_a.application_credential_secret' "${identity_file}" |
    docker run --rm --interactive --network host \
        --user "$(id -u):$(id -g)" \
        --volume "${oras_root}:/work" \
        "${oras_image}" login \
        --ca-file /work/ca.crt \
        --registry-config /work/auth.json \
        --username "${credential_a_id}" \
        --password-stdin "${registry_host}" >/dev/null
oras_ref="${registry_host}/${repository}:user-oras"
docker run --rm --network host \
    --user "$(id -u):$(id -g)" \
    --volume "${oras_root}:/work" \
    --workdir /work \
    "${oras_image}" push \
    --ca-file /work/ca.crt \
    --registry-config /work/auth.json \
    "${oras_ref}" \
    "artifact.txt:text/plain" >/dev/null
oras_digest="$(
    docker run --rm --network host \
        --user "$(id -u):$(id -g)" \
        --volume "${oras_root}:/work" \
        "${oras_image}" resolve \
        --ca-file /work/ca.crt \
        --registry-config /work/auth.json \
        "${oras_ref}"
)"
[[ "${oras_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
install -d -m 0700 "${oras_root}/pulled"
docker run --rm --network host \
    --user "$(id -u):$(id -g)" \
    --volume "${oras_root}:/work" \
    --workdir /work \
    "${oras_image}" pull \
    --ca-file /work/ca.crt \
    --registry-config /work/auth.json \
    --output /work/pulled \
    "${oras_ref}" >/dev/null
cmp --silent \
    "${oras_root}/artifact.txt" \
    "${oras_root}/pulled/artifact.txt"
echo "oras_push_pull=verified"

for _attempt in $(seq 1 30); do
    if test "$(
        curl --silent --show-error \
            --cacert "${registry_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${registry_url}/v2/" || true
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
        "${registry_url}/v2/"
)" = 401
failover_image="${registry_host}/${repository}:user-failover"
docker tag "${busybox_ref}" "${failover_image}"
docker --config "${docker_a}" push --quiet "${failover_image}" >/dev/null
docker image rm --force "${failover_image}" >/dev/null
docker --config "${docker_a}" pull --quiet "${failover_image}" >/dev/null
failover_digest="$(
    docker image inspect \
        --format '{{join .RepoDigests "\n"}}' "${failover_image}" |
        grep -E "^${registry_host}/${repository}@sha256:[0-9a-f]{64}$" |
        head -n 1 |
        cut -d@ -f2
)"
test "${failover_digest}" = "${docker_digest}"
echo "primary_pair_outage=verified"
temporary_evidence="${temporary_root}/evidence.json"
jq -n \
    --arg endpoint "${registry_url}" \
    --arg project_a_id "${project_a_id}" \
    --arg project_b_id "${project_b_id}" \
    --arg repository "${repository}" \
    --arg docker_digest "${docker_digest}" \
    --arg podman_digest "${podman_digest}" \
    --arg oras_digest "${oras_digest}" \
    --arg failover_digest "${failover_digest}" \
    --arg docker_version "${docker_version}" \
    --arg podman_version "${podman_version}" \
    --arg oras_version "${oras_version}" \
    --arg podman_image "${podman_image}" \
    --arg oras_image "${oras_image}" \
    '{
      schema: "coffer.user-endpoint-acceptance/v1",
      endpoint: $endpoint,
      tls_verified: true,
      project_a_id: $project_a_id,
      project_b_id: $project_b_id,
      repository: $repository,
      project_b_denied: true,
      clients: {
        docker: {version: $docker_version, digest: $docker_digest},
        podman: {
          version: $podman_version,
          image: $podman_image,
          digest: $podman_digest
        },
        oras: {
          version: $oras_version,
          image: $oras_image,
          digest: $oras_digest
        }
      },
      primary_pair_stopped: true,
      failover_digest: $failover_digest,
      secret_transport: "stdin-only"
    }' >"${temporary_evidence}"
chmod 0600 "${temporary_evidence}"
for fixture in project_a project_b; do
    secret="$(
        jq -er ".${fixture}.application_credential_secret" "${identity_file}"
    )"
    test -n "${secret}"
    if grep -Fq "${secret}" "${temporary_evidence}"; then
        echo "secret found in acceptance evidence" >&2
        exit 1
    fi
    unset secret
done
mv "${temporary_evidence}" "${evidence_file}"
chmod 0600 "${evidence_file}"
jq -er \
    '.tls_verified and .project_b_denied and .primary_pair_stopped' \
    "${evidence_file}" >/dev/null
echo "user_endpoint_acceptance=passed"
