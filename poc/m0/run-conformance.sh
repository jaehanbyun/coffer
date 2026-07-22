#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd)"
conformance_image="ghcr.io/opencontainers/distribution-spec/conformance:v1.1.1@sha256:609201aab0905b1e90ded490e5f0dbaadc9a4bef98aca4cd38ff308f588ed27a"
conformance_profile="${COFFER_M0_CONFORMANCE_PROFILE:-full}"

case "${conformance_profile}" in
  full)
    content_discovery=1
    automatic_crossmount=1
    ;;
  supported)
    content_discovery=0
    automatic_crossmount=0
    ;;
  *)
    printf 'unsupported conformance profile: %s\n' "${conformance_profile}" >&2
    exit 2
    ;;
esac

results_dir="${repository_root}/work/m0-conformance-${conformance_profile}"

command -v docker >/dev/null || {
  printf 'missing required command: docker\n' >&2
  exit 1
}

mkdir -p "${results_dir}"
rm -f "${results_dir}/junit.xml" "${results_dir}/report.html"

docker run --rm \
  --platform linux/amd64 \
  --add-host host.docker.internal:host-gateway \
  --volume "${results_dir}:/results" \
  --workdir /results \
  --env OCI_ROOT_URL="http://host.docker.internal:5000" \
  --env OCI_NAMESPACE="coffer/conformance" \
  --env OCI_CROSSMOUNT_NAMESPACE="coffer/conformance-crossmount" \
  --env OCI_TEST_PULL=1 \
  --env OCI_TEST_PUSH=1 \
  --env OCI_TEST_CONTENT_DISCOVERY="${content_discovery}" \
  --env OCI_TEST_CONTENT_MANAGEMENT=1 \
  --env OCI_AUTOMATIC_CROSSMOUNT="${automatic_crossmount}" \
  --env OCI_HIDE_SKIPPED_WORKFLOWS=0 \
  --env OCI_DEBUG=0 \
  --env OCI_DELETE_MANIFEST_BEFORE_BLOBS=1 \
  --env OCI_REPORT_DIR=/results \
  "${conformance_image}"

printf 'Conformance profile: %s\n' "${conformance_profile}"
printf 'Conformance reports: %s\n' "${results_dir}"
