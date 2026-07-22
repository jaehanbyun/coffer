#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
work_directory="${repository_root}/work/quota-reconciliation"
compose=(podman compose --file "${script_dir}/compose.yaml" --project-name coffer-quota-reconciliation)
registry_port="${COFFER_RECONCILIATION_PORT:-55003}"

umask 077

cleanup() {
  "${compose[@]}" logs --no-color >"${work_directory}/registry.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "${work_directory}/quota.sqlite" "${work_directory}/registry.log"
  rmdir "${work_directory}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for command_name in podman uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
podman info >/dev/null

mkdir -p "${work_directory}"
chmod 700 "${work_directory}"
export COFFER_RECONCILIATION_PORT="${registry_port}"
unset COFFER_DATABASE_URL

"${compose[@]}" config --quiet
"${compose[@]}" up --detach registry
container_id="$("${compose[@]}" ps --quiet registry)"
test -n "${container_id}"
for _attempt in $(seq 1 60); do
  status="$(podman inspect "${container_id}" --format '{{.State.Health.Status}}')"
  if test "${status}" = healthy; then
    break
  fi
  if test "${status}" = unhealthy; then
    printf 'Distribution fixture did not become healthy\n' >&2
    exit 1
  fi
  sleep 1
done
test "${status}" = healthy

uv run --project "${repository_root}" python \
  "${script_dir}/verify_distribution_reconciliation.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --database "${work_directory}/quota.sqlite" \
  --repository-root "${repository_root}"

cleanup
trap - EXIT
test -z "$(podman ps --all --quiet --filter label=org.openstack.coffer.poc=quota-reconciliation)"
test -z "$(podman volume ls --quiet --filter label=org.openstack.coffer.poc=quota-reconciliation)"
test -z "$(podman network ls --quiet --filter label=org.openstack.coffer.poc=quota-reconciliation)"
test ! -e "${work_directory}"
printf 'reconciliation cleanup verified: containers=0 volumes=0 networks=0 state=0\n'
