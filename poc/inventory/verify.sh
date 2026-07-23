#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
work_directory="${repository_root}/work/inventory"
compose=(podman compose --file "${script_dir}/compose.yaml" --project-name coffer-inventory)
registry_port="${COFFER_INVENTORY_PORT:-55004}"

umask 077

cleanup() {
  "${compose[@]}" logs --no-color >"${work_directory}/containers.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f \
    "${work_directory}/authority.json" \
    "${work_directory}/containers.log" \
    "${work_directory}/control.sqlite" \
    "${work_directory}/evidence.json" \
    "${work_directory}/expected.json" \
    "${work_directory}/inventory.json"
  rmdir "${work_directory}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for command_name in podman shasum uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
podman info >/dev/null

mkdir -p "${work_directory}"
chmod 700 "${work_directory}"
export COFFER_INVENTORY_PORT="${registry_port}"
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
    printf 'Distribution inventory fixture did not become healthy\n' >&2
    exit 1
  fi
  sleep 1
done
test "${status}" = healthy

uv run --project "${repository_root}" python "${script_dir}/prepare_fixture.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --repository-root "${repository_root}" \
  --work-directory "${work_directory}"

control_before="$(shasum -a 256 "${work_directory}/control.sqlite" | awk '{print $1}')"
"${compose[@]}" stop registry >/dev/null
test "$(podman inspect "${container_id}" --format '{{.State.Status}}')" = exited

storage_state() {
  "${compose[@]}" run --rm --no-deps --entrypoint sh enumerator -c \
    'find /var/lib/registry -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum' \
    | awk '{print $1}'
}

storage_before="$(storage_state)"
"${compose[@]}" run --rm --no-deps enumerator >"${work_directory}/evidence.json"
storage_after="$(storage_state)"
test "${storage_before}" = "${storage_after}"

uv run --project "${repository_root}" coffer-inventory-verify \
  --evidence "${work_directory}/evidence.json" \
  --authority "${work_directory}/authority.json" \
  --output "${work_directory}/inventory.json"
control_after="$(shasum -a 256 "${work_directory}/control.sqlite" | awk '{print $1}')"
test "${control_before}" = "${control_after}"

"${compose[@]}" start registry >/dev/null
for _attempt in $(seq 1 60); do
  status="$(podman inspect "${container_id}" --format '{{.State.Health.Status}}')"
  test "${status}" = healthy && break
  sleep 1
done
test "${status}" = healthy
uv run --project "${repository_root}" python "${script_dir}/verify_fixture.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --work-directory "${work_directory}"

cleanup
trap - EXIT
test -z "$(podman ps --all --quiet --filter label=org.openstack.coffer.poc=inventory)"
test -z "$(podman volume ls --quiet --filter label=org.openstack.coffer.poc=inventory)"
test -z "$(podman network ls --quiet --filter label=org.openstack.coffer.poc=inventory)"
test ! -e "${work_directory}"
printf 'inventory cleanup verified: containers=0 volumes=0 networks=0 state=0\n'
