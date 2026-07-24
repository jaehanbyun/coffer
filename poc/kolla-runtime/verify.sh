#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${ROOT}/work/kolla-runtime"
EVIDENCE="${WORK}/evidence"
SCOUT_EVIDENCE="work/kolla-runtime/evidence"
BASE_IMAGE="localhost/coffer-stage2-base:2026.1"
COFFER_IMAGE="localhost/coffer-stage2:2026.1"
REGISTRY_IMAGE="localhost/coffer-stage2-registry:3.1.1"
NETWORK="coffer-stage2-network"
DATABASE_VOLUME="coffer-stage2-database"
REGISTRY_VOLUME="coffer-stage2-registry-data"
CONTROL_CONTAINER="coffer-stage2-api"
EDGE_CONTAINER="coffer-stage2-edge"
REGISTRY_CONTAINER="coffer-stage2-registry"
BOOTSTRAP_CONTAINER="coffer-stage2-bootstrap"
RECONCILE_CONTAINER="coffer-stage2-reconcile"
API_PORT=18787
EDGE_PORT=18788
WAIT_ATTEMPTS="${COFFER_STAGE2_WAIT_ATTEMPTS:-60}"

machine_started_here=false
context=""
fixture=""
fixture_parent=""
runtime_cleaned=false
phase="initialization"

if [[ ! "${WAIT_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]] || ((WAIT_ATTEMPTS > 60)); then
    echo "COFFER_STAGE2_WAIT_ATTEMPTS must be an integer from 1 through 60" >&2
    exit 1
fi

report_failure() {
    local exit_code="$1"
    local line="$2"
    echo "Kolla runtime verification failed phase=${phase} line=${line} exit=${exit_code}" >&2
    if [[ -d "${EVIDENCE}" ]]; then
        printf 'phase=%s\nline=%s\nexit=%s\n' \
            "${phase}" "${line}" "${exit_code}" \
            >"${EVIDENCE}/failure-summary.txt"
    fi
    if podman info >/dev/null 2>&1; then
        local name
        for name in "${REGISTRY_CONTAINER}" "${CONTROL_CONTAINER}" "${EDGE_CONTAINER}"; do
            if podman container exists "${name}"; then
                podman inspect --format \
                    'container={{.Name}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} exit={{.State.ExitCode}}' \
                    "${name}" >&2 || true
                podman logs --tail 80 "${name}" >&2 || true
            fi
        done
    fi
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "required command is unavailable: $1" >&2
        exit 1
    fi
}

remove_exact_runtime() {
    local name
    for name in \
        "${CONTROL_CONTAINER}" "${EDGE_CONTAINER}" "${REGISTRY_CONTAINER}" \
        "${BOOTSTRAP_CONTAINER}" "${RECONCILE_CONTAINER}"; do
        podman rm --force "${name}" >/dev/null 2>&1 || true
    done
    podman volume rm --force "${DATABASE_VOLUME}" >/dev/null 2>&1 || true
    podman volume rm --force "${REGISTRY_VOLUME}" >/dev/null 2>&1 || true
    podman network rm --force "${NETWORK}" >/dev/null 2>&1 || true
    podman image rm --force "${COFFER_IMAGE}" >/dev/null 2>&1 || true
    podman image rm --force "${REGISTRY_IMAGE}" >/dev/null 2>&1 || true
    podman image rm --force "${BASE_IMAGE}" >/dev/null 2>&1 || true
}

remove_generated_directory() {
    local path="$1"
    if [[ -n "${path}" && "${path}" == "${WORK}"/tmp.* ]]; then
        rm -rf -- "${path}"
    fi
}

cleanup() {
    local exit_code=$?
    if [[ "${runtime_cleaned}" != "true" ]] && podman info >/dev/null 2>&1; then
        remove_exact_runtime
    fi
    remove_generated_directory "${fixture}"
    remove_generated_directory "${fixture_parent}"
    remove_generated_directory "${context}"
    rm -f -- "${EVIDENCE}/coffer-image.tar" \
        "${EVIDENCE}/registry-image.tar"
    if [[ "${machine_started_here}" == "true" ]]; then
        podman machine stop >/dev/null 2>&1 || true
    fi
    exit "${exit_code}"
}
trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

wait_for_health() {
    local container="$1"
    local attempt status
    for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
        status="$(podman inspect --format '{{.State.Health.Status}}' "${container}")"
        if [[ "${status}" == "healthy" ]]; then
            return 0
        fi
        sleep 1
    done
    podman logs "${container}" >&2 || true
    echo "container did not become healthy: ${container}" >&2
    return 1
}

wait_for_api() {
    local attempt
    for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
        if curl --disable --fail --silent --show-error \
            --cacert "${fixture}/ca.crt" \
            "https://127.0.0.1:${API_PORT}/readyz" \
            --output /dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_for_edge() {
    local attempt status
    for ((attempt = 1; attempt <= WAIT_ATTEMPTS; attempt++)); do
        status="$(curl --disable --silent --show-error \
            --cacert "${fixture}/ca.crt" \
            "https://127.0.0.1:${EDGE_PORT}/v2/" \
            --output /dev/null --write-out '%{http_code}' || true)"
        if [[ "${status}" == "401" ]]; then
            return 0
        fi
        sleep 1
    done
    echo "edge challenge returned HTTP ${status:-none}" >&2
    podman exec "${EDGE_CONTAINER}" python3 -c \
        "from coffer.registry_proxy import UpstreamOrigin; origin=UpstreamOrigin.from_url('https://${REGISTRY_CONTAINER}:8789', label='diagnostic registry', timeout_seconds=5, cafile='/etc/coffer/backend-ca.crt'); connection=origin.connect(); connection.request('GET', '/v2/'); response=connection.getresponse(); print(f'direct registry diagnostic status={response.status}')" \
        >"${EVIDENCE}/edge-diagnostic.txt" 2>&1 || true
    cat "${EVIDENCE}/edge-diagnostic.txt" >&2
    return 1
}

run_bootstrap() {
    podman run --name "${BOOTSTRAP_CONTAINER}" --rm \
        --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
        --volume "${fixture}/bootstrap:/var/lib/kolla/config_files:ro" \
        --volume "${DATABASE_VOLUME}:/var/lib/coffer" \
        "${COFFER_IMAGE}"
}

assert_equal() {
    local label="$1"
    local expected="$2"
    local actual="$3"
    if [[ "${actual}" != "${expected}" ]]; then
        printf 'runtime contract mismatch: %s expected=%q actual=%q\n' \
            "${label}" "${expected}" "${actual}" >&2
        return 1
    fi
}

assert_container_test() {
    local label="$1"
    local container="$2"
    shift 2
    if ! podman exec "${container}" test "$@"; then
        echo "runtime contract check failed: ${label}" >&2
        return 1
    fi
}

require_command podman
require_command curl
require_command jq
require_command docker
require_command uv
docker scout version >/dev/null

mkdir -p "${WORK}" "${EVIDENCE}"
rm -f -- "${EVIDENCE}/edge-diagnostic.txt" \
    "${EVIDENCE}/failure-summary.txt"

machine_state="$(podman machine inspect --format '{{.State}}')"
if [[ "${machine_state}" != "running" ]]; then
    podman machine start
    machine_started_here=true
fi
podman info >/dev/null

remove_exact_runtime

python3 - "${API_PORT}" "${EDGE_PORT}" <<'PY'
import socket
import sys

for raw_port in sys.argv[1:]:
    port = int(raw_port)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
PY

context="$(mktemp -d "${WORK}/tmp.context.XXXXXX")"
fixture_parent="$(mktemp -d "${WORK}/tmp.fixture-parent.XXXXXX")"
fixture="${fixture_parent}/fixture"

cp "${ROOT}/pyproject.toml" "${ROOT}/README.md" "${context}/"
mkdir -p "${context}/src"
cp -R "${ROOT}/src/coffer" "${context}/src/coffer"

podman build --layers --pull=always \
    --file "${ROOT}/poc/kolla-runtime/Containerfile.base" \
    --tag "${BASE_IMAGE}" "${context}"
podman build --layers --pull=never \
    --file "${ROOT}/poc/kolla-runtime/Containerfile.coffer" \
    --tag "${COFFER_IMAGE}" "${context}"

runtime_arch="$(podman info --format '{{.Host.Arch}}')"
case "${runtime_arch}" in
    arm64 | aarch64)
        distribution_arch="arm64"
        distribution_sha="8167316d2b4a57e10d44f8c8a3c75fea5f3ec1c71872760bb903e5e8e52e9ad6"
        ;;
    amd64 | x86_64)
        distribution_arch="amd64"
        distribution_sha="6f330a3ba9ea1d23a6ee189f449d792595240585bb2f159123d76ac594f70dd8"
        ;;
    *)
        echo "unsupported local architecture: ${runtime_arch}" >&2
        exit 1
        ;;
esac

podman build --layers --pull=never \
    --build-arg "DISTRIBUTION_ARCH=${distribution_arch}" \
    --build-arg "DISTRIBUTION_SHA256=${distribution_sha}" \
    --file "${ROOT}/poc/kolla-runtime/Containerfile.registry" \
    --tag "${REGISTRY_IMAGE}" "${context}"

podman run --rm --entrypoint registry "${REGISTRY_IMAGE}" --version \
    | grep -F '3.1.1' >/dev/null
for command in coffer-api coffer-edge coffer-reconcile coffer-bootstrap; do
    podman run --rm --entrypoint "${command}" "${COFFER_IMAGE}" --help \
        >/dev/null
done

podman image inspect "${COFFER_IMAGE}" "${REGISTRY_IMAGE}" \
    | jq '[.[] | {
        id: .Id,
        architecture: .Architecture,
        os: .Os,
        user: .Config.User,
        labels: .Config.Labels
    }]' >"${EVIDENCE}/images.json"

podman save --format docker-archive \
    --output "${EVIDENCE}/coffer-image.tar" "${COFFER_IMAGE}"
podman save --format docker-archive \
    --output "${EVIDENCE}/registry-image.tar" "${REGISTRY_IMAGE}"
(
    cd "${ROOT}"
    docker scout sbom --format spdx \
        --output "${SCOUT_EVIDENCE}/coffer.spdx.json" \
        "archive://${SCOUT_EVIDENCE}/coffer-image.tar"
    docker scout sbom --format spdx \
        --output "${SCOUT_EVIDENCE}/registry.spdx.json" \
        "archive://${SCOUT_EVIDENCE}/registry-image.tar"
    docker scout cves --format sarif \
        --output "${SCOUT_EVIDENCE}/coffer.cves.sarif.json" \
        "archive://${SCOUT_EVIDENCE}/coffer-image.tar"
    docker scout cves --format sarif \
        --output "${SCOUT_EVIDENCE}/registry.cves.sarif.json" \
        "archive://${SCOUT_EVIDENCE}/registry-image.tar"
    docker scout cves --only-severity critical,high \
        --output "${SCOUT_EVIDENCE}/coffer-critical-high.txt" \
        "archive://${SCOUT_EVIDENCE}/coffer-image.tar"
    docker scout cves --only-severity critical,high \
        --output "${SCOUT_EVIDENCE}/registry-critical-high.txt" \
        "archive://${SCOUT_EVIDENCE}/registry-image.tar"
)
rm -f -- "${EVIDENCE}/coffer-image.tar" \
    "${EVIDENCE}/registry-image.tar"

uv run python "${ROOT}/poc/kolla-runtime/generate_fixture.py" "${fixture}"

podman network create --label io.coffer.stage2=true "${NETWORK}" >/dev/null
podman volume create --label io.coffer.stage2=true \
    "${DATABASE_VOLUME}" >/dev/null
podman volume create --label io.coffer.stage2=true \
    "${REGISTRY_VOLUME}" >/dev/null

run_bootstrap
run_bootstrap

project_id="$(jq -r .project_id "${fixture}/artifact.json")"
podman run --rm --user coffer --entrypoint python3 \
    --volume "${DATABASE_VOLUME}:/var/lib/coffer" \
    "${COFFER_IMAGE}" -c \
    "from coffer.db import RepositoryStore; from coffer.quota import QuotaStore; db='sqlite:////var/lib/coffer/coffer.sqlite'; RepositoryStore(db).create('${project_id}', 'stage2'); QuotaStore(db).set_limit('${project_id}', 1048576)"

podman run --detach --name "${REGISTRY_CONTAINER}" \
    --network "${NETWORK}" --network-alias "${REGISTRY_CONTAINER}" \
    --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
    --env OTEL_TRACES_EXPORTER=none \
    --health-cmd 'healthcheck_listen registry 8789' \
    --health-interval 1s --health-retries 30 --health-timeout 2s \
    --volume "${fixture}/registry:/var/lib/kolla/config_files:ro" \
    --volume "${REGISTRY_VOLUME}:/var/lib/registry" \
    "${REGISTRY_IMAGE}" >/dev/null

podman run --detach --name "${CONTROL_CONTAINER}" \
    --network "${NETWORK}" --network-alias "${CONTROL_CONTAINER}" \
    --publish "127.0.0.1:${API_PORT}:8787" \
    --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
    --health-cmd 'healthcheck_listen coffer-api 8787' \
    --health-interval 1s --health-retries 30 --health-timeout 2s \
    --volume "${fixture}/api:/var/lib/kolla/config_files:ro" \
    --volume "${DATABASE_VOLUME}:/var/lib/coffer" \
    "${COFFER_IMAGE}" >/dev/null

podman run --detach --name "${EDGE_CONTAINER}" \
    --network "${NETWORK}" --network-alias "${EDGE_CONTAINER}" \
    --publish "127.0.0.1:${EDGE_PORT}:8788" \
    --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
    --health-cmd 'healthcheck_listen coffer-edge 8788' \
    --health-interval 1s --health-retries 30 --health-timeout 2s \
    --volume "${fixture}/edge:/var/lib/kolla/config_files:ro" \
    --volume "${DATABASE_VOLUME}:/var/lib/coffer" \
    "${COFFER_IMAGE}" >/dev/null

phase="initial service health"
wait_for_health "${REGISTRY_CONTAINER}"
wait_for_health "${CONTROL_CONTAINER}"
wait_for_health "${EDGE_CONTAINER}"
phase="initial API readiness"
wait_for_api
phase="initial edge challenge"
wait_for_edge

phase="runtime contract assertions"
assert_equal "api image user" "coffer" \
    "$(podman inspect --format '{{.Config.User}}' "${CONTROL_CONTAINER}")"
assert_equal "edge image user" "coffer" \
    "$(podman inspect --format '{{.Config.User}}' "${EDGE_CONTAINER}")"
assert_equal "registry image user" "registry" \
    "$(podman inspect --format '{{.Config.User}}' "${REGISTRY_CONTAINER}")"
assert_equal "api runtime uid" "53002" \
    "$(podman exec "${CONTROL_CONTAINER}" id -u)"
assert_equal "edge runtime uid" "53002" \
    "$(podman exec "${EDGE_CONTAINER}" id -u)"
assert_equal "registry runtime uid" "53003" \
    "$(podman exec "${REGISTRY_CONTAINER}" id -u)"
assert_equal "api config owner and mode" "coffer:coffer:600" \
    "$(podman exec "${CONTROL_CONTAINER}" stat -c '%U:%G:%a' /etc/coffer/coffer.conf)"
assert_equal "edge config owner and mode" "coffer:coffer:600" \
    "$(podman exec "${EDGE_CONTAINER}" stat -c '%U:%G:%a' /etc/coffer/coffer.conf)"
assert_equal "registry config owner and mode" "registry:registry:600" \
    "$(podman exec "${REGISTRY_CONTAINER}" stat -c '%U:%G:%a' /etc/coffer-registry/config.yml)"
assert_container_test "api config.json is read-only" \
    "${CONTROL_CONTAINER}" ! -w /var/lib/kolla/config_files/config.json
assert_container_test "edge config.json is read-only" \
    "${EDGE_CONTAINER}" ! -w /var/lib/kolla/config_files/config.json
assert_container_test "registry config.json is read-only" \
    "${REGISTRY_CONTAINER}" ! -w /var/lib/kolla/config_files/config.json
assert_container_test "custom CA is installed" "${CONTROL_CONTAINER}" \
    -f /usr/local/share/ca-certificates/kolla-customca-stage2-ca.crt
assert_equal "registry host port exposure" "" \
    "$(podman port "${REGISTRY_CONTAINER}")"

podman run --name "${RECONCILE_CONTAINER}" --rm \
    --network "${NETWORK}" \
    --env KOLLA_CONFIG_STRATEGY=COPY_ALWAYS \
    --volume "${fixture}/reconcile:/var/lib/kolla/config_files:ro" \
    --volume "${DATABASE_VOLUME}:/var/lib/coffer" \
    "${COFFER_IMAGE}"

phase="OCI push and pull"
edge_base="https://127.0.0.1:${EDGE_PORT}"
repository="$(jq -r .repository "${fixture}/artifact.json")"
blob_digest="$(jq -r .blob_digest "${fixture}/artifact.json")"
manifest_digest="$(jq -r .manifest_digest "${fixture}/artifact.json")"
fixture_blob_size="$(wc -c <"${fixture}/blob.json" | tr -d '[:space:]')"
assert_equal "fixture blob digest" "${blob_digest}" \
    "sha256:$(shasum -a 256 "${fixture}/blob.json" | awk '{print $1}')"
upload_headers="${fixture}/upload.headers"
umask 077
upload_status="$(curl --disable --silent --show-error \
    --config "${fixture}/curl-auth.conf" \
    --cacert "${fixture}/ca.crt" \
    --request POST \
    --dump-header "${upload_headers}" \
    --output /dev/null --write-out '%{http_code}' \
    "${edge_base}/v2/${repository}/blobs/uploads/")"
[[ "${upload_status}" == "202" ]]
upload_location="$(awk 'BEGIN {IGNORECASE=1} /^Location:/ {
    sub(/^[^:]+:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit
}' "${upload_headers}")"
[[ "${upload_location}" == /v2/* ]]
separator="?"
if [[ "${upload_location}" == *"?"* ]]; then
    separator="&"
fi
blob_result="$(curl --disable --silent --show-error \
    --config "${fixture}/curl-auth.conf" \
    --cacert "${fixture}/ca.crt" \
    --request PUT \
    --header 'Content-Type: application/octet-stream' \
    --data-binary "@${fixture}/blob.json" \
    --output /dev/null --write-out '%{http_code} %{size_upload}' \
    "${edge_base}${upload_location}${separator}digest=${blob_digest}")"
read -r blob_status uploaded_size <<<"${blob_result}"
assert_equal "curl blob upload size" "${fixture_blob_size}" "${uploaded_size}"
[[ "${blob_status}" == "201" ]]

manifest_status="$(curl --disable --silent --show-error \
    --config "${fixture}/curl-auth.conf" \
    --cacert "${fixture}/ca.crt" \
    --request PUT \
    --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
    --data-binary "@${fixture}/manifest.json" \
    --output /dev/null --write-out '%{http_code}' \
    "${edge_base}/v2/${repository}/manifests/stage2")"
[[ "${manifest_status}" == "201" ]]

curl --disable --fail --silent --show-error \
    --config "${fixture}/curl-auth.conf" \
    --cacert "${fixture}/ca.crt" \
    --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
    --output "${fixture}/fetched-manifest.json" \
    "${edge_base}/v2/${repository}/manifests/${manifest_digest}"
[[ "sha256:$(shasum -a 256 "${fixture}/fetched-manifest.json" | awk '{print $1}')" == "${manifest_digest}" ]]

[[ "$(curl --disable --silent --show-error --cacert "${fixture}/ca.crt" \
    --output /dev/null --write-out '%{http_code}' \
    "${edge_base}/healthz")" == "404" ]]

podman restart "${REGISTRY_CONTAINER}" "${CONTROL_CONTAINER}" "${EDGE_CONTAINER}" \
    >/dev/null
phase="post-restart service health"
wait_for_health "${REGISTRY_CONTAINER}"
wait_for_health "${CONTROL_CONTAINER}"
wait_for_health "${EDGE_CONTAINER}"
phase="post-restart API readiness"
wait_for_api
phase="post-restart edge challenge"
wait_for_edge
phase="post-restart bootstrap and digest"
run_bootstrap

curl --disable --fail --silent --show-error \
    --config "${fixture}/curl-auth.conf" \
    --cacert "${fixture}/ca.crt" \
    --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
    --output "${fixture}/fetched-after-restart.json" \
    "${edge_base}/v2/${repository}/manifests/${manifest_digest}"
[[ "sha256:$(shasum -a 256 "${fixture}/fetched-after-restart.json" | awk '{print $1}')" == "${manifest_digest}" ]]

for container in "${CONTROL_CONTAINER}" "${EDGE_CONTAINER}" "${REGISTRY_CONTAINER}"; do
    podman logs "${container}" >>"${fixture}/runtime.log" 2>&1
done
while IFS= read -r forbidden; do
    [[ -z "${forbidden}" ]] && continue
    if grep -F -- "${forbidden}" "${fixture}/runtime.log" >/dev/null; then
        echo "runtime log retained a forbidden fixture value" >&2
        exit 1
    fi
done <"${fixture}/forbidden-values.txt"
if grep -E -- 'Authorization:|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|eyJ[A-Za-z0-9_-]{20,}\.' \
    "${fixture}/runtime.log" >/dev/null; then
    echo "runtime log contains credential-shaped material" >&2
    exit 1
fi

phase="exact cleanup and residue"
remove_exact_runtime
runtime_cleaned=true

for name in \
    "${CONTROL_CONTAINER}" "${EDGE_CONTAINER}" "${REGISTRY_CONTAINER}" \
    "${BOOTSTRAP_CONTAINER}" "${RECONCILE_CONTAINER}"; do
    if podman container exists "${name}"; then
        echo "container residue remains: ${name}" >&2
        exit 1
    fi
done
for name in "${DATABASE_VOLUME}" "${REGISTRY_VOLUME}"; do
    if podman volume exists "${name}"; then
        echo "volume residue remains: ${name}" >&2
        exit 1
    fi
done
if podman network exists "${NETWORK}"; then
    echo "network residue remains: ${NETWORK}" >&2
    exit 1
fi
if podman image exists "${COFFER_IMAGE}" \
    || podman image exists "${REGISTRY_IMAGE}" \
    || podman image exists "${BASE_IMAGE}"; then
    echo "image residue remains" >&2
    exit 1
fi

echo "Kolla runtime Stage 2 verification passed"
