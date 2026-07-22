#!/usr/bin/env bash

set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd "${script_directory}/../.." && pwd -P)"
work_directory="${repository_root}/work/integration"
devstack_instance="${COFFER_DEVSTACK_INSTANCE:-coffer-devstack}"
rgw_remote="${COFFER_RGW_REMOTE:-bb00}"
rgw_guest="${COFFER_RGW_GUEST:-coffer@192.168.122.200}"
known_hosts="${repository_root}/work/rgw/known_hosts"
broker_pid=""
tunnel_pid=""
devstack_started=0
keystone_fixture_prepared=0
rgw_integration_prepared=0

ssh_options=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${known_hosts}"
  -o "ProxyJump=${rgw_remote}"
)

start_broker() {
  COFFER_INTEGRATION_AUTH_URL="${COFFER_DEVSTACK_AUTH_URL}" \
  COFFER_INTEGRATION_KEYSTONE_CA="${COFFER_DEVSTACK_CAFILE}" \
  COFFER_INTEGRATION_DATABASE_FILE="${work_directory}/coffer.sqlite" \
  COFFER_INTEGRATION_SIGNING_KEY="${work_directory}/signing-key.pem" \
    uv run --project "${repository_root}" gunicorn \
      --bind 127.0.0.1:18081 \
      --workers 1 \
      --worker-class gthread \
      --threads 2 \
      --certfile "${work_directory}/broker.crt" \
      --keyfile "${work_directory}/broker-key.pem" \
      --chdir "${script_directory}" \
      real_broker:application >>"${work_directory}/broker.log" 2>&1 &
  broker_pid=$!
}

wait_for_broker() {
  local broker_status=""
  for _attempt in $(seq 1 30); do
    broker_status="$(
      curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 2 --max-time 5 \
        --cacert "${work_directory}/broker-ca.crt" \
        --get --data-urlencode 'service=coffer-registry-poc' \
        https://127.0.0.1:18081/auth/token 2>/dev/null || true
    )"
    if test "${broker_status}" = 401; then
      return 0
    fi
    sleep 1
  done
  printf 'token broker did not become ready; last status=%s\n' \
    "${broker_status}" >&2
  return 1
}

cleanup() {
  local exit_status=$?
  trap - EXIT

  if [[ -n "${tunnel_pid}" ]]; then
    kill "${tunnel_pid}" >/dev/null 2>&1 || true
    wait "${tunnel_pid}" 2>/dev/null || true
  fi
  if [[ -n "${broker_pid}" ]]; then
    kill "${broker_pid}" >/dev/null 2>&1 || true
    wait "${broker_pid}" 2>/dev/null || true
  fi
  if (( rgw_integration_prepared )); then
    scp "${ssh_options[@]}" "${script_directory}/guest-prepare-rgw.sh" \
      "${rgw_guest}:/tmp/guest-prepare-rgw.sh" >/dev/null 2>&1 || true
    ssh "${ssh_options[@]}" "${rgw_guest}" \
      'sudo bash /tmp/guest-prepare-rgw.sh cleanup' >/dev/null 2>&1 || true
    "${repository_root}/poc/rgw/run-distribution.sh" >/dev/null 2>&1 || true
  fi
  if (( keystone_fixture_prepared )); then
    limactl shell "${devstack_instance}" \
      /tmp/guest-verify.sh cleanup-registry-fixture >/dev/null 2>&1 || true
  fi
  rm -f \
    "${work_directory}/credentials.json" \
    "${work_directory}/client-credentials.json" \
    "${work_directory}/signing-key.pem" \
    "${work_directory}/broker-ca-key.pem" \
    "${work_directory}/broker-key.pem" \
    "${work_directory}/coffer.sqlite"
  if (( devstack_started )); then
    limactl stop "${devstack_instance}" >/dev/null 2>&1 || true
  fi
  exit "${exit_status}"
}
trap cleanup EXIT

for command_name in curl jq limactl openssl rg scp ssh uv; do
  command -v "${command_name}" >/dev/null || {
    printf 'missing required command: %s\n' "${command_name}" >&2
    exit 1
  }
done
test -f "${known_hosts}"

mkdir -p "${work_directory}"
chmod 700 "${work_directory}"
rm -f \
  "${work_directory}/credentials.json" \
  "${work_directory}/client-credentials.json" \
  "${work_directory}/signing-key.pem" \
  "${work_directory}/jwks.json" \
  "${work_directory}/broker-ca-key.pem" \
  "${work_directory}/broker-ca.crt" \
  "${work_directory}/broker-key.pem" \
  "${work_directory}/broker.crt" \
  "${work_directory}/coffer.sqlite" \
  "${work_directory}/broker.log" \
  "${work_directory}/distribution.log" \
  "${work_directory}/project-b-push.log" \
  "${work_directory}/evidence.json" \
  "${work_directory}/health-before.json" \
  "${work_directory}/health-after.json" \
  "${work_directory}/ready-before.json" \
  "${work_directory}/ready-after.json" \
  "${work_directory}/metrics-before.prom" \
  "${work_directory}/metrics-after.prom" \
  "${work_directory}/tunnel.log"

devstack_status="$(
  limactl list --json | \
    jq -r --arg instance "${devstack_instance}" \
      'select(.name == $instance) | .status'
)"
case "${devstack_status}" in
  Running) ;;
  Stopped)
    limactl start "${devstack_instance}" >/dev/null
    devstack_started=1
    ;;
  *)
    printf 'unexpected DevStack instance state: %s\n' "${devstack_status}" >&2
    exit 2
    ;;
esac

"${repository_root}/poc/devstack/export-ca.sh" >/dev/null
# shellcheck disable=SC1091
source "${repository_root}/work/devstack/bindings.env"
curl --fail --silent --show-error --cacert "${COFFER_DEVSTACK_CAFILE}" \
  "${COFFER_DEVSTACK_AUTH_URL}" >/dev/null

limactl copy "${repository_root}/poc/devstack/guest-verify.sh" \
  "${devstack_instance}:/tmp/guest-verify.sh"
limactl shell "${devstack_instance}" chmod 700 /tmp/guest-verify.sh
limactl shell "${devstack_instance}" \
  /tmp/guest-verify.sh prepare-registry-fixture >/dev/null
keystone_fixture_prepared=1
limactl copy "${devstack_instance}:/tmp/coffer-registry-fixture.json" \
  "${work_directory}/credentials.json"
chmod 600 "${work_directory}/credentials.json"
jq '{project_a: {application_credential_id: .project_a.application_credential_id, application_credential_secret: .project_a.application_credential_secret, project_id: .project_a.project_id}, project_b: {application_credential_id: .project_b.application_credential_id, application_credential_secret: .project_b.application_credential_secret, project_id: .project_b.project_id}}' \
  "${work_directory}/credentials.json" \
  >"${work_directory}/client-credentials.json"
chmod 600 "${work_directory}/client-credentials.json"

uv run --project "${repository_root}" python \
  "${script_directory}/prepare_runtime.py" \
  --credential-file "${work_directory}/client-credentials.json" \
  --output-directory "${work_directory}"
openssl verify -CAfile "${work_directory}/broker-ca.crt" \
  "${work_directory}/broker.crt" >/dev/null
test "$(jq '.keys | length' "${work_directory}/jwks.json")" -eq 1

start_broker
wait_for_broker

scp "${ssh_options[@]}" \
  "${repository_root}/poc/rgw/guest-run-distribution.sh" \
  "${rgw_guest}:/tmp/guest-run-distribution.sh"
scp "${ssh_options[@]}" \
  "${script_directory}/guest-prepare-rgw.sh" \
  "${rgw_guest}:/tmp/guest-prepare-rgw.sh"
scp "${ssh_options[@]}" \
  "${script_directory}/guest-verify.sh" \
  "${rgw_guest}:/tmp/guest-integration-verify.sh"
scp "${ssh_options[@]}" \
  "${script_directory}/guest-verify-broker-restart.sh" \
  "${rgw_guest}:/tmp/guest-verify-broker-restart.sh"
scp "${ssh_options[@]}" \
  "${work_directory}/client-credentials.json" \
  "${rgw_guest}:/tmp/coffer-integration-client-credentials.json"
scp "${ssh_options[@]}" \
  "${work_directory}/jwks.json" \
  "${rgw_guest}:/tmp/coffer-integration-jwks.json"
scp "${ssh_options[@]}" \
  "${work_directory}/broker-ca.crt" \
  "${rgw_guest}:/tmp/coffer-integration-token-ca.crt"

ssh "${ssh_options[@]}" -N \
  -o ExitOnForwardFailure=yes \
  -R 127.0.0.1:18081:127.0.0.1:18081 \
  "${rgw_guest}" >"${work_directory}/tunnel.log" 2>&1 &
tunnel_pid=$!
sleep 1
kill -0 "${tunnel_pid}"

ssh "${ssh_options[@]}" "${rgw_guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-prepare-rgw.sh prepare'
rgw_integration_prepared=1
ssh "${ssh_options[@]}" "${rgw_guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-integration-verify.sh'

curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/healthz \
  >"${work_directory}/health-before.json"
curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/readyz \
  >"${work_directory}/ready-before.json"
curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/metrics \
  >"${work_directory}/metrics-before.prom"

kill "${broker_pid}"
wait "${broker_pid}" 2>/dev/null || true
broker_pid=""
start_broker
wait_for_broker
ssh "${ssh_options[@]}" "${rgw_guest}" \
  'sudo env LC_ALL=C LANG=C bash /tmp/guest-verify-broker-restart.sh'
curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/healthz \
  >"${work_directory}/health-after.json"
curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/readyz \
  >"${work_directory}/ready-after.json"
curl --fail --silent --show-error \
  --cacert "${work_directory}/broker-ca.crt" \
  https://127.0.0.1:18081/metrics \
  >"${work_directory}/metrics-after.prom"

scp "${ssh_options[@]}" \
  "${rgw_guest}:/tmp/coffer-integration-evidence.json" \
  "${work_directory}/evidence.json"
scp "${ssh_options[@]}" \
  "${rgw_guest}:/tmp/coffer-integration-distribution.log" \
  "${work_directory}/distribution.log"
scp "${ssh_options[@]}" \
  "${rgw_guest}:/tmp/coffer-integration-project-b-push.log" \
  "${work_directory}/project-b-push.log"
chmod 0644 \
  "${work_directory}/evidence.json" \
  "${work_directory}/distribution.log" \
  "${work_directory}/project-b-push.log"

for phase in before after; do
  jq -e '
    .status == "ok" and .checks.process == "alive"
  ' "${work_directory}/health-${phase}.json" >/dev/null
  jq -e '
    .status == "ok" and .checks.database == "ready"
  ' "${work_directory}/ready-${phase}.json" >/dev/null
  grep -Fq 'coffer_build_info{version="0.1.0"} 1.0' \
    "${work_directory}/metrics-${phase}.prom"
  grep -Fq 'coffer_readiness_checks_total{result="ready"} 1.0' \
    "${work_directory}/metrics-${phase}.prom"
  awk '
    $1 == "coffer_token_decisions_total{result=\"issued\"}" && $2 > 0 {
      issued = 1
    }
    END { exit !issued }
  ' "${work_directory}/metrics-${phase}.prom"
done

request_a_id="$(jq -er '.project_a_token_request_id' \
  "${work_directory}/evidence.json")"
request_b_id="$(jq -er '.project_b_token_request_id' \
  "${work_directory}/evidence.json")"
project_a_id="$(jq -er '.project_a_id' "${work_directory}/evidence.json")"
project_b_id="$(jq -er '.project_b_id' "${work_directory}/evidence.json")"
line_a="$(rg -F "request_id=${request_a_id}" "${work_directory}/broker.log")"
line_b="$(rg -F "request_id=${request_b_id}" "${work_directory}/broker.log")"
grep -Fq "project_id=${project_a_id}" <<<"${line_a}"
grep -Fq 'result=issued' <<<"${line_a}"
grep -Fq 'granted=[' <<<"${line_a}"
if grep -Fq 'granted=[]' <<<"${line_a}"; then
  printf 'project A token unexpectedly contained no registry grant\n' >&2
  exit 40
fi
grep -Fq "project_id=${project_b_id}" <<<"${line_b}"
grep -Fq 'result=issued' <<<"${line_b}"
grep -Fq 'granted=[]' <<<"${line_b}"

while IFS= read -r secret_value; do
  test -n "${secret_value}"
  if rg --fixed-strings --quiet -- "${secret_value}" \
    "${work_directory}/broker.log" \
    "${work_directory}/distribution.log" \
    "${work_directory}/project-b-push.log" \
    "${work_directory}/metrics-before.prom" \
    "${work_directory}/metrics-after.prom" \
    "${work_directory}/tunnel.log"; then
    printf 'application-credential secret leaked into retained logs\n' >&2
    exit 41
  fi
done < <(jq -r \
  '.project_a.application_credential_secret, .project_b.application_credential_secret' \
  "${work_directory}/client-credentials.json")
if rg --quiet 'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+' \
  "${work_directory}/broker.log" \
  "${work_directory}/distribution.log" \
  "${work_directory}/project-b-push.log" \
  "${work_directory}/metrics-before.prom" \
  "${work_directory}/metrics-after.prom" \
  "${work_directory}/tunnel.log"; then
  printf 'registry bearer token leaked into retained logs\n' >&2
  exit 42
fi

for forbidden_value in \
  "${project_a_id}" \
  "${project_b_id}" \
  "${request_a_id}" \
  "${request_b_id}" \
  "$(jq -er '.repository' "${work_directory}/evidence.json")" \
  "$(jq -er '.project_a.application_credential_id' \
    "${work_directory}/client-credentials.json")" \
  "$(jq -er '.project_b.application_credential_id' \
    "${work_directory}/client-credentials.json")"; do
  if rg --fixed-strings --quiet -- "${forbidden_value}" \
    "${work_directory}/metrics-before.prom" \
    "${work_directory}/metrics-after.prom"; then
    printf 'tenant or request identifier leaked into metrics\n' >&2
    exit 43
  fi
done

jq -e '
  .keystone == "real DevStack" and
  .storage == "real Ceph RGW" and
  .distribution == "unmodified v3.1.1" and
  (.clients | sort == ["Podman", "Skopeo"]) and
  .project_a_status == 200 and
  .project_b_cross_project_status == 401 and
  .project_b_push == "denied" and
  .digest == .distribution_restart_digest and
  (.podman_digest | test("^sha256:[0-9a-f]{64}$")) and
  .digest == .coffer_restart_digest
' "${work_directory}/evidence.json" >/dev/null

printf 'Real end-to-end integration evidence:\n'
jq '{keystone, storage, distribution, clients, repository, digest, distribution_restart_digest, coffer_restart_digest, project_a_status, project_b_cross_project_status, project_b_push, project_a_token_request_id, project_b_token_request_id}' \
  "${work_directory}/evidence.json"
printf 'Operational endpoints passed before and after broker restart; metrics labels remained bounded.\n'
