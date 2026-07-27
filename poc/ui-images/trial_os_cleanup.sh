#!/usr/bin/env bash

set -Eeuo pipefail
umask 027

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${ROOT}/poc/ui-images"
WORK="${ROOT}/work/ui-os-cleanup-trial"
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
PROBE_SUMMARY="${ROOT}/work/ui-parent-remediation-probe/evidence/summary.json"
TAG="2026.1-os-cleanup"
PREFIX="coffer-ui-trial-"
HORIZON_PARENT="localhost/${PREFIX}horizon:${TAG}"
SKYLINE_PARENT="localhost/${PREFIX}skyline-console:${TAG}"
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
    printf 'UI OS cleanup trial failed phase=%s line=%s exit=%s\n' \
        "${phase}" "${line}" "${exit_code}" >&2
}

trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

for command_name in docker git jq podman python3; do
    require_command "${command_name}"
done
docker scout version >/dev/null
if [[ -e "${WORK}" ]]; then
    echo "refusing existing UI OS cleanup trial work directory" >&2
    exit 1
fi
for image in "${TRIAL_IMAGES[@]}"; do
    if podman image exists "${image}" 2>/dev/null; then
        echo "refusing pre-existing bounded cleanup image: ${image}" >&2
        exit 1
    fi
done
test -f "${PROBE_SUMMARY}"
test ! -L "${PROBE_SUMMARY}"
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
        echo "unsupported UI OS cleanup trial host: ${runtime_os}" >&2
        exit 1
        ;;
esac
podman info >/dev/null

phase="source, wheel, and scanner capability"
test "$(git -C "${KOLLA_SOURCE}" rev-parse HEAD)" = "${KOLLA_COMMIT}"
test "$(git -C "${HORIZON_SOURCE}" rev-parse HEAD)" = \
    "0a4439556517cf67be0aa949b6551a14e409af75"
test "$(git -C "${SKYLINE_SOURCE}" rev-parse HEAD)" = \
    "c9000cb1be332a213009793598f17a80ce59671e"
test -z "$(git -C "${KOLLA_SOURCE}" status --porcelain)"
test -z "$(git -C "${HORIZON_SOURCE}" status --porcelain)"
test -z "$(git -C "${SKYLINE_SOURCE}" status --porcelain)"
test -x "${KOLLA_BUILD}"

horizon_wheel="${WHEELS}/coffer_horizon-0.1.0-py3-none-any.whl"
skyline_wheel="${WHEELS}/skyline_console-8.0.0+coffer.1-py3-none-any.whl"
cp "${WHEEL_INPUT}/$(basename "${horizon_wheel}")" "${horizon_wheel}"
cp "${WHEEL_INPUT}/$(basename "${skyline_wheel}")" "${skyline_wheel}"
test "$(shasum -a 256 "${horizon_wheel}" | awk '{print $1}')" = \
    "a634543218a14731f50a291c9f38728fe3deab26da5ae8ef0a92a1d10805cdb2"
test "$(shasum -a 256 "${skyline_wheel}" | awk '{print $1}')" = \
    "250013bb4ade737613d3c02d4c09a4b541a2803c86cc6aabea9f2583c54d480b"

docker_scout_version="$(
    docker scout version | awk '/^version:/ {print $2; exit}'
)"
test -n "${docker_scout_version}"
scout_probe_sbom="${WORK}/scout-capability.spdx.json"
scout_probe_sarif="${WORK}/scout-capability.sarif.json"
docker scout sbom --format spdx --output "${scout_probe_sbom}" \
    "fs://${HARNESS}/cleanup_trial.py"
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
        echo "unsupported UI OS cleanup trial architecture: ${runtime_arch}" >&2
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
    --tag "${HORIZON_BEFORE}" "${horizon_context}"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${SKYLINE_PARENT}" \
    --file "${skyline_context}/skyline-console.Containerfile" \
    --tag "${SKYLINE_BEFORE}" "${skyline_context}"

phase="exact OS cleanup derivatives"
cleanup_context="${CONTEXTS}/cleanup"
mkdir -p "${cleanup_context}"
cp "${HARNESS}/os_cleanup.Containerfile" "${cleanup_context}/"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${HORIZON_BEFORE}" \
    --file "${cleanup_context}/os_cleanup.Containerfile" \
    --tag "${HORIZON_AFTER}" "${cleanup_context}"
podman build --pull-never --network none --platform "${platform}" \
    --build-arg "BASE_IMAGE=${SKYLINE_BEFORE}" \
    --file "${cleanup_context}/os_cleanup.Containerfile" \
    --tag "${SKYLINE_AFTER}" "${cleanup_context}"

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

phase="trial provenance, package, and runtime evidence"
python3 "${HARNESS}/collect_cleanup_trial.py" \
    --evidence "${EVIDENCE}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}" \
    --ubuntu-sha256 "${ubuntu_sha}" \
    --kolla-revision "${KOLLA_COMMIT}" \
    --horizon-revision "0a4439556517cf67be0aa949b6551a14e409af75" \
    --skyline-revision "c9000cb1be332a213009793598f17a80ce59671e" \
    --docker-scout-version "${docker_scout_version}" \
    --trivy-version "${trivy_version}" \
    --horizon-before "${HORIZON_BEFORE}" \
    --horizon-after "${HORIZON_AFTER}" \
    --skyline-before "${SKYLINE_BEFORE}" \
    --skyline-after "${SKYLINE_AFTER}"
jq -e --arg architecture "${architecture}" \
    '.architecture == $architecture' "${EVIDENCE}/manifest.json" >/dev/null

phase="two-scanner before and after evidence"
for entry in \
    "horizon-before=${HORIZON_BEFORE}" \
    "horizon-after=${HORIZON_AFTER}" \
    "skyline-before=${SKYLINE_BEFORE}" \
    "skyline-after=${SKYLINE_AFTER}"; do
    key="${entry%%=*}"
    image="${entry#*=}"
    archive="${EVIDENCE}/${key}.tar"
    podman save --format docker-archive --output "${archive}" "${image}"
    (
        cd "${ROOT}"
        docker scout cves --format sarif \
            --output "work/ui-os-cleanup-trial/evidence/${key}.scout.sarif.json" \
            "archive://work/ui-os-cleanup-trial/evidence/${key}.tar"
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

phase="fail-closed cleanup classification"
trial_exit=0
python3 "${HARNESS}/cleanup_trial.py" "${EVIDENCE}" \
    --probe-summary "${PROBE_SUMMARY}" \
    --horizon-wheel "${horizon_wheel}" \
    --skyline-wheel "${skyline_wheel}" || trial_exit=$?
if [[ "${trial_exit}" -ne 3 ]]; then
    exit "${trial_exit}"
fi
jq -e '
    .decision.status == "blocked"
    and .decision.production_candidate == false
    and .decision.os_cleanup_trial_accepted == true
    and .decision.production_containerfile_changed == false
' "${EVIDENCE}/cleanup-trial.json" >/dev/null

echo "UI OS cleanup trial accepted but production remains blocked; evidence=${EVIDENCE}"
