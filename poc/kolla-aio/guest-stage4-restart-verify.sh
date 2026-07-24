#!/usr/bin/env bash

set -euo pipefail

state_file="/root/coffer-kolla-aio-stage4-identities.json"
evidence_file="/root/coffer-kolla-aio-stage4-tenant-evidence.json"
registry_url="https://192.168.122.220:8788"
external_ca="/etc/kolla/certificates-stage4/ca/root.crt"
token_service="coffer-registry"
temporary_directory="$(mktemp -d /root/coffer-stage4-restart.XXXXXX)"

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

schema_revision() {
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
}

make_bearer_config() {
  local basic_config="${temporary_directory}/basic.curl"
  local credential_id
  local credential_secret
  local bearer
  credential_id="$(
    jq -er '.project_a.application_credential_id' "${state_file}"
  )"
  credential_secret="$(
    jq -er '.project_a.application_credential_secret' "${state_file}"
  )"
  printf 'user = "%s:%s"\n' "${credential_id}" "${credential_secret}" \
    >"${basic_config}"
  chmod 0600 "${basic_config}"
  curl --fail --silent --show-error \
    --config "${basic_config}" \
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
}

manifest_digest() {
  make_bearer_config
  curl --fail --silent --show-error \
    --head \
    --config "${temporary_directory}/bearer.curl" \
    --cacert "${external_ca}" \
    --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
    --header 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    --dump-header "${temporary_directory}/manifest.headers" \
    --output /dev/null \
    "${registry_url}/v2/${repository}/manifests/${expected_digest}"
  awk -F': ' '
    tolower($1) == "docker-content-digest" {
      gsub("\r", "", $2)
      print $2
    }
  ' "${temporary_directory}/manifest.headers"
}

revision_before="$(schema_revision)"
test "$(manifest_digest)" = "${expected_digest}"
echo "Stage 4 pre-restart digest and schema revision verified"

docker restart coffer_api coffer_registry coffer_edge haproxy >/dev/null
for container_name in coffer_api coffer_registry coffer_edge haproxy; do
  for _attempt in $(seq 1 60); do
    if test "$(
      docker inspect --format '{{.State.Health.Status}}' "${container_name}"
    )" = healthy; then
      break
    fi
    sleep 1
  done
  test "$(
    docker inspect --format '{{.State.Health.Status}}' "${container_name}"
  )" = healthy
  printf 'Stage 4 restart health verified service=%s\n' "${container_name}"
done

for _attempt in $(seq 1 30); do
  registry_status="$(
    curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --cacert "${external_ca}" "${registry_url}/v2/" 2>/dev/null || true
  )"
  if test "${registry_status}" = 401; then
    break
  fi
  sleep 1
done
test "${registry_status}" = 401
echo "Stage 4 external edge challenge recovered after restart"
restart_digest="$(manifest_digest)"
test "${restart_digest}" = "${expected_digest}"
revision_after="$(schema_revision)"
test "${revision_after}" = "${revision_before}"

jq \
  --arg restart_digest "${restart_digest}" \
  --arg schema_revision "${revision_after}" \
  '. + {
    restart_digest: $restart_digest,
    restart_persistence: "passed",
    restarted_services: ["coffer-api", "coffer-edge", "Distribution", "HAProxy"],
    schema_revision_before_restart: $schema_revision,
    schema_revision_after_restart: $schema_revision
  }' "${evidence_file}" >"${temporary_directory}/evidence.json"
install -o root -g root -m 0600 \
  "${temporary_directory}/evidence.json" "${evidence_file}"

printf 'Stage 4 restart persistence passed digest=%s revision=%s\n' \
  "${restart_digest}" "${revision_after}"
