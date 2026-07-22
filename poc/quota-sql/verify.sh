#!/usr/bin/env bash

set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/../.." && pwd -P)"
work_directory="${repository_root}/work/quota-sql"
compose=(podman compose --file "${script_dir}/compose.yaml" --project-name coffer-quota-sql)
postgres_port="${COFFER_POSTGRES_PORT:-55432}"
mariadb_port="${COFFER_MARIADB_PORT:-53306}"

umask 077

cleanup() {
  "${compose[@]}" logs --no-color >"${work_directory}/services.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "${work_directory}/postgres-password" \
    "${work_directory}/mariadb-password" \
    "${work_directory}/mariadb-root-password" \
    "${work_directory}/services.log"
  rmdir "${work_directory}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for command_name in openssl podman uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
podman info >/dev/null

mkdir -p "${work_directory}"
chmod 700 "${work_directory}"
openssl rand -hex 24 >"${work_directory}/postgres-password"
openssl rand -hex 24 >"${work_directory}/mariadb-password"
openssl rand -hex 24 >"${work_directory}/mariadb-root-password"
chmod 600 "${work_directory}"/*-password
export COFFER_QUOTA_SQL_SECRET_DIR="${work_directory}"
export COFFER_POSTGRES_PORT="${postgres_port}"
export COFFER_MARIADB_PORT="${mariadb_port}"
unset COFFER_DATABASE_URL

"${compose[@]}" config --quiet
"${compose[@]}" up --detach postgres mariadb

wait_for_health() {
  local service="$1"
  local container_id
  local status
  container_id="$("${compose[@]}" ps --quiet "${service}")"
  test -n "${container_id}"
  for _attempt in $(seq 1 90); do
    status="$(podman inspect "${container_id}" --format '{{.State.Health.Status}}')"
    if test "${status}" = healthy; then
      return
    fi
    if test "${status}" = unhealthy; then
      printf '%s did not become healthy\n' "${service}" >&2
      return 1
    fi
    sleep 1
  done
  printf '%s health check timed out\n' "${service}" >&2
  return 1
}

wait_for_health postgres
wait_for_health mariadb

uv run --project "${repository_root}" --extra postgresql --extra mariadb \
  python "${script_dir}/verify_shared_sql.py" \
  --engine postgresql \
  --port "${postgres_port}" \
  --password-file "${work_directory}/postgres-password" \
  --repository-root "${repository_root}"
uv run --project "${repository_root}" --extra postgresql --extra mariadb \
  python "${script_dir}/verify_shared_sql.py" \
  --engine mariadb \
  --port "${mariadb_port}" \
  --password-file "${work_directory}/mariadb-password" \
  --repository-root "${repository_root}"

"${compose[@]}" logs --no-color >"${work_directory}/services.log"
service_logs="$(<"${work_directory}/services.log")"
for secret_file in \
  "${work_directory}/postgres-password" \
  "${work_directory}/mariadb-password" \
  "${work_directory}/mariadb-root-password"; do
  secret_value="$(<"${secret_file}")"
  if [[ "${service_logs}" == *"${secret_value}"* ]]; then
    printf 'a disposable database secret appeared in service logs\n' >&2
    exit 1
  fi
done
unset service_logs secret_value

cleanup
trap - EXIT
test -z "$(podman ps --all --quiet --filter label=org.openstack.coffer.poc=quota-sql)"
test -z "$(podman volume ls --quiet --filter label=org.openstack.coffer.poc=quota-sql)"
test -z "$(podman network ls --quiet --filter label=org.openstack.coffer.poc=quota-sql)"
test ! -e "${work_directory}"
printf 'shared SQL cleanup verified: containers=0 volumes=0 networks=0 credentials=0\n'
