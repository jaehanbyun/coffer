#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd "${script_directory}/../../.." && pwd -P)"
work_root="${repository_root}/work/gc-retention-filesystem"
lock_directory="${work_root}/.lock"
topology="${script_directory}/../topology.json"
image="docker.io/library/registry:3.1.1@sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
registry_port="${COFFER_GC_PORT:-55008}"
label="org.openstack.coffer.poc=gc-filesystem"
invocation_directory=""
storage_directory=""
snapshot_directory=""
restore_directory=""
cleanup_started=0

umask 077

compose() {
  podman compose \
    --file "${script_directory}/compose.yaml" \
    --project-name coffer-gc-filesystem \
    "$@"
}

cleanup() {
  local exit_status=$?
  trap - EXIT
  if (( cleanup_started )); then
    return "${exit_status}"
  fi
  cleanup_started=1
  for container_name in \
    coffer-gc-filesystem-collect \
    coffer-gc-filesystem-dry-1 \
    coffer-gc-filesystem-dry-2
  do
    podman rm --force "${container_name}" >/dev/null 2>&1 || true
  done
  if test -n "${storage_directory}"; then
    export COFFER_GC_STORAGE="${storage_directory}"
    export COFFER_GC_PORT="${registry_port}"
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  if test -n "${invocation_directory}"; then
    case "${invocation_directory}" in
      "${work_root}"/invocation.*)
        rm -rf -- "${invocation_directory}"
        ;;
      *)
        printf 'refusing unsafe fixture cleanup path\n' >&2
        return 90
        ;;
    esac
  fi
  rmdir "${lock_directory}" >/dev/null 2>&1 || true
  rmdir "${work_root}" >/dev/null 2>&1 || true
  return "${exit_status}"
}
trap cleanup EXIT

for command_name in podman uv cp jq; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
podman info >/dev/null

mkdir -p "${work_root}"
chmod 700 "${work_root}"
if ! mkdir "${lock_directory}"; then
  printf 'another GC filesystem fixture owns the lock\n' >&2
  exit 2
fi
chmod 700 "${lock_directory}"
if test -n "$(podman ps --all --quiet --filter "label=${label}")"; then
  printf 'pre-existing GC filesystem container found\n' >&2
  exit 3
fi
if test -n "$(podman network ls --quiet --filter "label=${label}")"; then
  printf 'pre-existing GC filesystem network found\n' >&2
  exit 4
fi

invocation_directory="$(mktemp -d "${work_root}/invocation.XXXXXX")"
chmod 700 "${invocation_directory}"
storage_directory="${invocation_directory}/storage"
snapshot_directory="${invocation_directory}/snapshot"
restore_directory="${invocation_directory}/restore"
mkdir "${storage_directory}" "${snapshot_directory}" "${restore_directory}"
chmod 700 \
  "${storage_directory}" \
  "${snapshot_directory}" \
  "${restore_directory}"
fixture="${invocation_directory}/fixture.json"
before_tree="${invocation_directory}/tree-before.json"
after_tree="${invocation_directory}/tree-after.json"
restore_tree="${invocation_directory}/tree-restore.json"
dry_one_raw="${invocation_directory}/dry-run-one.txt"
dry_two_raw="${invocation_directory}/dry-run-two.txt"
collection_raw="${invocation_directory}/collection.txt"
dry_one="${invocation_directory}/dry-run-one.json"
dry_two="${invocation_directory}/dry-run-two.json"
collection_evidence="${invocation_directory}/collection.json"
authorization="${invocation_directory}/authorization.json"
consumption="${invocation_directory}/consumption.json"
survivors="${invocation_directory}/survivors.json"
restored_survivors="${invocation_directory}/restored-survivors.json"
reclaim="${invocation_directory}/reclaim.json"
adapter=(
  uv run --project "${repository_root}" python
  "${script_directory}/filesystem_adapter.py"
)

export COFFER_GC_STORAGE="${storage_directory}"
export COFFER_GC_PORT="${registry_port}"
compose config --quiet

wait_healthy() {
  local container_id="$1"
  local status=""
  local running=""
  for _attempt in $(seq 1 60); do
    running="$(
      podman inspect "${container_id}" \
        --format '{{.State.Running}}'
    )"
    if test "${running}" != true; then
      return 1
    fi
    status="$(
      podman inspect "${container_id}" \
        --format '{{.State.Health.Status}}'
    )"
    if test "${status}" = healthy; then
      return 0
    fi
    if test "${status}" = unhealthy; then
      return 1
    fi
    sleep 1
  done
  return 1
}

start_registry() {
  compose up --detach registry >/dev/null
  registry_container_id="$(compose ps --quiet registry)"
  test -n "${registry_container_id}"
  wait_healthy "${registry_container_id}"
}

stop_registry() {
  compose stop --timeout 30 registry >/dev/null
  test "$(
    podman inspect "${registry_container_id}" --format '{{.State.Status}}'
  )" = exited
}

run_collector() {
  local container_name="$1"
  local storage_mode="$2"
  local output_path="$3"
  shift 3
  podman run --rm \
    --name "${container_name}" \
    --label "${label}" \
    --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m \
    --cap-drop=all \
    --cap-add=DAC_OVERRIDE \
    --security-opt no-new-privileges \
    --network none \
    --volume "${script_directory}/registry-config.yml:/etc/distribution/config.yml:ro" \
    --volume "${storage_directory}:/var/lib/registry:${storage_mode},z" \
    "${image}" \
    garbage-collect /etc/distribution/config.yml "$@" \
    >"${output_path}"
  chmod 600 "${output_path}"
}

start_registry
uv run --project "${repository_root}" python \
  "${script_directory}/prepare_fixture.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --output "${fixture}"
stop_registry

"${adapter[@]}" summarize \
  --root "${storage_directory}" \
  --output "${before_tree}"
cp -R "${storage_directory}/." "${snapshot_directory}/"
"${adapter[@]}" summarize \
  --root "${snapshot_directory}" \
  --output "${restore_tree}.snapshot"
cmp "${before_tree}" "${restore_tree}.snapshot"
rm "${restore_tree}.snapshot"

run_collector \
  coffer-gc-filesystem-dry-1 \
  ro \
  "${dry_one_raw}" \
  --dry-run
"${adapter[@]}" normalize \
  --fixture "${fixture}" \
  --raw-output "${dry_one_raw}" \
  --topology "${topology}" \
  --output "${dry_one}"
run_collector \
  coffer-gc-filesystem-dry-2 \
  ro \
  "${dry_two_raw}" \
  --dry-run
"${adapter[@]}" normalize \
  --fixture "${fixture}" \
  --raw-output "${dry_two_raw}" \
  --topology "${topology}" \
  --output "${dry_two}"
"${adapter[@]}" authorize \
  --first "${dry_one}" \
  --second "${dry_two}" \
  --topology "${topology}" \
  --ttl 900 \
  --output "${authorization}"
"${adapter[@]}" consume \
  --authorization "${authorization}" \
  --output "${consumption}"

run_collector \
  coffer-gc-filesystem-collect \
  rw \
  "${collection_raw}"
"${adapter[@]}" normalize \
  --fixture "${fixture}" \
  --raw-output "${collection_raw}" \
  --topology "${topology}" \
  --output "${collection_evidence}"
if "${adapter[@]}" consume \
  --authorization "${authorization}" \
  --output "${invocation_directory}/replayed-consumption.json" \
  >/dev/null 2>&1
then
  printf 'single-use collection authorization replayed\n' >&2
  exit 5
fi
test ! -e "${invocation_directory}/replayed-consumption.json"

"${adapter[@]}" summarize \
  --root "${storage_directory}" \
  --output "${after_tree}"
start_registry
uv run --project "${repository_root}" python \
  "${script_directory}/verify_fixture.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --fixture "${fixture}" \
  --mode collected \
  --output "${survivors}"
stop_registry

compose down --remove-orphans >/dev/null
cp -R "${snapshot_directory}/." "${restore_directory}/"
"${adapter[@]}" summarize \
  --root "${restore_directory}" \
  --output "${restore_tree}"
export COFFER_GC_STORAGE="${restore_directory}"
start_registry
uv run --project "${repository_root}" python \
  "${script_directory}/verify_fixture.py" \
  --registry-origin "http://127.0.0.1:${registry_port}" \
  --fixture "${fixture}" \
  --mode restored \
  --output "${restored_survivors}"
stop_registry
compose down --remove-orphans >/dev/null
export COFFER_GC_STORAGE="${storage_directory}"

"${adapter[@]}" verify-reclaim \
  --before "${before_tree}" \
  --after "${after_tree}" \
  --restored "${restore_tree}" \
  --output "${reclaim}"
candidate_total="$(jq -er '.candidate_total' "${dry_one}")"
reclaimed_bytes="$(jq -er '.logical_bytes_reclaimed' "${reclaim}")"
survivor_count="$(jq -er '.survivor_classes | length' "${survivors}")"

cleanup
trap - EXIT
test -z "$(podman ps --all --quiet --filter "label=${label}")"
test -z "$(podman network ls --quiet --filter "label=${label}")"
test ! -e "${work_root}"
printf \
  'GC filesystem fixture passed candidates=%s survivors=%s reclaimed-bytes=%s residue=0\n' \
  "${candidate_total}" \
  "${survivor_count}" \
  "${reclaimed_bytes}"
