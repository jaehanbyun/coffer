#!/usr/bin/env bash

set -Eeuo pipefail
umask 027

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${ROOT}/poc/ui-images"
WORK="${ROOT}/work/ui-parent-remediation-probe"
EVIDENCE="${WORK}/evidence"
CONTEXTS="${WORK}/contexts"
KOLLA_SOURCE="${ROOT}/work/kolla-2026.1-production"
KOLLA_BUILD="${KOLLA_SOURCE}/.venv/bin/kolla-build"
TAG="2026.1-parent-probe"
PREFIX="coffer-ui-probe-"
HORIZON_PARENT="localhost/${PREFIX}horizon:${TAG}"
SKYLINE_PARENT="localhost/${PREFIX}skyline-console:${TAG}"
podman_machine_started=false
podman_socket=""
phase="initialization"

# shellcheck source=poc/production-images/pins.env
source "${ROOT}/poc/production-images/pins.env"

readonly PROBE_IMAGES=(
    "localhost/${PREFIX}base:${TAG}"
    "localhost/${PREFIX}openstack-base:${TAG}"
    "${HORIZON_PARENT}"
    "localhost/${PREFIX}skyline-base:${TAG}"
    "${SKYLINE_PARENT}"
)

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "required command is unavailable: $1" >&2
        exit 1
    fi
}

remove_exact_images() {
    local image
    for image in "${PROBE_IMAGES[@]}"; do
        podman image rm --force "${image}" >/dev/null 2>&1 || true
    done
}

cleanup() {
    local exit_code=$?
    if podman info >/dev/null 2>&1; then
        remove_exact_images
    fi
    rm -rf -- "${CONTEXTS:?}"
    if [[ "${podman_machine_started}" == true ]]; then
        podman machine stop >/dev/null 2>&1 || true
    fi
    exit "${exit_code}"
}

report_failure() {
    local exit_code="$1"
    local line="$2"
    printf 'UI stock-parent probe failed phase=%s line=%s exit=%s\n' \
        "${phase}" "${line}" "${exit_code}" >&2
}

trap 'report_failure "$?" "${LINENO}"' ERR
trap cleanup EXIT

for command_name in git jq podman python3; do
    require_command "${command_name}"
done
if [[ -e "${WORK}" ]]; then
    echo "refusing existing UI parent probe work directory" >&2
    exit 1
fi
for image in "${PROBE_IMAGES[@]}"; do
    if podman image exists "${image}" 2>/dev/null; then
        echo "refusing pre-existing bounded probe image: ${image}" >&2
        exit 1
    fi
done
mkdir -p "${EVIDENCE}" "${CONTEXTS}"
chmod 700 "${WORK}" "${EVIDENCE}" "${CONTEXTS}"

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
        trap 'kill "${podman_service_pid}" >/dev/null 2>&1 || true; cleanup' EXIT
        for _attempt in {1..100}; do
            [[ -S "${podman_socket}" ]] && break
            sleep 0.1
        done
        test -S "${podman_socket}"
        ;;
    *)
        echo "unsupported UI package-probe host: ${runtime_os}" >&2
        exit 1
        ;;
esac
podman info >/dev/null

phase="source verification"
test "$(git -C "${KOLLA_SOURCE}" rev-parse HEAD)" = "${KOLLA_COMMIT}"
test -z "$(git -C "${KOLLA_SOURCE}" status --porcelain)"
test -x "${KOLLA_BUILD}"

runtime_arch="$(podman info --format '{{.Host.Arch}}')"
case "${runtime_arch}" in
    arm64 | aarch64)
        base_arch="aarch64"
        debian_arch="arm64"
        platform="linux/arm64"
        ubuntu_sha="${UBUNTU_2404_ARM64_SHA256}"
        ;;
    amd64 | x86_64)
        base_arch="x86_64"
        debian_arch="amd64"
        platform="linux/amd64"
        ubuntu_sha="${UBUNTU_2404_AMD64_SHA256}"
        ;;
    *)
        echo "unsupported UI package-probe architecture: ${runtime_arch}" >&2
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
    --work-dir "${CONTEXTS}" \
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

phase="read-only package probes"
for entry in "horizon=${HORIZON_PARENT}" "skyline=${SKYLINE_PARENT}"; do
    surface="${entry%%=*}"
    image="${entry#*=}"
    podman run --rm \
        --network none \
        --read-only \
        --cap-drop all \
        --security-opt no-new-privileges \
        --user 0 \
        --entrypoint python3 \
        --volume \
        "${HARNESS}/package_probe.py:/tmp/coffer-package-probe.py:ro" \
        "${image}" \
        /tmp/coffer-package-probe.py \
        --target linux-libc-dev \
        >"${EVIDENCE}/${surface}.package-probe.json"
    chmod 640 "${EVIDENCE}/${surface}.package-probe.json"
    jq -e '
        .schema == "coffer.ui-parent-package-probe/v1"
        and .target.name == "linux-libc-dev"
        and .purge_simulation.safe_to_apply == false
        and .package_database.dpkg_audit_clean == true
        and .package_database.apt_dependency_check_clean == true
    ' "${EVIDENCE}/${surface}.package-probe.json" >/dev/null
done

phase="cross-surface evidence"
python3 - "${EVIDENCE}" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
documents = {
    surface: json.loads((root / f"{surface}.package-probe.json").read_text())
    for surface in ("horizon", "skyline")
}
if documents["horizon"]["architecture"] != documents["skyline"]["architecture"]:
    raise SystemExit("parent package-probe architectures diverge")
if documents["horizon"]["target"] != documents["skyline"]["target"]:
    raise SystemExit("parent package-probe target evidence diverges")
summary = {
    "schema": "coffer.ui-parent-package-probe-summary/v1",
    "architecture": documents["horizon"]["architecture"],
    "surfaces": {
        surface: {
            "sha256": hashlib.sha256(
                (root / f"{surface}.package-probe.json").read_bytes()
            ).hexdigest()
        }
        for surface in ("horizon", "skyline")
    },
    "target": documents["horizon"]["target"],
    "purge_simulation": documents["horizon"]["purge_simulation"],
    "decision": {
        "safe_to_apply": False,
        "reason": (
            "stock-parent inventory and apt simulation are read-only evidence; "
            "an isolated derivative runtime and rebuild test is still required"
        ),
    },
}
path = root / "summary.json"
path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
path.chmod(0o640)
PY

echo "UI stock-parent package probe completed; evidence=${EVIDENCE}"
