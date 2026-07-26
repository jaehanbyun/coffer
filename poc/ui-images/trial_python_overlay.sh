#!/usr/bin/env bash

set -Eeuo pipefail
umask 027

if [[ "$#" -gt 1 ]]; then
    echo "usage: trial_python_overlay.sh [target-key]" >&2
    exit 1
fi
TARGET_KEY="${1:-mako}"
if [[ ! "${TARGET_KEY}" =~ ^[a-z][a-z0-9-]{1,31}$ ]]; then
    echo "invalid Python overlay target key" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${ROOT}/poc/ui-images"
TARGET_MANIFEST="${HARNESS}/python_targets.json"
WORK="${ROOT}/work/ui-python-overlay-trial-${TARGET_KEY}"
EVIDENCE="${WORK}/evidence"
CONTEXTS="${WORK}/contexts"
WHEELS="${WORK}/wheels"
TRIVY_CACHE="${WORK}/trivy-cache"
SCOUT_CACHE="${WORK}/scout-cache"
KOLLA_SOURCE="${ROOT}/work/kolla-2026.1-production"
KOLLA_BUILD="${KOLLA_SOURCE}/.venv/bin/kolla-build"
HORIZON_SOURCE="${ROOT}/work/horizon-25.7.3"
SKYLINE_SOURCE="${ROOT}/work/skyline-console-2026.1"
WHEEL_INPUT="${ROOT}/work/ui-image-qualification/wheels"
OS_CLEANUP_RESULT="${ROOT}/work/ui-os-cleanup-trial/evidence/cleanup-trial.json"
OS_CLEANUP_INVENTORIES="${ROOT}/work/ui-os-cleanup-trial/evidence/inventories.json"
REMEDIATION_RESULT="${ROOT}/work/ui-image-qualification/evidence/remediation.json"
TARGET_WHEEL_NAME=""
TARGET_WHEEL_URL=""
TARGET_WHEEL_SHA256=""
TARGET_DISPLAY_NAME=""
TARGET_TO_VERSION=""
TARGET_TRIAL_LABEL=""
TARGET_SURFACES=()
TAG="2026.1-python-overlay"
PREFIX="coffer-ui-python-trial-"
HORIZON_PARENT="localhost/${PREFIX}horizon:${TAG}"
SKYLINE_PARENT="localhost/${PREFIX}skyline-console:${TAG}"
HORIZON_COFFER="localhost/${PREFIX}horizon-coffer:${TAG}"
SKYLINE_COFFER="localhost/${PREFIX}skyline-coffer:${TAG}"
HORIZON_BEFORE="localhost/${PREFIX}horizon-before:${TAG}"
HORIZON_AFTER="localhost/${PREFIX}horizon-after:${TAG}"
SKYLINE_BEFORE="localhost/${PREFIX}skyline-before:${TAG}"
SKYLINE_AFTER="localhost/${PREFIX}skyline-after:${TAG}"
podman_machine_started=false
podman_service_pid=""
podman_socket=""
phase="initialization"
TRIVY_IMAGE=""

# shellcheck source=poc/production-images/pins.env
source "${ROOT}/poc/production-images/pins.env"
TRIVY_IMAGE="docker.io/aquasec/trivy:${TRIVY_VERSION}@sha256:${TRIVY_INDEX_SHA256}"

readonly TRIAL_IMAGES=(
    "localhost/${PREFIX}base:${TAG}"
    "localhost/${PREFIX}openstack-base:${TAG}"
    "${HORIZON_PARENT}"
    "localhost/${PREFIX}skyline-base:${TAG}"
    "${SKYLINE_PARENT}"
    "${HORIZON_COFFER}"
    "${SKYLINE_COFFER}"
    "${HORIZON_BEFORE}"
    "${HORIZON_AFTER}"
    "${SKYLINE_BEFORE}"
    "${SKYLINE_AFTER}"
)

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "required command is unavailable: $1" >&2
        exit 1
    fi
}

remove_exact_images() {
    local image
    for image in "${TRIAL_IMAGES[@]}"; do
        podman image rm --force "${image}" >/dev/null 2>&1 || true
    done
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
    if podman info >/dev/null 2>&1; then
        remove_exact_images
    fi
    stop_native_podman_service
    rm -rf -- \
        "${CONTEXTS:?}" "${WHEELS:?}" "${TRIVY_CACHE:?}" "${SCOUT_CACHE:?}"
    find "${EVIDENCE}" -maxdepth 1 -type f -name '*.tar' -delete \
        >/dev/null 2>&1 || true
    if [[ "${podman_machine_started}" == true ]]; then
        podman machine stop >/dev/null 2>&1 || true
    fi
    exit "${exit_code}"
}

report_failure() {
    local exit_code="$1"
    local line="$2"
    printf 'UI Python overlay trial failed phase=%s line=%s exit=%s\n' \
        "${phase}" "${line}" "${exit_code}" >&2
}

trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

for command_name in curl docker git jq podman python3 shasum; do
    require_command "${command_name}"
done
test -f "${TARGET_MANIFEST}"
test ! -L "${TARGET_MANIFEST}"
TARGET_WHEEL_NAME="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].wheel_filename' "${TARGET_MANIFEST}"
)"
TARGET_WHEEL_URL="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].wheel_url' "${TARGET_MANIFEST}"
)"
TARGET_WHEEL_SHA256="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].wheel_sha256' "${TARGET_MANIFEST}"
)"
TARGET_DISPLAY_NAME="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].display_name' "${TARGET_MANIFEST}"
)"
TARGET_TO_VERSION="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].to_version' "${TARGET_MANIFEST}"
)"
TARGET_TRIAL_LABEL="$(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].trial_label' "${TARGET_MANIFEST}"
)"
TARGET_KEY="${TARGET_KEY}" TARGET_MANIFEST="${TARGET_MANIFEST}" \
    PYTHONPATH="${HARNESS}" python3 -c \
    'import os; from pathlib import Path; from python_target import load_target; load_target(Path(os.environ["TARGET_MANIFEST"]), os.environ["TARGET_KEY"])'
while IFS= read -r target_surface; do
    TARGET_SURFACES+=("${target_surface}")
done < <(
    jq -er --arg target "${TARGET_KEY}" \
        '.targets[$target].surfaces[]' "${TARGET_MANIFEST}"
)
test "${#TARGET_SURFACES[@]}" -gt 0
docker scout version >/dev/null
if [[ -e "${WORK}" ]]; then
    echo "refusing existing UI Python overlay trial work directory" >&2
    exit 1
fi
for image in "${TRIAL_IMAGES[@]}"; do
    if podman image exists "${image}" 2>/dev/null; then
        echo "refusing pre-existing bounded Python trial image: ${image}" >&2
        exit 1
    fi
done
for input in \
    "${OS_CLEANUP_RESULT}" "${OS_CLEANUP_INVENTORIES}" "${REMEDIATION_RESULT}"; do
    test -f "${input}"
    test ! -L "${input}"
done
mkdir -p \
    "${EVIDENCE}" "${CONTEXTS}" "${WHEELS}" \
    "${TRIVY_CACHE}" "${SCOUT_CACHE}"
chmod 700 \
    "${WORK}" "${EVIDENCE}" "${CONTEXTS}" "${WHEELS}" \
    "${TRIVY_CACHE}" "${SCOUT_CACHE}"
export DOCKER_SCOUT_CACHE_DIR="${SCOUT_CACHE}"

runtime_os="$(uname -s)"
case "${runtime_os}" in
    Darwin)
        machine_state="$(podman machine inspect --format '{{.State}}')"
        if [[ "${machine_state}" != "running" ]]; then
            phase="Podman machine start"
            podman machine start
            podman_machine_started=true
        fi
        podman_socket="$(
            podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}'
        )"
        test -S "${podman_socket}"
        ;;
    Linux)
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
        test -S "${podman_socket}"
        ;;
    *)
        echo "unsupported UI Python overlay trial host: ${runtime_os}" >&2
        exit 1
        ;;
esac
podman info >/dev/null

phase="source, wheel, baseline, and scanner capability"
test "$(git -C "${KOLLA_SOURCE}" rev-parse HEAD)" = "${KOLLA_COMMIT}"
test "$(git -C "${HORIZON_SOURCE}" rev-parse HEAD)" = \
    "0a4439556517cf67be0aa949b6551a14e409af75"
test "$(git -C "${SKYLINE_SOURCE}" rev-parse HEAD)" = \
    "c9000cb1be332a213009793598f17a80ce59671e"
test -z "$(git -C "${KOLLA_SOURCE}" status --porcelain)"
test -z "$(git -C "${HORIZON_SOURCE}" status --porcelain)"
test -z "$(git -C "${SKYLINE_SOURCE}" status --porcelain)"
test -x "${KOLLA_BUILD}"
test "$(shasum -a 256 "${OS_CLEANUP_RESULT}" | awk '{print $1}')" = \
    "a8da7856f955f25866a0b9fbe9214d34863a502714a1624ac2ae66ce6caac2d3"
test "$(shasum -a 256 "${OS_CLEANUP_INVENTORIES}" | awk '{print $1}')" = \
    "cce5364a6a2202ae822b8510cb0b4339afef1133d3f8f0affacb75e28cf721db"
test "$(shasum -a 256 "${REMEDIATION_RESULT}" | awk '{print $1}')" = \
    "9ecde6e3b6e2d484bd27fa05cf6c1b26e81077a3e3154a64ebf4902863fa0941"

horizon_wheel="${WHEELS}/coffer_horizon-0.1.0-py3-none-any.whl"
skyline_wheel="${WHEELS}/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
target_wheel="${WHEELS}/${TARGET_WHEEL_NAME}"
cp "${WHEEL_INPUT}/$(basename "${horizon_wheel}")" "${horizon_wheel}"
cp "${WHEEL_INPUT}/$(basename "${skyline_wheel}")" "${skyline_wheel}"
test "$(shasum -a 256 "${horizon_wheel}" | awk '{print $1}')" = \
    "33f0d950818f2d18d9ef6b5e3766445e1e867f39d4bc83a2c2739227b0bee957"
test "$(shasum -a 256 "${skyline_wheel}" | awk '{print $1}')" = \
    "8df1ca2aff8ee05766ba963e3e3a746b8d40a8051591afcf3a526464faa8a034"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
    --output "${target_wheel}" "${TARGET_WHEEL_URL}"
test "$(shasum -a 256 "${target_wheel}" | awk '{print $1}')" = \
    "${TARGET_WHEEL_SHA256}"

docker_scout_version="$(
    docker scout version | awk '/^version:/ {print $2; exit}'
)"
test -n "${docker_scout_version}"
scout_probe_sbom="${WORK}/scout-capability.spdx.json"
scout_probe_sarif="${WORK}/scout-capability.sarif.json"
docker scout sbom --format spdx --output "${scout_probe_sbom}" \
    "fs://${HARNESS}/python_trial.py"
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
        echo "unsupported UI Python overlay architecture: ${runtime_arch}" >&2
        exit 1
        ;;
esac

phase="stock Kolla parent build"
"${KOLLA_BUILD}" \
    --engine podman \
    --podman_base_url "unix://${podman_socket}" \
    --config-file "${HARNESS}/kolla-build.conf" \
    --docker-dir "${KOLLA_SOURCE}/docker" \
    --locals-base "${ROOT}" \
    --work-dir "${CONTEXTS}/kolla" \
    --base ubuntu \
    --base-image ubuntu \
    --base-tag "24.04@sha256:${ubuntu_sha}" \
    --base-arch "${base_arch}" \
    --debian-arch "${debian_arch}" \
    --platform "${platform}" \
    --openstack-release 2026.1 \
    --namespace localhost \
    --image-name-prefix "${PREFIX}" \
    --tag "${TAG}" \
    --threads 1 \
    '^(horizon|skyline-console)$'
podman image exists "${HORIZON_PARENT}"
podman image exists "${SKYLINE_PARENT}"

phase="post-Coffer images"
horizon_context="${CONTEXTS}/horizon"
skyline_context="${CONTEXTS}/skyline"
mkdir -p "${horizon_context}" "${skyline_context}"
cp "${ROOT}/ui/images/horizon.Containerfile" \
    "${ROOT}/ui/images/install_horizon.py" \
    "${horizon_wheel}" "${horizon_context}/"
cp "${ROOT}/ui/images/skyline-console.Containerfile" \
    "${skyline_wheel}" "${skyline_context}/"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${HORIZON_PARENT}" \
    --file "${horizon_context}/horizon.Containerfile" \
    --tag "${HORIZON_COFFER}" "${horizon_context}"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${SKYLINE_PARENT}" \
    --file "${skyline_context}/skyline-console.Containerfile" \
    --tag "${SKYLINE_COFFER}" "${skyline_context}"

phase="accepted OS cleanup baseline derivatives"
cleanup_context="${CONTEXTS}/cleanup"
mkdir -p "${cleanup_context}"
cp "${HARNESS}/os_cleanup.Containerfile" "${cleanup_context}/"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${HORIZON_COFFER}" \
    --file "${cleanup_context}/os_cleanup.Containerfile" \
    --tag "${HORIZON_BEFORE}" "${cleanup_context}"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${SKYLINE_COFFER}" \
    --file "${cleanup_context}/os_cleanup.Containerfile" \
    --tag "${SKYLINE_BEFORE}" "${cleanup_context}"

phase="fixed ${TARGET_DISPLAY_NAME} overlay derivatives"
overlay_context="${CONTEXTS}/python-overlay"
mkdir -p "${overlay_context}"
cp \
    "${HARNESS}/python_overlay.Containerfile" \
    "${HARNESS}/python_target.py" \
    "${TARGET_MANIFEST}" \
    "${overlay_context}/"
cp "${target_wheel}" "${overlay_context}/target.whl"
for target_surface in "${TARGET_SURFACES[@]}"; do
    case "${target_surface}" in
        horizon)
            surface_before="${HORIZON_BEFORE}"
            surface_after="${HORIZON_AFTER}"
            ;;
        skyline)
            surface_before="${SKYLINE_BEFORE}"
            surface_after="${SKYLINE_AFTER}"
            ;;
        *)
            echo "unsupported Python overlay target surface" >&2
            exit 1
            ;;
    esac
    podman build --pull-never --network none --platform "${platform}" \
        --build-arg "BASE_IMAGE=${surface_before}" \
        --build-arg "TARGET_KEY=${TARGET_KEY}" \
        --build-arg "TARGET_LABEL=${TARGET_TRIAL_LABEL}" \
        --build-arg "TARGET_WHEEL_FILENAME=${TARGET_WHEEL_NAME}" \
        --file "${overlay_context}/python_overlay.Containerfile" \
        --tag "${surface_after}" "${overlay_context}"
done

phase="Trivy acquisition"
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

phase="trial provenance, OS, Python, and UI runtime evidence"
collection_args=(
    --evidence "${EVIDENCE}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}" \
    --target-wheel "${target_wheel}" \
    --target-manifest "${TARGET_MANIFEST}" \
    --target "${TARGET_KEY}" \
    --baseline-result "${OS_CLEANUP_RESULT}" \
    --baseline-inventories "${OS_CLEANUP_INVENTORIES}" \
    --remediation-result "${REMEDIATION_RESULT}" \
    --ubuntu-sha256 "${ubuntu_sha}" \
    --kolla-revision "${KOLLA_COMMIT}" \
    --horizon-revision "0a4439556517cf67be0aa949b6551a14e409af75" \
    --skyline-revision "c9000cb1be332a213009793598f17a80ce59671e" \
    --docker-scout-version "${docker_scout_version}" \
    --trivy-version "${trivy_version}"
)
scan_entries=()
for target_surface in "${TARGET_SURFACES[@]}"; do
    case "${target_surface}" in
        horizon)
            collection_args+=(
                --horizon-before "${HORIZON_BEFORE}"
                --horizon-after "${HORIZON_AFTER}"
            )
            scan_entries+=(
                "horizon-before=${HORIZON_BEFORE}"
                "horizon-after=${HORIZON_AFTER}"
            )
            ;;
        skyline)
            collection_args+=(
                --skyline-before "${SKYLINE_BEFORE}"
                --skyline-after "${SKYLINE_AFTER}"
            )
            scan_entries+=(
                "skyline-before=${SKYLINE_BEFORE}"
                "skyline-after=${SKYLINE_AFTER}"
            )
            ;;
    esac
done
python3 "${HARNESS}/collect_python_trial.py" "${collection_args[@]}"
jq -e --arg architecture "${architecture}" \
    '.architecture == $architecture' "${EVIDENCE}/manifest.json" >/dev/null

phase="two-scanner before and after evidence"
for entry in "${scan_entries[@]}"; do
    key="${entry%%=*}"
    image="${entry#*=}"
    archive="${EVIDENCE}/${key}.tar"
    podman save --format docker-archive --output "${archive}" "${image}"
    (
        cd "${ROOT}"
        docker scout cves --format sarif \
            --output "work/ui-python-overlay-trial-${TARGET_KEY}/evidence/${key}.scout.sarif.json" \
            "archive://work/ui-python-overlay-trial-${TARGET_KEY}/evidence/${key}.tar"
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

phase="fail-closed Python compatibility classification"
trial_exit=0
python3 "${HARNESS}/python_trial.py" "${EVIDENCE}" \
    --baseline-result "${OS_CLEANUP_RESULT}" \
    --baseline-inventories "${OS_CLEANUP_INVENTORIES}" \
    --remediation-result "${REMEDIATION_RESULT}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}" \
    --target-wheel "${target_wheel}" \
    --target-manifest "${TARGET_MANIFEST}" \
    --target "${TARGET_KEY}" || trial_exit=$?
if [[ "${trial_exit}" -ne 3 ]]; then
    exit "${trial_exit}"
fi
jq -e --arg target "${TARGET_DISPLAY_NAME}==${TARGET_TO_VERSION}" '
    .decision.status == "blocked"
    and .decision.production_candidate == false
    and .decision.python_overlay_trial_accepted == true
    and .decision.target == $target
    and .decision.production_containerfile_changed == false
' "${EVIDENCE}/python-trial.json" >/dev/null

echo "UI ${TARGET_DISPLAY_NAME} overlay trial accepted but production remains blocked; evidence=${EVIDENCE}"
