#!/usr/bin/env bash

set -Eeuo pipefail

identity_file="/root/coffer-ui-preview-identities.json"
evidence_file="/home/ubuntu/coffer-artifact-api-acceptance.json"
api_origin="http://192.168.122.205:8788"
repository_name="preview-proof"
temporary_root="$(mktemp -d /root/coffer-artifact-api.XXXXXX)"

cleanup() {
    rm -rf -- "${temporary_root}"
    unset project_a_token project_b_token
}
trap cleanup EXIT
trap 'printf "artifact_api_acceptance=failed line=%s\n" "${LINENO}" >&2' ERR

test "$(id -u)" -eq 0
test "$(hostname)" = "coffer-ui-preview-1"
test -s "${identity_file}"
test ! -L "${identity_file}"
. /etc/kolla/admin-openrc.sh
test "${OS_AUTH_URL}" = "http://192.168.122.205:5000"
auth_url="${OS_AUTH_URL}/v3/auth/tokens"
unset OS_APPLICATION_CREDENTIAL_ID OS_APPLICATION_CREDENTIAL_SECRET
unset OS_PASSWORD OS_TOKEN

application_credential_token() {
    local fixture="$1"
    local headers token
    headers="$(mktemp "${temporary_root}/headers.XXXXXX")"
    jq -ce \
        --arg fixture "${fixture}" \
        '{
          auth: {
            identity: {
              methods: ["application_credential"],
              application_credential: {
                id: .[$fixture].application_credential_id,
                secret: .[$fixture].application_credential_secret
              }
            }
          }
        }' "${identity_file}" |
        curl --silent --show-error --fail \
            --dump-header "${headers}" \
            --output /dev/null \
            --header "Content-Type: application/json" \
            --data-binary @- \
            "${auth_url}"
    token="$(
        awk '
          tolower($1) == "x-subject-token:" {
            gsub("\r", "", $2)
            print $2
          }
        ' "${headers}"
    )"
    test -n "${token}"
    printf '%s' "${token}"
}

project_a_token="$(application_credential_token project_a)"
project_b_token="$(application_credential_token project_b)"
repositories="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories?limit=100"
)"
repository_id="$(
    jq -er \
        --arg name "${repository_name}" \
        '.repositories[] | select(.name == $name) | .id' \
        <<<"${repositories}"
)"

artifacts="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories/${repository_id}/artifacts?limit=100"
)"
jq -e '
  (.artifacts | length) >= 3
  and .next_marker == null
  and (
    [.artifacts[].tags[]]
    | contains([
        "0.1.0",
        "user-docker",
        "user-failover",
        "user-oras",
        "user-podman"
      ])
  )
  and any(
    .artifacts[];
    .artifact_type == "application/vnd.cncf.helm.config.v1+json"
    and .kind == "artifact"
  )
' <<<"${artifacts}" >/dev/null

first_page="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories/${repository_id}/artifacts?limit=1"
)"
marker="$(jq -er '.next_marker' <<<"${first_page}")"
second_page="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories/${repository_id}/artifacts?limit=1&marker=${marker}"
)"
test "$(jq -r '.artifacts | length' <<<"${first_page}")" -eq 1
test "$(jq -r '.artifacts | length' <<<"${second_page}")" -eq 1
test "$(
    jq -r '.artifacts[0].digest' <<<"${first_page}"
)" != "$(
    jq -r '.artifacts[0].digest' <<<"${second_page}"
)"

search="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories/${repository_id}/artifacts?limit=10&query=0.1.0"
)"
test "$(jq -r '.artifacts | length' <<<"${search}")" -eq 1
helm_digest="$(jq -er '.artifacts[0].digest' <<<"${search}")"
detail="$(
    curl --silent --show-error --fail \
        --header "X-Auth-Token: ${project_a_token}" \
        "${api_origin}/v1/repositories/${repository_id}/artifacts/${helm_digest}"
)"
test "$(jq -r '.artifact.digest' <<<"${detail}")" = "${helm_digest}"

project_b_status="$(
    curl --silent --show-error \
        --header "X-Auth-Token: ${project_b_token}" \
        --output "${temporary_root}/project-b.json" \
        --write-out '%{http_code}' \
        "${api_origin}/v1/repositories/${repository_id}/artifacts?limit=10"
)"
test "${project_b_status}" = 404

temporary_evidence="${temporary_root}/evidence.json"
jq -n \
    --arg repository_id "${repository_id}" \
    --arg helm_digest "${helm_digest}" \
    --argjson artifact_count "$(jq '.artifacts | length' <<<"${artifacts}")" \
    '{
      schema: "coffer.artifact-api-acceptance/v1",
      repository_id: $repository_id,
      artifact_count: $artifact_count,
      required_tags_visible: true,
      helm_digest: $helm_digest,
      helm_search: true,
      keyset_pagination: true,
      project_b_denied: true,
      secret_transport: "stdin-or-memory-only"
    }' >"${temporary_evidence}"
chown ubuntu:ubuntu "${temporary_evidence}"
chmod 0600 "${temporary_evidence}"
mv "${temporary_evidence}" "${evidence_file}"

printf 'artifact_api_acceptance=passed artifact_count=%s\n' \
    "$(jq -r '.artifact_count' "${evidence_file}")"
