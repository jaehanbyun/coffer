#!/usr/bin/env bash

set -Eeuo pipefail
umask 027

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${ROOT}/poc/ui-images"
WORK="${ROOT}/work/ui-image-qualification"
EVIDENCE="${WORK}/evidence"
SCOUT_EVIDENCE="work/ui-image-qualification/evidence"
WHEELS="${WORK}/wheels"
CONTEXTS="${WORK}/contexts"
TRIVY_CACHE="${WORK}/trivy-cache"
SCOUT_CACHE="${WORK}/scout-cache"
KOLLA_SOURCE="${ROOT}/work/kolla-2026.1-production"
KOLLA_BUILD="${KOLLA_SOURCE}/.venv/bin/kolla-build"
HORIZON_SOURCE="${ROOT}/work/horizon-25.7.3"
HORIZON_PYTHON="${ROOT}/ui/horizon/.venv/bin/python"
SKYLINE_SOURCE="${ROOT}/work/skyline-console-2026.1"
TAG="2026.1-native-candidate"
HORIZON_PARENT="localhost/coffer-ui-horizon:${TAG}"
HORIZON_CUSTOM="localhost/coffer-ui-horizon-custom:${TAG}"
SKYLINE_PARENT="localhost/coffer-ui-skyline-console:${TAG}"
SKYLINE_CUSTOM="localhost/coffer-ui-skyline-custom:${TAG}"
TRIVY_IMAGE=""
phase="initialization"
podman_service_pid=""
podman_socket=""

# shellcheck source=poc/production-images/pins.env
source "${ROOT}/poc/production-images/pins.env"
TRIVY_IMAGE="docker.io/aquasec/trivy:${TRIVY_VERSION}@sha256:${TRIVY_INDEX_SHA256}"

readonly KOLLA_IMAGES=(
    "localhost/coffer-ui-base:${TAG}"
    "localhost/coffer-ui-openstack-base:${TAG}"
    "${HORIZON_PARENT}"
    "localhost/coffer-ui-skyline-base:${TAG}"
    "${SKYLINE_PARENT}"
)
readonly CUSTOM_IMAGES=("${HORIZON_CUSTOM}" "${SKYLINE_CUSTOM}")

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "required command is unavailable: $1" >&2
        exit 1
    fi
}

remove_exact_images() {
    local image
    for image in "${CUSTOM_IMAGES[@]}" "${KOLLA_IMAGES[@]}"; do
        podman image rm --force "${image}" >/dev/null 2>&1 || true
    done
}

remove_scan_archives() {
    rm -f -- \
        "${EVIDENCE}/horizon-parent.tar" \
        "${EVIDENCE}/horizon-custom.tar" \
        "${EVIDENCE}/skyline-parent.tar" \
        "${EVIDENCE}/skyline-custom.tar"
}

remove_scanner_cache() {
    rm -rf -- "${TRIVY_CACHE:?}"
    rm -rf -- "${SCOUT_CACHE:?}"
}

stop_native_podman_service() {
    if [[ -n "${podman_service_pid}" ]]; then
        kill "${podman_service_pid}" >/dev/null 2>&1 || true
        wait "${podman_service_pid}" >/dev/null 2>&1 || true
        podman_service_pid=""
    fi
}

cleanup() {
    local exit_code=$?
    remove_scan_archives
    remove_scanner_cache
    if podman info >/dev/null 2>&1; then
        remove_exact_images
    fi
    stop_native_podman_service
    exit "${exit_code}"
}

report_failure() {
    local exit_code="$1"
    local line="$2"
    printf 'UI image qualification failed phase=%s line=%s exit=%s\n' \
        "${phase}" "${line}" "${exit_code}" >&2
}

trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

for command_name in docker git jq podman python3 uv; do
    require_command "${command_name}"
done
docker scout version >/dev/null
runtime_os="$(uname -s)"
case "${runtime_os}" in
    Darwin)
        if [[ "$(podman machine inspect --format '{{.State}}')" != "running" ]]; then
            echo "the retained Podman machine must already be running" >&2
            exit 1
        fi
        ;;
    Linux)
        ;;
    *)
        echo "unsupported UI qualification host: ${runtime_os}" >&2
        exit 1
        ;;
esac
podman info >/dev/null
for image in "${CUSTOM_IMAGES[@]}" "${KOLLA_IMAGES[@]}"; do
    if podman image exists "${image}"; then
        echo "refusing pre-existing bounded UI image: ${image}" >&2
        exit 1
    fi
done
if [[ -e "${WORK}" ]]; then
    echo "refusing existing UI qualification work directory" >&2
    exit 1
fi
mkdir -p \
    "${EVIDENCE}" "${WHEELS}" "${CONTEXTS}" \
    "${TRIVY_CACHE}" "${SCOUT_CACHE}"
chmod 700 \
    "${WORK}" "${EVIDENCE}" "${WHEELS}" "${CONTEXTS}" \
    "${TRIVY_CACHE}" "${SCOUT_CACHE}"
export DOCKER_SCOUT_CACHE_DIR="${SCOUT_CACHE}"

phase="Podman API service"
if [[ "${runtime_os}" == "Darwin" ]]; then
    podman_socket="$(podman machine inspect \
        --format '{{.ConnectionInfo.PodmanSocket.Path}}')"
    test -S "${podman_socket}"
else
    podman_socket="${WORK}/podman-api.sock"
    podman system service --time=0 "unix://${podman_socket}" \
        >"${WORK}/podman-service.log" 2>&1 &
    podman_service_pid=$!
    for _attempt in {1..100}; do
        if [[ -S "${podman_socket}" ]]; then
            break
        fi
        if ! kill -0 "${podman_service_pid}" >/dev/null 2>&1; then
            echo "native Podman service exited before readiness" >&2
            exit 1
        fi
        sleep 0.1
    done
    if [[ ! -S "${podman_socket}" ]]; then
        echo "native Podman service did not become ready" >&2
        exit 1
    fi
fi

phase="source and tool verification"
test "$(git -C "${KOLLA_SOURCE}" rev-parse HEAD)" = "${KOLLA_COMMIT}"
test "$(git -C "${HORIZON_SOURCE}" rev-parse HEAD)" = \
    "0a4439556517cf67be0aa949b6551a14e409af75"
test "$(git -C "${SKYLINE_SOURCE}" rev-parse HEAD)" = \
    "c9000cb1be332a213009793598f17a80ce59671e"
test -z "$(git -C "${KOLLA_SOURCE}" status --porcelain)"
test -z "$(git -C "${HORIZON_SOURCE}" status --porcelain)"
test -z "$(git -C "${SKYLINE_SOURCE}" status --porcelain)"
test -x "${KOLLA_BUILD}"
test -x "${HORIZON_PYTHON}"
if ! "${KOLLA_SOURCE}/.venv/bin/python" -c 'import podman' >/dev/null 2>&1; then
    uv pip install --python "${KOLLA_SOURCE}/.venv/bin/python" \
        "podman==${PODMAN_PY_VERSION}"
fi
docker_scout_version="$(
    docker scout version | awk '/^version:/ {print $2; exit}'
)"
test -n "${docker_scout_version}"

phase="Docker Scout CVE capability"
scout_probe_sbom="${WORK}/scout-capability.spdx.json"
scout_probe_sarif="${WORK}/scout-capability.sarif.json"
docker scout sbom --format spdx --output "${scout_probe_sbom}" \
    "fs://${HARNESS}/qualification.py"
docker scout cves --format sarif --output "${scout_probe_sarif}" \
    "sbom://${scout_probe_sbom}"
jq -e '
    .version == "2.1.0"
    and (.runs | type == "array")
    and (.runs | length == 1)
' "${scout_probe_sarif}" >/dev/null
rm -f -- "${scout_probe_sbom}" "${scout_probe_sarif}"

runtime_arch="$(podman info --format '{{.Host.Arch}}')"
case "${runtime_arch}" in
    arm64 | aarch64)
        base_arch="aarch64"
        debian_arch="arm64"
        architecture="arm64"
        platform="linux/arm64"
        ubuntu_sha="${UBUNTU_2404_ARM64_SHA256}"
        ;;
    amd64 | x86_64)
        base_arch="x86_64"
        debian_arch="amd64"
        architecture="amd64"
        platform="linux/amd64"
        ubuntu_sha="${UBUNTU_2404_AMD64_SHA256}"
        ;;
    *)
        echo "unsupported UI image architecture: ${runtime_arch}" >&2
        exit 1
        ;;
esac

phase="wheel materialization"
horizon_wheel="${WHEELS}/coffer_horizon-0.1.0-py3-none-any.whl"
skyline_wheel="${WHEELS}/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
if [[ -n "${COFFER_UI_WHEEL_INPUT_DIR:-}" ]]; then
    input_wheels="${COFFER_UI_WHEEL_INPUT_DIR}"
    if [[ "${input_wheels}" != /* || ! -d "${input_wheels}" \
        || -L "${input_wheels}" ]]; then
        echo "UI wheel input directory is invalid" >&2
        exit 1
    fi
    if [[ "$(find "${input_wheels}" -maxdepth 1 -type f -name '*.whl' | wc -l)" \
        -ne 2 ]]; then
        echo "UI wheel input directory must contain exactly two wheels" >&2
        exit 1
    fi
    for input_wheel in \
        "${input_wheels}/$(basename "${horizon_wheel}")" \
        "${input_wheels}/$(basename "${skyline_wheel}")"; do
        if [[ ! -f "${input_wheel}" || -L "${input_wheel}" ]]; then
            echo "UI wheel input is missing or linked" >&2
            exit 1
        fi
    done
    cp "${input_wheels}/$(basename "${horizon_wheel}")" "${horizon_wheel}"
    cp "${input_wheels}/$(basename "${skyline_wheel}")" "${skyline_wheel}"
else
    uv build --wheel --out-dir "${WHEELS}" "${ROOT}/ui/horizon"
    skyline_source_wheel="$(
        find "${ROOT}/work/skyline-console-coffer-wheel" -maxdepth 1 -type f \
            -name 'skyline_console-8.0.0+coffer.1-py3-none-any.whl' -print
    )"
    test -f "${skyline_source_wheel}"
    cp "${skyline_source_wheel}" "${skyline_wheel}"
fi
test -f "${horizon_wheel}"
test -f "${skyline_wheel}"
"${HORIZON_PYTHON}" "${ROOT}/ui/horizon/verify.py" \
    --horizon-source "${HORIZON_SOURCE}"
python3 "${ROOT}/ui/skyline/verify_build.py" \
    --tree "${ROOT}/work/skyline-console-coffer" \
    --wheel-dir "${ROOT}/work/skyline-console-coffer-wheel"

phase="stock Kolla parent build"
"${KOLLA_BUILD}" \
    --engine podman \
    --podman_base_url "unix://${podman_socket}" \
    --config-file "${HARNESS}/kolla-build.conf" \
    --docker-dir "${KOLLA_SOURCE}/docker" \
    --locals-base "${ROOT}" \
    --work-dir "${CONTEXTS}" \
    --base ubuntu \
    --base-image ubuntu \
    --base-tag "24.04@sha256:${ubuntu_sha}" \
    --base-arch "${base_arch}" \
    --debian-arch "${debian_arch}" \
    --platform "${platform}" \
    --openstack-release 2026.1 \
    --namespace localhost \
    --image-name-prefix coffer-ui- \
    --tag "${TAG}" \
    --threads 1 \
    '^(horizon|skyline-console)$'
podman image exists "${HORIZON_PARENT}"
podman image exists "${SKYLINE_PARENT}"

phase="custom image contexts"
horizon_context="${WORK}/horizon-context"
skyline_context="${WORK}/skyline-context"
mkdir -p "${horizon_context}" "${skyline_context}"
chmod 700 "${horizon_context}" "${skyline_context}"
cp "${ROOT}/ui/images/horizon.Containerfile" \
    "${ROOT}/ui/images/install_horizon.py" \
    "${horizon_wheel}" "${horizon_context}/"
cp "${ROOT}/ui/images/skyline-console.Containerfile" \
    "${skyline_wheel}" "${skyline_context}/"

phase="custom Horizon image build"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${HORIZON_PARENT}" \
    --file "${horizon_context}/horizon.Containerfile" \
    --tag "${HORIZON_CUSTOM}" "${horizon_context}"
phase="custom Skyline image build"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${SKYLINE_PARENT}" \
    --file "${skyline_context}/skyline-console.Containerfile" \
    --tag "${SKYLINE_CUSTOM}" "${skyline_context}"

phase="scanner acquisition"
podman pull "${TRIVY_IMAGE}" >/dev/null
podman run --rm \
    --volume "${TRIVY_CACHE}:/root/.cache/trivy:rw" \
    "${TRIVY_IMAGE}" image --download-db-only
podman run --rm \
    --volume "${TRIVY_CACHE}:/root/.cache/trivy:rw" \
    "${TRIVY_IMAGE}" image --download-java-db-only
trivy_version="$(
    podman run --rm --network none "${TRIVY_IMAGE}" --version \
        | awk '/^Version:/ {print $2; exit}'
)"
test -n "${trivy_version}"

phase="image and runtime evidence"
python3 "${HARNESS}/collect_evidence.py" \
    --evidence "${EVIDENCE}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}" \
    --docker-scout-version "${docker_scout_version}" \
    --trivy-version "${trivy_version}" \
    --horizon-parent "${HORIZON_PARENT}" \
    --horizon-custom "${HORIZON_CUSTOM}" \
    --skyline-parent "${SKYLINE_PARENT}" \
    --skyline-custom "${SKYLINE_CUSTOM}"
jq -e --arg architecture "${architecture}" \
    '.architecture == $architecture' "${EVIDENCE}/manifest.json" >/dev/null

phase="security and SBOM evidence"
for entry in \
    "horizon-parent=${HORIZON_PARENT}" \
    "horizon-custom=${HORIZON_CUSTOM}" \
    "skyline-parent=${SKYLINE_PARENT}" \
    "skyline-custom=${SKYLINE_CUSTOM}"; do
    key="${entry%%=*}"
    image="${entry#*=}"
    archive="${EVIDENCE}/${key}.tar"
    podman save --format docker-archive --output "${archive}" "${image}"
    (
        cd "${ROOT}"
        docker scout sbom --format spdx \
            --output "${SCOUT_EVIDENCE}/${key}.spdx.json" \
            "archive://${SCOUT_EVIDENCE}/${key}.tar"
        docker scout cves --format sarif \
            --output "${SCOUT_EVIDENCE}/${key}.scout.sarif.json" \
            "archive://${SCOUT_EVIDENCE}/${key}.tar"
    )
    podman run --rm --network none \
        --volume "${EVIDENCE}:/evidence:rw" \
        --tmpfs /root/.cache/trivy:rw,noexec,nosuid,nodev \
        --volume "${TRIVY_CACHE}/db:/root/.cache/trivy/db:ro" \
        --volume "${TRIVY_CACHE}/java-db:/root/.cache/trivy/java-db:ro" \
        "${TRIVY_IMAGE}" image \
        --scanners vuln,secret \
        --skip-db-update \
        --skip-java-db-update \
        --offline-scan \
        --format json \
        --output "/evidence/${key}.trivy.json" \
        --input "/evidence/${key}.tar"
    rm -f -- "${archive}"
done

phase="fail-closed qualification"
if python3 "${HARNESS}/qualification.py" "${EVIDENCE}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}"; then
    qualification_status=0
else
    qualification_status=$?
fi
case "${qualification_status}" in
    0)
        echo "UI images qualified on ${architecture}; evidence=${EVIDENCE}"
        ;;
    3)
        echo "UI image qualification is correctly blocked; evidence=${EVIDENCE}"
        ;;
    *)
        exit "${qualification_status}"
        ;;
esac
