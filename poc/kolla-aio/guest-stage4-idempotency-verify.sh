#!/usr/bin/env bash

set -euo pipefail

state_file="/root/coffer-kolla-aio-stage4-identities.json"
evidence_file="/root/coffer-kolla-aio-stage4-tenant-evidence.json"
registry_url="https://192.168.122.220:8788"
external_ca="/etc/kolla/certificates-stage4/ca/root.crt"
token_service="coffer-registry"
temporary_directory="$(mktemp -d /root/coffer-stage4-idempotency.XXXXXX)"

cleanup() {
  local exit_status=$?
  trap - EXIT
  rm -rf -- "${temporary_directory}"
  exit "${exit_status}"
}
trap cleanup EXIT

test "$(id -u)" -eq 0
test "$(stat -c '%a' "${state_file}")" = 600
test "$(stat -c '%a' "${evidence_file}")" = 600
repository="$(jq -er '.repository' "${evidence_file}")"
expected_digest="$(jq -er '.digest' "${evidence_file}")"
expected_revision="$(
  jq -er '.schema_revision_after_restart' "${evidence_file}"
)"

for run_number in 1 2; do
  log_file="/root/coffer-stage4-reconfigure-${run_number}.log"
  test -s "${log_file}"
  test "$(grep -c '^changed:' "${log_file}")" = 1
  changed_task="$(
    awk '
      /^TASK / {task=$0}
      /^changed:/ {print task}
    ' "${log_file}"
  )"
  grep -Fq 'Run the one-shot Coffer schema bootstrap' <<<"${changed_task}"
  grep -Eq \
    '^localhost +: ok=69 +changed=1 +unreachable=0 +failed=0 ' \
    "${log_file}"
done

current_revision="$(
  docker exec -i coffer_api /usr/local/bin/python3 - <<'PY'
from sqlalchemy import create_engine, text

from coffer.config import parse_config

configuration = parse_config(
    args=["--config-file", "/etc/coffer/coffer.conf"]
)
engine = create_engine(configuration.database.connection)
with engine.connect() as connection:
    revisions = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalars().all()
if len(revisions) != 1:
    raise RuntimeError("expected exactly one Alembic revision")
print(revisions[0])
PY
)"
test "${current_revision}" = "${expected_revision}"

registry_status="$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --cacert "${external_ca}" "${registry_url}/v2/"
)"
test "${registry_status}" = 401

credential_id="$(
  jq -er '.project_a.application_credential_id' "${state_file}"
)"
credential_secret="$(
  jq -er '.project_a.application_credential_secret' "${state_file}"
)"
printf 'user = "%s:%s"\n' "${credential_id}" "${credential_secret}" \
  >"${temporary_directory}/basic.curl"
chmod 0600 "${temporary_directory}/basic.curl"
curl --fail --silent --show-error \
  --config "${temporary_directory}/basic.curl" \
  --cacert "${external_ca}" \
  --output "${temporary_directory}/token.json" \
  --get \
  --data-urlencode "service=${token_service}" \
  --data-urlencode "scope=repository:${repository}:pull" \
  "${registry_url}/auth/token"
bearer="$(jq -er '.token' "${temporary_directory}/token.json")"
printf 'header = "Authorization: Bearer %s"\n' "${bearer}" \
  >"${temporary_directory}/bearer.curl"
chmod 0600 "${temporary_directory}/bearer.curl"
unset credential_secret bearer

curl --fail --silent --show-error \
  --head \
  --config "${temporary_directory}/bearer.curl" \
  --cacert "${external_ca}" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
  --header 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
  --dump-header "${temporary_directory}/manifest.headers" \
  --output /dev/null \
  "${registry_url}/v2/${repository}/manifests/${expected_digest}"
post_reconfigure_digest="$(
  awk -F': ' '
    tolower($1) == "docker-content-digest" {
      gsub("\r", "", $2)
      print $2
    }
  ' "${temporary_directory}/manifest.headers"
)"
test "${post_reconfigure_digest}" = "${expected_digest}"

docker logs coffer_api >"${temporary_directory}/coffer-api.log" 2>&1
docker logs coffer_edge >"${temporary_directory}/coffer-edge.log" 2>&1
docker logs coffer_registry >"${temporary_directory}/coffer-registry.log" 2>&1
log_inputs=(
  /root/coffer-stage4-reconfigure-1.log
  /root/coffer-stage4-reconfigure-2.log
  "${temporary_directory}/coffer-api.log"
  "${temporary_directory}/coffer-edge.log"
  "${temporary_directory}/coffer-registry.log"
)
while IFS= read -r secret_value; do
  test -n "${secret_value}"
  if grep -aFq -- "${secret_value}" "${log_inputs[@]}"; then
    echo "Stage 4 secret leaked into retained runtime output" >&2
    exit 39
  fi
done < <(
  jq -r '
    .project_a.application_credential_secret,
    .project_a.user_password,
    .project_b.application_credential_secret,
    .project_b.user_password
  ' "${state_file}"
  for secret_name in \
    database-password \
    keystone-service-password \
    distribution-http-secret \
    rgw-access-key \
    rgw-secret-key; do
    tr -d '\n' \
      <"/etc/kolla/config/coffer/secrets/${secret_name}"
    printf '\n'
  done
)
if grep -aEq \
  'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${log_inputs[@]}"; then
  echo "registry bearer token leaked into retained runtime output" >&2
  exit 40
fi

jq \
  --arg post_reconfigure_digest "${post_reconfigure_digest}" \
  --arg schema_revision "${current_revision}" \
  '. + {
    post_reconfigure_digest: $post_reconfigure_digest,
    migration_repeat: "no schema change",
    migration_revision_after_reconfigure: $schema_revision,
    reconfigure_runs: [
      {
        ok: 69,
        changed: 1,
        failed: 0,
        intended_change: "one-shot schema bootstrap"
      },
      {
        ok: 69,
        changed: 1,
        failed: 0,
        intended_change: "one-shot schema bootstrap"
      }
    ],
    secret_log_scan: "passed"
  }' "${evidence_file}" >"${temporary_directory}/evidence.json"
install -o root -g root -m 0600 \
  "${temporary_directory}/evidence.json" "${evidence_file}"
rm -f -- \
  /root/coffer-stage4-reconfigure-1.log \
  /root/coffer-stage4-reconfigure-2.log

printf 'Stage 4 idempotency passed digest=%s revision=%s runs=2\n' \
  "${post_reconfigure_digest}" "${current_revision}"
