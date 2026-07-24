#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${ROOT}/poc/production-images"
WORK="${ROOT}/work/production-image-remediation"
INPUTS="${WORK}/inputs"
CONTEXTS="${WORK}/contexts"
SOURCE_SNAPSHOT="${WORK}/source"
EVIDENCE="${WORK}/evidence"
KOLLA_SOURCE="${ROOT}/work/kolla-2026.1-production"
KOLLA_BUILD="${KOLLA_SOURCE}/.venv/bin/kolla-build"
IMAGE_TAG="2026.1-candidate"
BASE_IMAGE="localhost/coffer-production-base:${IMAGE_TAG}"
COFFER_IMAGE="localhost/coffer-production-coffer:${IMAGE_TAG}"
REGISTRY_IMAGE="localhost/coffer-production-coffer-registry:${IMAGE_TAG}"
TRIVY_IMAGE="docker.io/aquasec/trivy:${TRIVY_VERSION:-0.72.0}"
KEEP_IMAGES="${COFFER_PRODUCTION_KEEP_IMAGES:-false}"
phase="initialization"

# shellcheck source=poc/production-images/pins.env
source "${HARNESS}/pins.env"
TRIVY_IMAGE="docker.io/aquasec/trivy:${TRIVY_VERSION}@sha256:${TRIVY_INDEX_SHA256}"

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "required command is unavailable: $1" >&2
        exit 1
    fi
}

remove_exact_images() {
    local image
    for image in \
        "${COFFER_IMAGE}" "${REGISTRY_IMAGE}" \
        "${BASE_IMAGE}"; do
        podman image rm --force "${image}" >/dev/null 2>&1 || true
    done
}

cleanup() {
    local exit_code=$?
    if podman info >/dev/null 2>&1 && [[ "${KEEP_IMAGES}" != "true" ]]; then
        remove_exact_images
    fi
    exit "${exit_code}"
}

report_failure() {
    local exit_code="$1"
    local line="$2"
    printf 'Production image qualification failed phase=%s line=%s exit=%s\n' \
        "${phase}" "${line}" "${exit_code}" >&2
}

trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

for command_name in curl docker git gh go jq podman python3 tar uv; do
    require_command "${command_name}"
done
if command -v sha256sum >/dev/null 2>&1; then
    sha256_check=(sha256sum -c -)
elif command -v shasum >/dev/null 2>&1; then
    sha256_check=(shasum -a 256 -c -)
else
    echo "required SHA-256 checker is unavailable" >&2
    exit 1
fi
docker scout version >/dev/null
if [[ "${KEEP_IMAGES}" != "true" && "${KEEP_IMAGES}" != "false" ]]; then
    echo "COFFER_PRODUCTION_KEEP_IMAGES must be true or false" >&2
    exit 1
fi
if [[ "$(podman machine inspect --format '{{.State}}')" != "running" ]]; then
    echo "the retained Podman machine must already be running in a persistent PTY" >&2
    exit 1
fi
podman info >/dev/null
if [[ ! -d "${KOLLA_SOURCE}/.git" ]]; then
    git clone --filter=blob:none --branch stable/2026.1 --single-branch \
        https://opendev.org/openstack/kolla "${KOLLA_SOURCE}"
    git -C "${KOLLA_SOURCE}" checkout --detach "${KOLLA_COMMIT}"
fi
if [[ ! -x "${KOLLA_BUILD}" ]]; then
    uv venv --python 3.13 "${KOLLA_SOURCE}/.venv"
    uv pip install --python "${KOLLA_SOURCE}/.venv/bin/python" "${KOLLA_SOURCE}"
fi
if ! "${KOLLA_SOURCE}/.venv/bin/python" -c 'import podman' >/dev/null 2>&1; then
    uv pip install --python "${KOLLA_SOURCE}/.venv/bin/python" \
        "podman==${PODMAN_PY_VERSION}"
fi

runtime_arch="$(podman info --format '{{.Host.Arch}}')"
case "${runtime_arch}" in
    arm64 | aarch64)
        base_arch="aarch64"
        debian_arch="arm64"
        platform="linux/arm64"
        ubuntu_sha="${UBUNTU_2404_ARM64_SHA256}"
        distribution_sha="${DISTRIBUTION_ARM64_SHA256}"
        provenance_sha="${DISTRIBUTION_ARM64_PROVENANCE_SHA256}"
        release_arch="arm64"
        ;;
    amd64 | x86_64)
        base_arch="x86_64"
        debian_arch="amd64"
        platform="linux/amd64"
        ubuntu_sha="${UBUNTU_2404_AMD64_SHA256}"
        distribution_sha="${DISTRIBUTION_AMD64_SHA256}"
        provenance_sha="${DISTRIBUTION_AMD64_PROVENANCE_SHA256}"
        release_arch="amd64"
        ;;
    *)
        echo "unsupported production-candidate architecture: ${runtime_arch}" >&2
        exit 1
        ;;
esac

phase="input verification"
test "$(git -C "${KOLLA_SOURCE}" rev-parse HEAD)" = "${KOLLA_COMMIT}"
test "$(git -C "${ROOT}/work/distribution-v3.1.1" rev-parse HEAD)" = \
    "${DISTRIBUTION_COMMIT}"
cmp -s "${ROOT}/requirements/production-constraints.txt" \
    <(uv export --locked --no-dev --all-extras --no-emit-project \
        --no-hashes --no-header)
mkdir -p "${INPUTS}" "${EVIDENCE}"
release_name="registry_${DISTRIBUTION_VERSION}_linux_${release_arch}.tar.gz"
provenance_name="registry_${DISTRIBUTION_VERSION}_linux_${release_arch}.provenance.json"
gh release download "v${DISTRIBUTION_VERSION}" \
    --repo distribution/distribution \
    --pattern "${release_name}" \
    --pattern "${provenance_name}" \
    --dir "${INPUTS}" --clobber
printf '%s  %s\n' "${distribution_sha}" "${INPUTS}/${release_name}" \
    | "${sha256_check[@]}"
printf '%s  %s\n' "${provenance_sha}" "${INPUTS}/${provenance_name}" \
    | "${sha256_check[@]}"
jq -e \
    --arg name "${release_name}" \
    --arg digest "${distribution_sha}" \
    '.subject[] | select(.name == $name and .digest.sha256 == $digest)' \
    "${INPUTS}/${provenance_name}" >/dev/null
tar -xzf "${INPUTS}/${release_name}" -C "${INPUTS}" registry
touch "${EVIDENCE}/release-provenance.passed"

phase="source snapshot"
if [[ -e "${SOURCE_SNAPSHOT}" || -e "${CONTEXTS}" ]]; then
    rm -rf -- "${SOURCE_SNAPSHOT}" "${CONTEXTS}"
fi
mkdir -p "${SOURCE_SNAPSHOT}" "${CONTEXTS}"
git -C "${ROOT}" ls-files -co --exclude-standard -z \
    | tar -C "${ROOT}" --null -T - -cf - \
    | tar -xf - -C "${SOURCE_SNAPSHOT}"

phase="Kolla candidate image build"
remove_exact_images
podman_socket="$(podman machine inspect \
    --format '{{.ConnectionInfo.PodmanSocket.Path}}')"
test -S "${podman_socket}"
"${KOLLA_BUILD}" \
    --engine podman \
    --podman_base_url "unix://${podman_socket}" \
    --config-file "${HARNESS}/kolla-build.conf" \
    --docker-dir "${ROOT}/docker" \
    --locals-base "${SOURCE_SNAPSHOT}" \
    --work-dir "${CONTEXTS}" \
    --base ubuntu \
    --base-image ubuntu \
    --base-tag "24.04@sha256:${ubuntu_sha}" \
    --base-arch "${base_arch}" \
    --debian-arch "${debian_arch}" \
    --platform "${platform}" \
    --openstack-release 2026.1 \
    --namespace localhost \
    --image-name-prefix coffer-production- \
    --tag "${IMAGE_TAG}" \
    --threads 1 \
    '^(coffer|coffer-registry)$'

phase="candidate runtime contract"
COFFER_RUNTIME_WORK="${WORK}/runtime" \
COFFER_RUNTIME_BASE_IMAGE="${BASE_IMAGE}" \
COFFER_RUNTIME_COFFER_IMAGE="${COFFER_IMAGE}" \
COFFER_RUNTIME_REGISTRY_IMAGE="${REGISTRY_IMAGE}" \
COFFER_RUNTIME_BUILD_IMAGES=false \
COFFER_RUNTIME_REMOVE_IMAGES=false \
COFFER_RUNTIME_MANAGE_MACHINE=false \
    "${ROOT}/poc/kolla-runtime/verify.sh" \
    >"${EVIDENCE}/runtime-contract.log" 2>&1
touch "${EVIDENCE}/runtime-contract.passed"
cp "${WORK}/runtime/evidence/"* "${EVIDENCE}/"

phase="Trivy qualification"
podman save --format docker-archive --output "${EVIDENCE}/coffer-image.tar" \
    "${COFFER_IMAGE}"
podman save --format docker-archive --output "${EVIDENCE}/registry-image.tar" \
    "${REGISTRY_IMAGE}"
for image_name in coffer registry; do
    podman run --rm \
        --volume "${EVIDENCE}:/evidence:ro" \
        "${TRIVY_IMAGE}" image \
        --scanners vuln,secret \
        --format json \
        --input "/evidence/${image_name}-image.tar" \
        >"${EVIDENCE}/${image_name}.trivy.json"
done

phase="Distribution reachability qualification"
mkdir -p "${WORK}/bin"
GOBIN="${WORK}/bin" go install \
    "golang.org/x/vuln/cmd/govulncheck@${GOVULNCHECK_VERSION}"
if (
    cd "${ROOT}/work/distribution-v3.1.1"
    "${WORK}/bin/govulncheck" -mode=source ./...
) >"${EVIDENCE}/distribution-source.govulncheck.txt"; then
    source_status=0
else
    source_status=$?
fi
if "${WORK}/bin/govulncheck" \
    -mode=binary "${INPUTS}/registry" \
    >"${EVIDENCE}/distribution-binary.govulncheck.txt"; then
    binary_status=0
else
    binary_status=$?
fi
test "${source_status}" -eq 3
test "${binary_status}" -eq 3

phase="fail-closed decision"
if uv run python "${HARNESS}/verify_evidence.py" "${EVIDENCE}"; then
    qualification_status=0
else
    qualification_status=$?
fi
test "${qualification_status}" -eq 3
echo "Production image qualification is correctly blocked; see ${EVIDENCE}/qualification.json"
