#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd)"
source_dir="${repository_root}/work/distribution-v3.1.1"
distribution_commit="9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
registry_image="docker.io/library/registry:3.1.1@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
go_image="docker.io/library/golang:1.25.9-alpine3.23@sha256:5caaf1cca9dc351e13deafbc3879fd4754801acba8653fa9540cea125d01a71f"
govulncheck_version="v1.6.0"

for command_name in docker git; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done

if ! docker scout version >/dev/null 2>&1; then
  printf 'Docker Scout is required for the image severity scan\n' >&2
  exit 1
fi

if test ! -d "${source_dir}/.git"; then
  mkdir -p "$(dirname "${source_dir}")"
  git clone --filter=blob:none --no-checkout \
    https://github.com/distribution/distribution.git "${source_dir}"
  git -C "${source_dir}" fetch --depth 1 origin "${distribution_commit}"
  git -C "${source_dir}" -c advice.detachedHead=false checkout --detach FETCH_HEAD
fi

if test "$(git -C "${source_dir}" rev-parse HEAD)" != "${distribution_commit}"; then
  printf 'unexpected Distribution source commit in %s\n' "${source_dir}" >&2
  exit 1
fi

printf 'Scanning the pinned Linux ARM64 registry image with Docker Scout...\n'
docker scout cves \
  --platform linux/arm64 \
  --only-severity critical,high \
  "registry://${registry_image}"

printf 'Checking reachable Go vulnerabilities against the shipped Go 1.25.9 toolchain...\n'
docker run --rm \
  --platform linux/arm64 \
  --volume "${source_dir}:/src:ro" \
  --workdir /src \
  "${go_image}" \
  sh -ec "go run golang.org/x/vuln/cmd/govulncheck@${govulncheck_version} ./..."
