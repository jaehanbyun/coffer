#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {preflight|accept|status}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    preflight|accept|status)
        ;;
    *)
        echo "refusing an unknown Coffer tenant acceptance action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
fixture_root="${state_root}/tenant-fixture"
identity_state="${fixture_root}/identities.json"
fixture_marker="${fixture_root}/prepared.complete"
fixture_marker_value="coffer-stage5-tenant-fixture-v1"
acceptance_root="${state_root}/tenant-acceptance"
repository_state="${acceptance_root}/repository.json"
quota_marker="${acceptance_root}/quota-denial.complete"
accepted_marker="${acceptance_root}/accepted.complete"
evidence_file="${acceptance_root}/evidence.json"
marker_value="coffer-stage5-tenant-acceptance-v1"
repository_name="stage5-proof"
registry_name="registry.coffer.stage5"
registry_url="https://${registry_name}"
internal_api="https://192.168.252.10:8787"
internal_keystone="https://192.168.252.10:5000/v3"
kolla_ca="/etc/kolla/certificates-stage5/ca/root.crt"
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"
client_root="/run/coffer-stage5-tenant-client"
source_image="localhost/coffer:stage5"
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)
temporary_root=""

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(stat -c '%U:%G:%a' "${fixture_root}")" = root:root:700
test "$(stat -c '%U:%G:%a' "${identity_state}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${fixture_marker}")" = root:root:600
test "$(cat "${fixture_marker}")" = "${fixture_marker_value}"
test "$(stat -c '%U:%G:%a' "${kolla_ca}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${deployment_key}")" = ubuntu:ubuntu:600
test "$(stat -c '%U:%G:%a' "${known_hosts}")" = ubuntu:ubuntu:644
test "$(docker inspect -f '{{.State.Running}}' coffer_api)" = true
test "$(docker inspect -f '{{.State.Running}}' coffer_edge)" = true

cleanup_local_temporary() {
    if test -z "${temporary_root}"; then
        return
    fi
    case "${temporary_root}" in
        "${state_root}"/.tenant-acceptance.*)
            ;;
        *)
            echo "refusing an unexpected tenant acceptance temporary root" >&2
            return 1
            ;;
    esac
    find "${temporary_root}" -xdev -type f -delete
    find "${temporary_root}" -xdev -depth -type d -empty -delete
    temporary_root=""
}
trap cleanup_local_temporary EXIT

create_temporary_root() {
    test -z "${temporary_root}"
    temporary_root="$(
        mktemp -d "${state_root}/.tenant-acceptance.XXXXXX"
    )"
    chmod 0700 "${temporary_root}"
}

discover_external_owner() {
    local index
    local owner_count=0

    external_owner_address=""
    external_owner_hostname=""
    for index in "${!addresses[@]}"; do
        if sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${addresses[${index}]}" \
            "ip -4 -o address show dev ens5 |
                grep -Fq '192.168.254.10/32'"; then
            external_owner_address="${addresses[${index}]}"
            external_owner_hostname="${hostnames[${index}]}"
            owner_count="$((owner_count + 1))"
        fi
    done
    test "${owner_count}" -eq 1
}

verify_owner_client_clean() {
    local index

    discover_external_owner
    for index in "${!addresses[@]}"; do
        sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${addresses[${index}]}" \
            sudo env LC_ALL=C LANG=C bash -s -- \
            "${hostnames[${index}]}" "${client_root}" \
            "${registry_name}" <<'REMOTE'
set -Eeuo pipefail

expected_hostname="$1"
client_root="$2"
registry_name="$3"

test "$(hostname)" = "${expected_hostname}"
test ! -e "${client_root}"
test ! -e "/etc/docker/certs.d/${registry_name}"
test -z "$(
    grep -F -- "${registry_name}" /etc/hosts 2>/dev/null || true
)"
test -z "$(
    docker image ls \
        --filter "reference=${registry_name}/*" \
        --format '{{.Repository}}:{{.Tag}}'
)"
REMOTE
    done
    printf 'coffer_tenant_owner state=clean external_owner=%s client_residue=none\n' \
        "${external_owner_hostname}"
}

control_snapshot() {
    local project_a
    local project_b

    project_a="$(jq -er '.project_a.project_id' "${identity_state}")"
    project_b="$(jq -er '.project_b.project_id' "${identity_state}")"
    docker exec -i coffer_api /var/lib/kolla/venv/bin/python3 - \
        "${repository_name}" "${project_a}" "${project_b}" <<'PY'
import sys

from coffer.config import parse_config
from coffer.db import RepositoryStore
from coffer.quota import QuotaNotConfigured, QuotaStore


repository_name = sys.argv[1]
project_a = sys.argv[2]
project_b = sys.argv[3]
configuration = parse_config(
    args=["--config-file", "/etc/coffer/coffer.conf"]
)
repository_store = RepositoryStore(configuration.database.connection)
quota_store = QuotaStore(configuration.database.connection)
repository_count = sum(
    repository.name == repository_name
    for project_id in (project_a, project_b)
    for repository in repository_store.list(project_id)
)
quota_count = 0
for project_id in (project_a, project_b):
    try:
        quota_store.usage(project_id)
    except QuotaNotConfigured:
        pass
    else:
        quota_count += 1
print(f"repositories={repository_count} quotas={quota_count}")
PY
}

require_clean_boundary() {
    local snapshot

    test ! -e "${acceptance_root}"
    snapshot="$(control_snapshot)"
    test "${snapshot}" = "repositories=0 quotas=0"
    verify_owner_client_clean
    printf 'coffer_tenant_acceptance state=clean %s mutation=none\n' \
        "${snapshot}"
}

issue_keystone_token() {
    local fixture_name="$1"
    local token_path="$2"
    local payload="${temporary_root}/keystone-${fixture_name}.json"
    local headers="${temporary_root}/keystone-${fixture_name}.headers"
    local response="${temporary_root}/keystone-${fixture_name}.response"
    local credential_id
    local credential_secret
    local status

    credential_id="$(
        jq -er ".${fixture_name}.application_credential_id" \
            "${identity_state}"
    )"
    credential_secret="$(
        jq -er ".${fixture_name}.application_credential_secret" \
            "${identity_state}"
    )"
    jq -n \
        --arg identifier "${credential_id}" \
        --arg secret "${credential_secret}" \
        '{
          auth: {
            identity: {
              methods: ["application_credential"],
              application_credential: {
                id: $identifier,
                secret: $secret
              }
            }
          }
        }' >"${payload}"
    unset credential_secret
    chmod 0600 "${payload}"
    status="$(
        curl --disable --silent --show-error \
            --output "${response}" \
            --dump-header "${headers}" \
            --write-out '%{http_code}' \
            --request POST \
            --cacert "${kolla_ca}" \
            --header 'Content-Type: application/json' \
            --data-binary "@${payload}" \
            "${internal_keystone}/auth/tokens"
    )"
    test "${status}" = 201
    awk -F': ' '
        tolower($1) == "x-subject-token" {
            gsub("\r", "", $2)
            print $2
        }
    ' "${headers}" >"${token_path}"
    test -s "${token_path}"
    test "$(wc -l <"${token_path}")" -eq 1
    chmod 0600 "${token_path}"
}

make_keystone_curl_config() {
    local token_path="$1"
    local config_path="$2"
    local token

    token="$(tr -d '\n' <"${token_path}")"
    test -n "${token}"
    printf 'header = "X-Auth-Token: %s"\n' "${token}" >"${config_path}"
    chmod 0600 "${config_path}"
    unset token
}

ensure_repository() {
    local project_a_id
    local project_b_status
    local match_count
    local status
    local list="${temporary_root}/repositories.json"
    local response="${temporary_root}/repository.response"

    project_a_id="$(jq -er '.project_a.project_id' "${identity_state}")"
    curl --disable --fail --silent --show-error \
        --config "${temporary_root}/keystone-a.curl" \
        --cacert "${kolla_ca}" \
        --output "${list}" \
        "${internal_api}/v1/repositories"
    match_count="$(
        jq --arg name "${repository_name}" \
            '[.repositories[] | select(.name == $name)] | length' \
            "${list}"
    )"
    case "${match_count}" in
        0)
            status="$(
                curl --disable --silent --show-error \
                    --config "${temporary_root}/keystone-a.curl" \
                    --cacert "${kolla_ca}" \
                    --output "${response}" \
                    --write-out '%{http_code}' \
                    --header 'Content-Type: application/json' \
                    --data "{\"name\":\"${repository_name}\"}" \
                    "${internal_api}/v1/repositories"
            )"
            test "${status}" = 201
            ;;
        1)
            jq --arg name "${repository_name}" \
                '{repository: [
                    .repositories[] | select(.name == $name)
                ][0]}' "${list}" >"${response}"
            ;;
        *)
            echo "tenant repository count is not exact" >&2
            return 1
            ;;
    esac
    test "$(jq -er '.repository.name' "${response}")" = "${repository_name}"
    test "$(jq -er '.repository.project_id' "${response}")" = "${project_a_id}"
    install -o root -g root -m 0600 "${response}" "${repository_state}"

    project_b_status="$(
        curl --disable --silent --show-error \
            --config "${temporary_root}/keystone-b.curl" \
            --cacert "${kolla_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${internal_api}/v1/repositories/$(
                jq -er '.repository.id' "${repository_state}"
            )"
    )"
    test "${project_b_status}" = 404
}

set_quota_limit() {
    local limit="$1"
    local project_a_id

    project_a_id="$(jq -er '.project_a.project_id' "${identity_state}")"
    docker exec -i coffer_api /var/lib/kolla/venv/bin/python3 - \
        "${project_a_id}" "${limit}" <<'PY'
import sys

from coffer.config import parse_config
from coffer.quota import QuotaStore


configuration = parse_config(
    args=["--config-file", "/etc/coffer/coffer.conf"]
)
usage = QuotaStore(configuration.database.connection).set_limit(
    sys.argv[1],
    int(sys.argv[2]),
)
if usage.limit_bytes != int(sys.argv[2]) or usage.reserved_bytes != 0:
    raise SystemExit("quota limit did not converge")
PY
}

quota_snapshot() {
    local project_a_id

    project_a_id="$(jq -er '.project_a.project_id' "${identity_state}")"
    docker exec -i coffer_api /var/lib/kolla/venv/bin/python3 - \
        "${project_a_id}" <<'PY'
import json
import sys

from coffer.config import parse_config
from coffer.quota import QuotaStore


configuration = parse_config(
    args=["--config-file", "/etc/coffer/coffer.conf"]
)
usage = QuotaStore(configuration.database.connection).usage(sys.argv[1])
print(json.dumps({
    "limit_bytes": usage.limit_bytes,
    "reserved_bytes": usage.reserved_bytes,
    "used_bytes": usage.used_bytes,
}, sort_keys=True))
PY
}

prepare_client_state() {
    jq \
        --slurpfile repository "${repository_state}" \
        --arg source_image "${source_image}" \
        '. + {
          repository: $repository[0].repository,
          source_image: $source_image
        }' "${identity_state}" >"${temporary_root}/client.json"
    chmod 0600 "${temporary_root}/client.json"
}

stage_owner_client() {
    stream_owner_file() {
        local destination="$1"

        sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
            sudo tee "${destination}" >/dev/null
    }

    discover_external_owner
    sudo -u ubuntu ssh \
        "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
        sudo install -d -o root -g root -m 0700 "${client_root}"
    stream_owner_file "${client_root}/client.json" \
        <"${temporary_root}/client.json"
    stream_owner_file "${client_root}/ca.crt" <"${kolla_ca}"
    sudo -u ubuntu ssh \
        "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
        sudo chown root:root \
        "${client_root}/client.json" "${client_root}/ca.crt"
    sudo -u ubuntu ssh \
        "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
        sudo chmod 0600 \
        "${client_root}/client.json" "${client_root}/ca.crt"
}

run_owner_client() {
    local client_action="$1"

    stage_owner_client
    sudo -u ubuntu ssh \
        "${ssh_options[@]}" "ubuntu@${external_owner_address}" \
        sudo env LC_ALL=C.UTF-8 LANG=C.UTF-8 bash -s -- \
        "${client_action}" "${client_root}" "${registry_name}" \
        "${registry_url}" <<'REMOTE'
set -Eeuo pipefail
umask 077

action="$1"
client_root="$2"
registry_name="$3"
registry_url="$4"
state="${client_root}/client.json"
ca="${client_root}/ca.crt"
docker_ca="/etc/docker/certs.d/${registry_name}"
hosts_original="${client_root}/hosts.original"
hosts_digest=""
hosts_changed=0
docker_ca_created=0
target_image=""
denied_image=""
temporary_files=(
    "${client_root}/client.json"
    "${client_root}/ca.crt"
    "${client_root}/hosts.original"
    "${client_root}/basic-a.curl"
    "${client_root}/basic-b.curl"
    "${client_root}/registry-a.json"
    "${client_root}/registry-b.json"
    "${client_root}/bearer-a.curl"
    "${client_root}/bearer-b.curl"
    "${client_root}/quota-manifest.json"
    "${client_root}/quota-response.json"
    "${client_root}/quota-config.json"
    "${client_root}/quota-layer.bin"
    "${client_root}/docker-a/config.json"
    "${client_root}/docker-b/config.json"
    "${client_root}/project-b-pull.log"
    "${client_root}/project-b-push.log"
    "${client_root}/manifest.headers"
    "${client_root}/blob.bin"
    "${client_root}/part-1.bin"
    "${client_root}/part-2.bin"
    "${client_root}/upload.headers"
    "${client_root}/evidence.json"
)

cleanup_client() {
    local rc="$?"
    local temporary_file

    trap - EXIT
    if test -n "${target_image}"; then
        docker image rm --force "${target_image}" >/dev/null 2>&1 || true
    fi
    if test -n "${denied_image}"; then
        docker image rm --force "${denied_image}" >/dev/null 2>&1 || true
    fi
    if test "${docker_ca_created}" -eq 1; then
        rm -f -- "${docker_ca}/ca.crt"
        rmdir -- "${docker_ca}" 2>/dev/null || true
    fi
    if test "${hosts_changed}" -eq 1; then
        cp --preserve=all "${hosts_original}" /etc/hosts
        test "$(sha256sum /etc/hosts | awk '{print $1}')" = "${hosts_digest}"
    fi
    for temporary_file in "${temporary_files[@]}"; do
        rm -f -- "${temporary_file}"
    done
    rmdir -- "${client_root}/docker-a" 2>/dev/null || true
    rmdir -- "${client_root}/docker-b" 2>/dev/null || true
    rmdir -- "${client_root}" 2>/dev/null || true
    exit "${rc}"
}
trap cleanup_client EXIT

test "$(id -u)" -eq 0
case "${action}" in
    quota-denial|accept|status)
        ;;
    *)
        exit 64
        ;;
esac
test "$(stat -c '%U:%G:%a' "${client_root}")" = root:root:700
test "$(stat -c '%U:%G:%a' "${state}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${ca}")" = root:root:600
test ! -e "${docker_ca}"
test -z "$(grep -F -- "${registry_name}" /etc/hosts 2>/dev/null || true)"

cp --preserve=all /etc/hosts "${hosts_original}"
hosts_digest="$(sha256sum "${hosts_original}" | awk '{print $1}')"
printf '192.168.254.10 %s\n' "${registry_name}" >>/etc/hosts
hosts_changed=1
getent ahostsv4 "${registry_name}" |
    awk '$1 != "192.168.254.10" {exit 1}'

install -d -o root -g root -m 0755 "${docker_ca}"
install -o root -g root -m 0644 "${ca}" "${docker_ca}/ca.crt"
docker_ca_created=1
printf 'coffer_tenant_owner checkpoint=network-boundary state=ready\n' >&2

project_a_id="$(jq -er '.project_a.project_id' "${state}")"
project_b_id="$(jq -er '.project_b.project_id' "${state}")"
credential_a_id="$(
    jq -er '.project_a.application_credential_id' "${state}"
)"
credential_b_id="$(
    jq -er '.project_b.application_credential_id' "${state}"
)"
secret_a="$(jq -er '.project_a.application_credential_secret' "${state}")"
secret_b="$(jq -er '.project_b.application_credential_secret' "${state}")"
repository_name="$(jq -er '.repository.name' "${state}")"
source_image="$(jq -er '.source_image' "${state}")"
repository="p/${project_a_id}/${repository_name}"
target_image="${registry_name}/${repository}:baseline"
denied_image="${registry_name}/${repository}:project-b-denied"

make_basic_config() {
    local identifier="$1"
    local secret="$2"
    local output="$3"

    printf 'user = "%s:%s"\n' "${identifier}" "${secret}" >"${output}"
    chmod 0600 "${output}"
}

request_registry_token() {
    local basic_config="$1"
    local output="$2"

    curl --disable --fail --silent --show-error \
        --config "${basic_config}" \
        --cacert "${ca}" \
        --output "${output}" \
        --get \
        --data-urlencode 'service=coffer-registry' \
        --data-urlencode "scope=repository:${repository}:pull,push,delete" \
        "${registry_url}/auth/token"
    chmod 0600 "${output}"
}

make_bearer_config() {
    local token_json="$1"
    local output="$2"
    local bearer

    bearer="$(jq -er '.token' "${token_json}")"
    printf 'header = "Authorization: Bearer %s"\n' "${bearer}" >"${output}"
    chmod 0600 "${output}"
    unset bearer
}

make_basic_config "${credential_a_id}" "${secret_a}" \
    "${client_root}/basic-a.curl"
make_basic_config "${credential_b_id}" "${secret_b}" \
    "${client_root}/basic-b.curl"
request_registry_token \
    "${client_root}/basic-a.curl" "${client_root}/registry-a.json"
make_bearer_config \
    "${client_root}/registry-a.json" "${client_root}/bearer-a.curl"
printf 'coffer_tenant_owner checkpoint=token-a state=ready\n' >&2
if test "${action}" != quota-denial; then
    request_registry_token \
        "${client_root}/basic-b.curl" "${client_root}/registry-b.json"
    make_bearer_config \
        "${client_root}/registry-b.json" "${client_root}/bearer-b.curl"
    printf 'coffer_tenant_owner checkpoint=token-b state=ready\n' >&2
fi

location_url() {
    local location="$1"

    case "${location}" in
        "${registry_url}"/*)
            printf '%s\n' "${location}"
            ;;
        /*)
            printf '%s%s\n' "${registry_url}" "${location}"
            ;;
        *)
            echo "registry upload location changed origin" >&2
            return 1
            ;;
    esac
}

upload_complete_blob() {
    local blob_path="$1"
    local blob_digest="$2"
    local upload_status
    local upload_location
    local upload_url
    local separator

    upload_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --dump-header "${client_root}/upload.headers" \
            --write-out '%{http_code}' \
            --request POST \
            --header 'Content-Length: 0' \
            "${registry_url}/v2/${repository}/blobs/uploads/"
    )"
    test "${upload_status}" = 202
    upload_location="$(
        awk -F': ' '
            tolower($1) == "location" {
                gsub("\r", "", $2)
                print $2
            }
        ' "${client_root}/upload.headers"
    )"
    upload_url="$(location_url "${upload_location}")"
    case "${upload_url}" in
        *\?*) separator='&' ;;
        *) separator='?' ;;
    esac
    upload_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            --request PUT \
            --header 'Content-Type: application/octet-stream' \
            --data-binary "@${blob_path}" \
            "${upload_url}${separator}digest=${blob_digest}"
    )"
    test "${upload_status}" = 201
}

if test "${action}" = quota-denial; then
    printf '{}\n' >"${client_root}/quota-config.json"
    printf 'coffer-stage5-quota-denial-layer\n' \
        >"${client_root}/quota-layer.bin"
    quota_config_digest="sha256:$(
        sha256sum "${client_root}/quota-config.json" | awk '{print $1}'
    )"
    quota_layer_digest="sha256:$(
        sha256sum "${client_root}/quota-layer.bin" | awk '{print $1}'
    )"
    quota_config_size="$(wc -c <"${client_root}/quota-config.json")"
    quota_layer_size="$(wc -c <"${client_root}/quota-layer.bin")"
    upload_complete_blob \
        "${client_root}/quota-config.json" "${quota_config_digest}"
    upload_complete_blob \
        "${client_root}/quota-layer.bin" "${quota_layer_digest}"
    jq -n \
        --arg config_digest "${quota_config_digest}" \
        --arg layer_digest "${quota_layer_digest}" \
        --argjson config_size "${quota_config_size}" \
        --argjson layer_size "${quota_layer_size}" '{
      schemaVersion: 2,
      mediaType: "application/vnd.oci.image.manifest.v1+json",
      config: {
        mediaType: "application/vnd.oci.image.config.v1+json",
        digest: $config_digest,
        size: $config_size
      },
      layers: [{
        mediaType: "application/vnd.oci.image.layer.v1.tar",
        digest: $layer_digest,
        size: $layer_size
      }]
    }' >"${client_root}/quota-manifest.json"
    quota_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output "${client_root}/quota-response.json" \
            --write-out '%{http_code}' \
            --request PUT \
            --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
            --data-binary "@${client_root}/quota-manifest.json" \
            "${registry_url}/v2/${repository}/manifests/quota-denied"
    )"
    printf 'coffer_tenant_owner checkpoint=quota-response status=%s\n' \
        "${quota_status}" >&2
    if test "${quota_status}" != 429; then
        jq -r '
          .errors[]?
          | "coffer_tenant_owner quota_error_code=\(.code) message=\(.message)"
        ' "${client_root}/quota-response.json" >&2
    fi
    test "${quota_status}" = 429
    jq -e '
      .errors == [{
        "code": "TOOMANYREQUESTS",
        "message": "project logical quota exceeded"
      }]
    ' "${client_root}/quota-response.json" >/dev/null
    printf 'quota=429\n'
    exit 0
fi

if test "${action}" = accept; then
    install -d -o root -g root -m 0700 \
        "${client_root}/docker-a" "${client_root}/docker-b"
    printf '%s\n' "${secret_a}" |
        docker --config "${client_root}/docker-a" login \
            --username "${credential_a_id}" --password-stdin \
            "${registry_name}" >/dev/null 2>&1
    printf '%s\n' "${secret_b}" |
        docker --config "${client_root}/docker-b" login \
            --username "${credential_b_id}" --password-stdin \
            "${registry_name}" >/dev/null 2>&1
    printf 'coffer_tenant_owner checkpoint=docker-login state=ready\n' >&2

    docker image inspect "${source_image}" >/dev/null
    docker tag "${source_image}" "${target_image}"
    timeout 1800 docker --config "${client_root}/docker-a" push \
        --quiet "${target_image}" >/dev/null
    printf 'coffer_tenant_owner checkpoint=docker-push state=passed\n' >&2

    curl --disable --fail --silent --show-error \
        --head \
        --config "${client_root}/bearer-a.curl" \
        --cacert "${ca}" \
        --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
        --header 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
        --dump-header "${client_root}/manifest.headers" \
        --output /dev/null \
        "${registry_url}/v2/${repository}/manifests/baseline"
    manifest_digest="$(
        awk -F': ' '
            tolower($1) == "docker-content-digest" {
                gsub("\r", "", $2)
                print $2
            }
        ' "${client_root}/manifest.headers"
    )"
    [[ "${manifest_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
    printf 'coffer_tenant_owner checkpoint=manifest state=present\n' >&2

    docker image rm --force "${target_image}" >/dev/null
    timeout 1800 docker --config "${client_root}/docker-a" pull \
        --quiet "${target_image}" >/dev/null
    docker image inspect "${target_image}" \
        --format '{{json .RepoDigests}}' |
        jq -e \
            --arg expected "${registry_name}/${repository}@${manifest_digest}" \
            'index($expected) != null' >/dev/null
    printf 'coffer_tenant_owner checkpoint=docker-pull state=passed\n' >&2

    if docker --config "${client_root}/docker-b" pull \
        "${target_image}" >"${client_root}/project-b-pull.log" 2>&1; then
        echo "project B unexpectedly pulled project A content" >&2
        exit 35
    fi
    docker tag "${source_image}" "${denied_image}"
    if docker --config "${client_root}/docker-b" push \
        "${denied_image}" >"${client_root}/project-b-push.log" 2>&1; then
        echo "project B unexpectedly pushed project A content" >&2
        exit 36
    fi
    if grep -aFq -- "${secret_a}" \
        "${client_root}/project-b-pull.log" \
        "${client_root}/project-b-push.log" ||
        grep -aFq -- "${secret_b}" \
            "${client_root}/project-b-pull.log" \
            "${client_root}/project-b-push.log"; then
        echo "tenant credential secret leaked into client logs" >&2
        exit 37
    fi
    if grep -aEq \
        'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
        "${client_root}/project-b-pull.log" \
        "${client_root}/project-b-push.log"; then
        echo "tenant bearer token leaked into client logs" >&2
        exit 38
    fi
    unset secret_a secret_b
    printf 'coffer_tenant_owner checkpoint=project-b state=denied\n' >&2

    python3 - "${client_root}/blob.bin" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).write_bytes(bytes(range(256)) * 8192)
PY
    dd if="${client_root}/blob.bin" of="${client_root}/part-1.bin" \
        bs=1048576 count=1 status=none
    dd if="${client_root}/blob.bin" of="${client_root}/part-2.bin" \
        bs=1048576 skip=1 count=1 status=none
    blob_digest="sha256:$(
        sha256sum "${client_root}/blob.bin" | awk '{print $1}'
    )"

    upload_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --dump-header "${client_root}/upload.headers" \
            --write-out '%{http_code}' \
            --request POST \
            --header 'Content-Length: 0' \
            "${registry_url}/v2/${repository}/blobs/uploads/"
    )"
    test "${upload_status}" = 202
    upload_location="$(
        awk -F': ' '
            tolower($1) == "location" {
                gsub("\r", "", $2)
                print $2
            }
        ' "${client_root}/upload.headers"
    )"
    upload_url="$(location_url "${upload_location}")"

    for part in 1 2; do
        upload_status="$(
            curl --disable --silent --show-error \
                --config "${client_root}/bearer-a.curl" \
                --cacert "${ca}" \
                --output /dev/null \
                --dump-header "${client_root}/upload.headers" \
                --write-out '%{http_code}' \
                --request PATCH \
                --header 'Content-Type: application/octet-stream' \
                --data-binary "@${client_root}/part-${part}.bin" \
                "${upload_url}"
        )"
        test "${upload_status}" = 202
        upload_location="$(
            awk -F': ' '
                tolower($1) == "location" {
                    gsub("\r", "", $2)
                    print $2
                }
            ' "${client_root}/upload.headers"
        )"
        upload_url="$(location_url "${upload_location}")"
        printf 'coffer_tenant_owner checkpoint=resumable-part part=%s state=passed\n' \
            "${part}" >&2
    done
    case "${upload_url}" in
        *\?*) separator='&' ;;
        *) separator='?' ;;
    esac
    upload_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            --request PUT \
            --header 'Content-Length: 0' \
            "${upload_url}${separator}digest=${blob_digest}"
    )"
    test "${upload_status}" = 201
    blob_status="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-a.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            --head \
            "${registry_url}/v2/${repository}/blobs/${blob_digest}"
    )"
    test "${blob_status}" = 200
    printf 'coffer_tenant_owner checkpoint=resumable-finalize state=passed\n' >&2

    project_b_tags="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-b.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${registry_url}/v2/${repository}/tags/list"
    )"
    project_b_blob="$(
        curl --disable --silent --show-error \
            --config "${client_root}/bearer-b.curl" \
            --cacert "${ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            --head \
            "${registry_url}/v2/${repository}/blobs/${blob_digest}"
    )"
    test "${project_b_tags}" = 401
    test "${project_b_blob}" = 401

    jq -n \
        --arg repository "${repository}" \
        --arg manifest_digest "${manifest_digest}" \
        --arg resumable_blob_digest "${blob_digest}" \
        '{
          repository: $repository,
          manifest_digest: $manifest_digest,
          resumable_blob_digest: $resumable_blob_digest,
          project_a_push_pull: "passed",
          resumable_upload_parts: 2,
          project_b_pull: "denied",
          project_b_push: "denied",
          project_b_tags_status: 401,
          project_b_blob_status: 401
        }' >"${client_root}/evidence.json"
    cat "${client_root}/evidence.json"
    exit 0
fi

expected_manifest="$(jq -er '.manifest_digest' "${state}")"
expected_blob="$(jq -er '.resumable_blob_digest' "${state}")"
manifest_status="$(
    curl --disable --silent --show-error \
        --config "${client_root}/bearer-a.curl" \
        --cacert "${ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        --head \
        "${registry_url}/v2/${repository}/manifests/${expected_manifest}"
)"
blob_status="$(
    curl --disable --silent --show-error \
        --config "${client_root}/bearer-a.curl" \
        --cacert "${ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        --head \
        "${registry_url}/v2/${repository}/blobs/${expected_blob}"
)"
project_b_status="$(
    curl --disable --silent --show-error \
        --config "${client_root}/bearer-b.curl" \
        --cacert "${ca}" \
        --output /dev/null \
        --write-out '%{http_code}' \
        --head \
        "${registry_url}/v2/${repository}/manifests/${expected_manifest}"
)"
test "${manifest_status}" = 200
test "${blob_status}" = 200
test "${project_b_status}" = 401
printf 'status=passed\n'
REMOTE
}

scan_runtime_logs() {
    local index
    local log

    collect_runtime_log() {
        local address="$1"

        sudo -u ubuntu ssh \
            "${ssh_options[@]}" "ubuntu@${address}" \
            sudo env LC_ALL=C LANG=C bash -s
    }

    for index in "${!addresses[@]}"; do
        log="${temporary_root}/${hostnames[${index}]}.runtime.log"
        collect_runtime_log "${addresses[${index}]}" \
            >"${log}" 2>&1 <<'REMOTE'
set -Eeuo pipefail
docker logs coffer_api
docker logs coffer_edge
docker logs coffer_registry
REMOTE
        chmod 0600 "${log}"
    done
    /home/ubuntu/coffer-stage5/venv/bin/python3 - \
        "${identity_state}" \
        "${temporary_root}/${hostnames[0]}.runtime.log" \
        "${temporary_root}/${hostnames[1]}.runtime.log" \
        "${temporary_root}/${hostnames[2]}.runtime.log" <<'PY'
from pathlib import Path
import json
import re
import sys


state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
secrets = []
for fixture_name in ("project_a", "project_b"):
    fixture = state[fixture_name]
    secrets.extend((
        fixture["user_password"].encode(),
        fixture["application_credential_secret"].encode(),
    ))
data = b"".join(Path(path).read_bytes() for path in sys.argv[2:])
if any(secret in data for secret in secrets):
    raise SystemExit("tenant secret found in Coffer runtime logs")
if b"-----BEGIN PRIVATE KEY-----" in data:
    raise SystemExit("private key found in Coffer runtime logs")
if re.search(
    rb"Authorization ['\"](?:Basic|Bearer) [A-Za-z0-9+/=._-]+",
    data,
):
    raise SystemExit("authorization credential found in Coffer runtime logs")
if re.search(
    rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
    data,
):
    raise SystemExit("bearer token found in Coffer runtime logs")
PY
    printf 'coffer_tenant_runtime_log_audit hosts=3 containers=9 secrets=redacted result=passed\n'
}

write_marker() {
    local marker="$1"
    local temporary="${marker}.tmp.$$"

    printf '%s\n' "${marker_value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
}

require_marker() {
    local marker="$1"

    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${marker_value}"
}

prepare_control_clients() {
    issue_keystone_token project_a "${temporary_root}/keystone-a.token"
    issue_keystone_token project_b "${temporary_root}/keystone-b.token"
    make_keystone_curl_config \
        "${temporary_root}/keystone-a.token" \
        "${temporary_root}/keystone-a.curl"
    make_keystone_curl_config \
        "${temporary_root}/keystone-b.token" \
        "${temporary_root}/keystone-b.curl"
}

require_accepted_boundary() {
    local client_status
    local project_a_status
    local project_b_status
    local quota

    test "$(stat -c '%U:%G:%a' "${acceptance_root}")" = root:root:700
    test "$(stat -c '%U:%G:%a' "${repository_state}")" = root:root:600
    test "$(stat -c '%U:%G:%a' "${evidence_file}")" = root:root:600
    require_marker "${quota_marker}"
    require_marker "${accepted_marker}"
    prepare_control_clients
    project_a_status="$(
        curl --disable --silent --show-error \
            --config "${temporary_root}/keystone-a.curl" \
            --cacert "${kolla_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${internal_api}/v1/repositories/$(
                jq -er '.repository.id' "${repository_state}"
            )"
    )"
    project_b_status="$(
        curl --disable --silent --show-error \
            --config "${temporary_root}/keystone-b.curl" \
            --cacert "${kolla_ca}" \
            --output /dev/null \
            --write-out '%{http_code}' \
            "${internal_api}/v1/repositories/$(
                jq -er '.repository.id' "${repository_state}"
            )"
    )"
    test "${project_a_status}" = 200
    test "${project_b_status}" = 404
    prepare_client_state
    jq \
        --slurpfile evidence "${evidence_file}" \
        '. + $evidence[0]' "${temporary_root}/client.json" \
        >"${temporary_root}/client-status.json"
    mv -f \
        "${temporary_root}/client-status.json" \
        "${temporary_root}/client.json"
    client_status="$(run_owner_client status)"
    test "${client_status}" = status=passed
    verify_owner_client_clean
    quota="$(quota_snapshot)"
    jq -e '
      .limit_bytes == 2147483648
      and .used_bytes > 0
      and .used_bytes <= .limit_bytes
      and .reserved_bytes == 0
    ' <<<"${quota}" >/dev/null
    test "$(control_snapshot)" = "repositories=1 quotas=1"
    scan_runtime_logs
    printf 'coffer_tenant_acceptance state=accepted repository=1 quota=healthy digest=retained isolation=passed\n'
}

if test "${action}" = preflight; then
    require_clean_boundary
    exit 0
fi

create_temporary_root

if test "${action}" = status; then
    require_accepted_boundary
    exit 0
fi

exec 9>/run/lock/coffer-stage5-tenant-acceptance.lock
if ! flock -n 9; then
    echo "refusing concurrent Coffer tenant acceptance execution" >&2
    exit 75
fi

if test -e "${accepted_marker}"; then
    require_accepted_boundary
    printf 'coffer_tenant_acceptance phase=accept result=passed idempotent=yes\n'
    exit 0
fi

if test ! -e "${acceptance_root}"; then
    require_clean_boundary
    install -d -o root -g root -m 0700 "${acceptance_root}"
else
    test "$(stat -c '%U:%G:%a' "${acceptance_root}")" = root:root:700
    test ! -e "${accepted_marker}"
fi

prepare_control_clients
printf 'coffer_tenant_acceptance checkpoint=control-tokens state=ready\n'
ensure_repository
printf 'coffer_tenant_acceptance checkpoint=repository state=ready\n'

if test ! -e "${quota_marker}"; then
    set_quota_limit 1
    prepare_client_state
    quota_result="$(run_owner_client quota-denial)"
    test "${quota_result}" = quota=429
    verify_owner_client_clean
    write_marker "${quota_marker}"
    printf 'coffer_tenant_acceptance checkpoint=quota-denial status=429\n'
else
    require_marker "${quota_marker}"
fi

set_quota_limit 2147483648
printf 'coffer_tenant_acceptance checkpoint=quota-open limit=2147483648\n'
prepare_client_state
printf 'coffer_tenant_acceptance checkpoint=owner-full state=starting\n'
set +e
client_evidence="$(run_owner_client accept)"
client_rc="$?"
set -e
if test "${client_rc}" -ne 0; then
    printf 'coffer_tenant_acceptance checkpoint=owner-full state=failed rc=%s\n' \
        "${client_rc}" >&2
    exit "${client_rc}"
fi
printf 'coffer_tenant_acceptance checkpoint=owner-full state=passed\n'
verify_owner_client_clean
printf '%s\n' "${client_evidence}" >"${temporary_root}/client-evidence.json"
jq -e '
  .project_a_push_pull == "passed"
  and .resumable_upload_parts == 2
  and .project_b_pull == "denied"
  and .project_b_push == "denied"
  and .project_b_tags_status == 401
  and .project_b_blob_status == 401
' "${temporary_root}/client-evidence.json" >/dev/null
install -o root -g root -m 0600 \
    "${temporary_root}/client-evidence.json" "${evidence_file}"

quota="$(quota_snapshot)"
jq -e '
  .limit_bytes == 2147483648
  and .used_bytes > 0
  and .used_bytes <= .limit_bytes
  and .reserved_bytes == 0
' <<<"${quota}" >/dev/null
test "$(control_snapshot)" = "repositories=1 quotas=1"
scan_runtime_logs
write_marker "${accepted_marker}"
require_accepted_boundary

printf 'coffer_tenant_acceptance phase=accept result=passed marker=complete quota_denial=429 push_pull=passed resumable_parts=2 isolation=passed\n'
