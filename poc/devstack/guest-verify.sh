#!/usr/bin/env bash
set -euo pipefail

devstack_dir="${COFFER_DEVSTACK_DIR:-${HOME}/devstack}"
fixture_file="/tmp/coffer-host-credential.json"
control_fixture_file="/tmp/coffer-control-fixture.json"
registry_fixture_file="/tmp/coffer-registry-fixture.json"
project_name="coffer-collision"
user_name="coffer-user"
domain_a_name="coffer-lab-a"
domain_b_name="coffer-lab-b"

load_admin() {
  set +u
  # shellcheck disable=SC1091
  source "${devstack_dir}/openrc" admin admin
  set -u
}

host_ip() {
  ip -4 route get 1.1.1.1 | \
    awk '{for (field = 1; field <= NF; field++) if ($field == "src") {print $(field + 1); exit}}'
}

ensure_domain() {
  local name="$1"
  openstack domain show "${name}" -f value -c id 2>/dev/null || \
    openstack domain create "${name}" -f value -c id
}

ensure_project() {
  local domain_id="$1"
  openstack project show --domain "${domain_id}" "${project_name}" \
    -f value -c id 2>/dev/null || \
    openstack project create --domain "${domain_id}" "${project_name}" \
      -f value -c id
}

ensure_user() {
  local domain_id="$1"
  local password="$2"
  local user_id
  user_id="$(openstack user show --domain "${domain_id}" "${user_name}" \
    -f value -c id 2>/dev/null || \
    openstack user create --domain "${domain_id}" --password "${password}" \
      "${user_name}" -f value -c id)"
  openstack user set --password "${password}" "${user_id}"
  printf '%s\n' "${user_id}"
}

user_openstack() {
  local password="$1"
  local domain_id="$2"
  local project_id="$3"
  shift 3
  OS_AUTH_URL="${auth_url}" \
  OS_IDENTITY_API_VERSION=3 \
  OS_AUTH_TYPE=password \
  OS_USERNAME="${user_name}" \
  OS_PASSWORD="${password}" \
  OS_USER_DOMAIN_ID="${domain_id}" \
  OS_PROJECT_ID="${project_id}" \
  OS_PROJECT_DOMAIN_ID="${domain_id}" \
  OS_CACERT="${ca_file}" \
    openstack "$@"
}

credential_openstack() {
  local credential_id="$1"
  local credential_secret="$2"
  shift 2
  env -u OS_TOKEN \
    -u OS_USERNAME \
    -u OS_PASSWORD \
    -u OS_USER_DOMAIN_ID \
    -u OS_USER_DOMAIN_NAME \
    -u OS_PROJECT_ID \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_ID \
    -u OS_PROJECT_DOMAIN_NAME \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=v3applicationcredential \
    OS_APPLICATION_CREDENTIAL_ID="${credential_id}" \
    OS_APPLICATION_CREDENTIAL_SECRET="${credential_secret}" \
    OS_CACERT="${ca_file}" \
    openstack "$@"
}

domain_user_openstack() {
  local username="$1"
  local password="$2"
  local user_domain_id="$3"
  local scope_domain_id="$4"
  shift 4
  env -u OS_TOKEN \
    -u OS_PROJECT_ID \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_ID \
    -u OS_PROJECT_DOMAIN_NAME \
    -u OS_SYSTEM_SCOPE \
    -u OS_USER_DOMAIN_NAME \
    -u OS_DOMAIN_NAME \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=password \
    OS_USERNAME="${username}" \
    OS_PASSWORD="${password}" \
    OS_USER_DOMAIN_ID="${user_domain_id}" \
    OS_DOMAIN_ID="${scope_domain_id}" \
    OS_CACERT="${ca_file}" \
    openstack "$@"
}

system_user_openstack() {
  local username="$1"
  local password="$2"
  local user_domain_id="$3"
  shift 3
  env -u OS_TOKEN \
    -u OS_PROJECT_ID \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_ID \
    -u OS_PROJECT_DOMAIN_NAME \
    -u OS_DOMAIN_ID \
    -u OS_DOMAIN_NAME \
    -u OS_USER_DOMAIN_NAME \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=password \
    OS_USERNAME="${username}" \
    OS_PASSWORD="${password}" \
    OS_USER_DOMAIN_ID="${user_domain_id}" \
    OS_SYSTEM_SCOPE=all \
    OS_CACERT="${ca_file}" \
    openstack "$@"
}

isolated_project_user_openstack() {
  local username="$1"
  local password="$2"
  local user_domain_id="$3"
  local project_id="$4"
  shift 4
  env -u OS_TOKEN \
    -u OS_DOMAIN_ID \
    -u OS_DOMAIN_NAME \
    -u OS_SYSTEM_SCOPE \
    -u OS_USER_DOMAIN_NAME \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_NAME \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=password \
    OS_USERNAME="${username}" \
    OS_PASSWORD="${password}" \
    OS_USER_DOMAIN_ID="${user_domain_id}" \
    OS_PROJECT_ID="${project_id}" \
    OS_PROJECT_DOMAIN_ID="${user_domain_id}" \
    OS_CACERT="${ca_file}" \
    openstack "$@"
}

strict_tls_probe() {
  local trust_file="$1"
  python3 - "${auth_url}" "${trust_file}" <<'PY'
import ssl
import sys
import urllib.request

context = ssl.create_default_context(cafile=sys.argv[2])
with urllib.request.urlopen(sys.argv[1], context=context, timeout=10) as response:
    response.read()
PY
}

create_lifecycle_credential() {
  local name="$1"
  local expiration="$2"
  user_openstack "${user_password_a}" "${domain_a_id}" "${project_a_id}" \
    application credential create --role member \
    --expiration "${expiration}" -f json "${name}"
}

delete_credential_as_admin() {
  local credential_id="$1"
  openstack application credential delete "${credential_id}" \
    >/dev/null 2>&1 || true
}

verify_expiration_guard() {
  local expiration
  local expiration_epoch
  local credential_json
  local credential_id
  local credential_secret

  expiration="$(date -u -d '+12 seconds' +%Y-%m-%dT%H:%M:%S)"
  expiration_epoch="$(date -u -d "${expiration}" +%s)"
  credential_json="$(create_lifecycle_credential \
    "coffer-expiration-$(date +%s)" "${expiration}")"
  credential_id="$(jq -er '.id // .ID' <<<"${credential_json}")"
  credential_secret="$(jq -er '.secret // .Secret' <<<"${credential_json}")"
  unset credential_json

  if ! credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null; then
    delete_credential_as_admin "${credential_id}"
    unset credential_secret
    printf 'finite application credential failed before expiration\n' >&2
    return 1
  fi
  while (( $(date -u +%s) <= expiration_epoch )); do
    sleep 1
  done
  if credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null 2>&1; then
    delete_credential_as_admin "${credential_id}"
    unset credential_secret
    printf 'expired application credential unexpectedly authenticated\n' >&2
    return 1
  fi
  delete_credential_as_admin "${credential_id}"
  unset credential_secret
}

verify_role_removal_guard() {
  local expiration
  local credential_json
  local credential_id
  local credential_secret
  local unexpectedly_authenticated=0

  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  credential_json="$(create_lifecycle_credential \
    "coffer-role-removal-$(date +%s)" "${expiration}")"
  credential_id="$(jq -er '.id // .ID' <<<"${credential_json}")"
  credential_secret="$(jq -er '.secret // .Secret' <<<"${credential_json}")"
  unset credential_json
  credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null

  openstack role remove --project "${project_a_id}" --user "${user_a_id}" member
  if credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null 2>&1; then
    unexpectedly_authenticated=1
  fi
  openstack role add --project "${project_a_id}" --user "${user_a_id}" member
  delete_credential_as_admin "${credential_id}"
  unset credential_secret
  if (( unexpectedly_authenticated )); then
    printf 'credential survived removal of its delegated role\n' >&2
    return 1
  fi
}

verify_owner_disable_guard() {
  local expiration
  local credential_json
  local credential_id
  local credential_secret
  local unexpectedly_authenticated=0

  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  credential_json="$(create_lifecycle_credential \
    "coffer-owner-disable-$(date +%s)" "${expiration}")"
  credential_id="$(jq -er '.id // .ID' <<<"${credential_json}")"
  credential_secret="$(jq -er '.secret // .Secret' <<<"${credential_json}")"
  unset credential_json
  credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null

  openstack user set --disable "${user_a_id}"
  if credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null 2>&1; then
    unexpectedly_authenticated=1
  fi
  openstack user set --enable "${user_a_id}"
  delete_credential_as_admin "${credential_id}"
  unset credential_secret
  if (( unexpectedly_authenticated )); then
    printf 'credential survived owner disablement\n' >&2
    return 1
  fi
}

verify_nonproject_scope_isolation() {
  local scope_user_name="coffer-scope-user"
  local scope_user_password
  local scope_user_id
  local existing_user_id
  local unexpected_credential_id=""
  local failure=0

  existing_user_id="$(openstack user show --domain "${domain_a_id}" \
    "${scope_user_name}" -f value -c id 2>/dev/null || true)"
  if [[ -n "${existing_user_id}" ]]; then
    openstack user delete "${existing_user_id}"
  fi
  scope_user_password="$(openssl rand -hex 16)"
  scope_user_id="$(openstack user create --domain "${domain_a_id}" \
    --password "${scope_user_password}" --enable "${scope_user_name}" \
    -f value -c id)"
  openstack role add --domain "${domain_a_id}" --user "${scope_user_id}" reader
  openstack role add --system all --user "${scope_user_id}" admin

  if ! domain_user_openstack "${scope_user_name}" "${scope_user_password}" \
    "${domain_a_id}" "${domain_a_id}" token issue >/dev/null; then
    printf 'domain-scoped token issuance failed\n' >&2
    failure=1
  fi
  if ! system_user_openstack "${scope_user_name}" "${scope_user_password}" \
    "${domain_a_id}" token issue >/dev/null; then
    printf 'system-scoped token issuance failed\n' >&2
    failure=1
  fi

  if isolated_project_user_openstack "${scope_user_name}" \
    "${scope_user_password}" "${domain_a_id}" "${project_a_id}" \
    token issue >/dev/null 2>&1; then
    printf 'domain/system-only user unexpectedly received a project token\n' >&2
    failure=1
  fi
  if unexpected_credential_id="$(domain_user_openstack "${scope_user_name}" \
    "${scope_user_password}" "${domain_a_id}" "${domain_a_id}" \
    application credential create --role reader \
    --expiration "$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)" \
    -f value -c id "coffer-domain-scope" 2>/dev/null)"; then
    delete_credential_as_admin "${unexpected_credential_id}"
    printf 'domain-scoped token unexpectedly created an application credential\n' >&2
    failure=1
  fi
  if unexpected_credential_id="$(system_user_openstack "${scope_user_name}" \
    "${scope_user_password}" "${domain_a_id}" \
    application credential create --role admin \
    --expiration "$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)" \
    -f value -c id "coffer-system-scope" 2>/dev/null)"; then
    delete_credential_as_admin "${unexpected_credential_id}"
    printf 'system-scoped token unexpectedly created an application credential\n' >&2
    failure=1
  fi

  openstack role remove --domain "${domain_a_id}" --user "${scope_user_id}" \
    reader >/dev/null 2>&1 || true
  openstack role remove --system all --user "${scope_user_id}" \
    admin >/dev/null 2>&1 || true
  openstack user delete "${scope_user_id}"
  unset scope_user_password
  return "${failure}"
}

prepare_identities() {
  user_password_a="$(openssl rand -hex 16)"
  user_password_b="$(openssl rand -hex 16)"
  domain_a_id="$(ensure_domain "${domain_a_name}")"
  domain_b_id="$(ensure_domain "${domain_b_name}")"
  project_a_id="$(ensure_project "${domain_a_id}")"
  project_b_id="$(ensure_project "${domain_b_id}")"
  user_a_id="$(ensure_user "${domain_a_id}" "${user_password_a}")"
  user_b_id="$(ensure_user "${domain_b_id}" "${user_password_b}")"
  openstack role add --project "${project_a_id}" --user "${user_a_id}" member
  openstack role add --project "${project_b_id}" --user "${user_b_id}" member
}

verify_matrix() {
  local wrong_ca
  local credential_name
  local expiration
  local credential_json
  local credential_id
  local credential_secret
  local token_project_id

  strict_tls_probe "${ca_file}" >/dev/null
  wrong_ca="$(mktemp)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=coffer-wrong-ca' -keyout "${wrong_ca}.key" \
    -out "${wrong_ca}" >/dev/null 2>&1
  if strict_tls_probe "${wrong_ca}" >/dev/null 2>&1; then
    printf 'Keystone unexpectedly accepted an unrelated CA\n' >&2
    rm -f "${wrong_ca}" "${wrong_ca}.key"
    exit 1
  fi
  rm -f "${wrong_ca}" "${wrong_ca}.key"

  test "${project_a_id}" != "${project_b_id}"
  test "${domain_a_id}" != "${domain_b_id}"
  test "${user_a_id}" != "${user_b_id}"

  token_project_id="$(user_openstack "${user_password_a}" "${domain_a_id}" \
    "${project_a_id}" token issue -f value -c project_id)"
  test "${token_project_id}" = "${project_a_id}"

  credential_name="coffer-lifecycle-$(date +%s)"
  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  credential_json="$(user_openstack "${user_password_a}" "${domain_a_id}" \
    "${project_a_id}" application credential create --role member \
    --expiration "${expiration}" -f json "${credential_name}")"
  credential_id="$(jq -er '.id // .ID' <<<"${credential_json}")"
  credential_secret="$(jq -er '.secret // .Secret' <<<"${credential_json}")"
  unset credential_json

  if ! token_project_id="$(credential_openstack "${credential_id}" \
    "${credential_secret}" token issue -f value -c project_id)"; then
    user_openstack "${user_password_a}" "${domain_a_id}" "${project_a_id}" \
      application credential delete "${credential_id}" >/dev/null 2>&1 || true
    unset credential_secret
    printf 'application credential authentication failed\n' >&2
    return 1
  fi
  if [[ "${token_project_id}" != "${project_a_id}" ]]; then
    user_openstack "${user_password_a}" "${domain_a_id}" "${project_a_id}" \
      application credential delete "${credential_id}" >/dev/null 2>&1 || true
    unset credential_secret
    printf 'application credential returned the wrong project scope\n' >&2
    return 1
  fi
  user_openstack "${user_password_a}" "${domain_a_id}" "${project_a_id}" \
    application credential delete "${credential_id}"
  if credential_openstack "${credential_id}" "${credential_secret}" \
    token issue >/dev/null 2>&1; then
    printf 'deleted application credential unexpectedly authenticated\n' >&2
    exit 1
  fi
  unset credential_secret

  verify_expiration_guard
  verify_role_removal_guard
  verify_owner_disable_guard
  verify_nonproject_scope_isolation

  jq -n \
    --arg endpoint "${auth_url}" \
    --arg domain_a_id "${domain_a_id}" \
    --arg domain_b_id "${domain_b_id}" \
    --arg project_a_id "${project_a_id}" \
    --arg project_b_id "${project_b_id}" \
    --arg user_a_id "${user_a_id}" \
    --arg user_b_id "${user_b_id}" \
    '{endpoint: $endpoint, tls: "verified", wrong_ca: "rejected", duplicate_names: "isolated", application_credential_deletion: "verified", application_credential_expiration: "verified", delegated_role_removal: "invalidated", owner_disablement: "invalidated", domain_scope: "isolated", system_scope: "isolated", domain_a_id: $domain_a_id, domain_b_id: $domain_b_id, project_a_id: $project_a_id, project_b_id: $project_b_id, user_a_id: $user_a_id, user_b_id: $user_b_id}'
}

cleanup_host_fixture() {
  if [[ ! -f "${fixture_file}" ]]; then
    return
  fi
  local password
  local domain_id
  local project_id
  local user_id
  local credential_id
  local temporary_role
  password="$(jq -er '.user_password' "${fixture_file}")"
  domain_id="$(jq -er '.domain_id' "${fixture_file}")"
  project_id="$(jq -er '.project_id' "${fixture_file}")"
  user_id="$(jq -er '.user_id' "${fixture_file}")"
  credential_id="$(jq -er '.application_credential_id' "${fixture_file}")"
  temporary_role="$(jq -r '.temporary_role // empty' "${fixture_file}")"
  user_openstack "${password}" "${domain_id}" "${project_id}" \
    application credential delete "${credential_id}" >/dev/null 2>&1 || true
  if [[ -n "${temporary_role}" ]]; then
    openstack role remove --project "${project_id}" --user "${user_id}" \
      "${temporary_role}" >/dev/null 2>&1 || true
  fi
  rm -f "${fixture_file}"
  unset password
}

prepare_host_fixture() {
  local requested_role="${1:-member}"
  local credential_name
  local expiration
  local credential_json
  local credential_id
  local credential_secret
  local temporary_role=""

  case "${requested_role}" in
    reader|member) ;;
    admin|service)
      openstack role add --project "${project_a_id}" --user "${user_a_id}" \
        "${requested_role}"
      temporary_role="${requested_role}"
      ;;
    *)
      printf 'unsupported host fixture role: %s\n' "${requested_role}" >&2
      return 2
      ;;
  esac

  credential_name="coffer-host-${requested_role}-$(date +%s)"
  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  if ! credential_json="$(user_openstack "${user_password_a}" "${domain_a_id}" \
    "${project_a_id}" application credential create --role "${requested_role}" \
    --expiration "${expiration}" -f json "${credential_name}")"; then
    if [[ -n "${temporary_role}" ]]; then
      openstack role remove --project "${project_a_id}" --user "${user_a_id}" \
        "${temporary_role}" >/dev/null 2>&1 || true
    fi
    return 1
  fi
  credential_id="$(jq -er '.id // .ID' <<<"${credential_json}")"
  credential_secret="$(jq -er '.secret // .Secret' <<<"${credential_json}")"
  unset credential_json

  umask 077
  jq -n \
    --arg application_credential_id "${credential_id}" \
    --arg application_credential_secret "${credential_secret}" \
    --arg project_id "${project_a_id}" \
    --arg user_id "${user_a_id}" \
    --arg user_password "${user_password_a}" \
    --arg domain_id "${domain_a_id}" \
    --arg requested_role "${requested_role}" \
    --arg temporary_role "${temporary_role}" \
    '{application_credential_id: $application_credential_id, application_credential_secret: $application_credential_secret, project_id: $project_id, user_id: $user_id, user_password: $user_password, domain_id: $domain_id, requested_role: $requested_role, temporary_role: $temporary_role}' \
    >"${fixture_file}"
  chmod 600 "${fixture_file}"
  unset credential_secret
  printf '%s\n' "${fixture_file}"
}

delete_host_credential() {
  local password
  local domain_id
  local project_id
  local credential_id
  test -f "${fixture_file}"
  password="$(jq -er '.user_password' "${fixture_file}")"
  domain_id="$(jq -er '.domain_id' "${fixture_file}")"
  project_id="$(jq -er '.project_id' "${fixture_file}")"
  credential_id="$(jq -er '.application_credential_id' "${fixture_file}")"
  user_openstack "${password}" "${domain_id}" "${project_id}" \
    application credential delete "${credential_id}"
  unset password
}

cleanup_registry_fixture() {
  if [[ ! -f "${registry_fixture_file}" ]]; then
    return
  fi

  local fixture_name
  local password
  local domain_id
  local project_id
  local credential_id
  for fixture_name in project_a project_b; do
    password="$(jq -er ".${fixture_name}.user_password" \
      "${registry_fixture_file}")"
    domain_id="$(jq -er ".${fixture_name}.domain_id" \
      "${registry_fixture_file}")"
    project_id="$(jq -er ".${fixture_name}.project_id" \
      "${registry_fixture_file}")"
    credential_id="$(jq -er ".${fixture_name}.application_credential_id" \
      "${registry_fixture_file}")"
    user_openstack "${password}" "${domain_id}" "${project_id}" \
      application credential delete "${credential_id}" >/dev/null 2>&1 || true
    unset password
  done
  rm -f "${registry_fixture_file}"
}

prepare_registry_fixture() {
  local expiration
  local credential_a_json
  local credential_b_json
  local credential_a_id
  local credential_b_id
  local credential_a_secret
  local credential_b_secret

  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  credential_a_json="$(user_openstack "${user_password_a}" "${domain_a_id}" \
    "${project_a_id}" application credential create --role member \
    --expiration "${expiration}" -f json \
    "coffer-registry-a-$(date +%s)")"
  credential_a_id="$(jq -er '.id // .ID' <<<"${credential_a_json}")"
  credential_a_secret="$(jq -er '.secret // .Secret' \
    <<<"${credential_a_json}")"
  unset credential_a_json

  if ! credential_b_json="$(user_openstack "${user_password_b}" \
    "${domain_b_id}" "${project_b_id}" application credential create \
    --role member --expiration "${expiration}" -f json \
    "coffer-registry-b-$(date +%s)")"; then
    user_openstack "${user_password_a}" "${domain_a_id}" "${project_a_id}" \
      application credential delete "${credential_a_id}" >/dev/null 2>&1 || true
    unset credential_a_secret
    return 1
  fi
  credential_b_id="$(jq -er '.id // .ID' <<<"${credential_b_json}")"
  credential_b_secret="$(jq -er '.secret // .Secret' \
    <<<"${credential_b_json}")"
  unset credential_b_json

  umask 077
  jq -n \
    --arg credential_a_id "${credential_a_id}" \
    --arg credential_a_secret "${credential_a_secret}" \
    --arg project_a_id "${project_a_id}" \
    --arg user_a_id "${user_a_id}" \
    --arg user_password_a "${user_password_a}" \
    --arg domain_a_id "${domain_a_id}" \
    --arg credential_b_id "${credential_b_id}" \
    --arg credential_b_secret "${credential_b_secret}" \
    --arg project_b_id "${project_b_id}" \
    --arg user_b_id "${user_b_id}" \
    --arg user_password_b "${user_password_b}" \
    --arg domain_b_id "${domain_b_id}" \
    '{project_a: {application_credential_id: $credential_a_id, application_credential_secret: $credential_a_secret, project_id: $project_a_id, user_id: $user_a_id, user_password: $user_password_a, domain_id: $domain_a_id}, project_b: {application_credential_id: $credential_b_id, application_credential_secret: $credential_b_secret, project_id: $project_b_id, user_id: $user_b_id, user_password: $user_password_b, domain_id: $domain_b_id}}' \
    >"${registry_fixture_file}"
  chmod 600 "${registry_fixture_file}"
  unset credential_a_secret credential_b_secret
  printf '%s\n' "${registry_fixture_file}"
}

cleanup_control_fixture() {
  if [[ ! -f "${control_fixture_file}" ]]; then
    return
  fi
  local scope_user_id
  local service_user_id
  scope_user_id="$(jq -r '.scope_user_id // empty' "${control_fixture_file}")"
  service_user_id="$(jq -r '.service_user_id // empty' "${control_fixture_file}")"
  if [[ -n "${scope_user_id}" ]]; then
    openstack user delete "${scope_user_id}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${service_user_id}" ]]; then
    openstack user delete "${service_user_id}" >/dev/null 2>&1 || true
  fi
  rm -f "${control_fixture_file}"
}

delete_named_user_if_present() {
  local domain_id="$1"
  local username="$2"
  local user_id
  user_id="$(openstack user show --domain "${domain_id}" "${username}" \
    -f value -c id 2>/dev/null || true)"
  if [[ -n "${user_id}" ]]; then
    openstack user delete "${user_id}"
  fi
}

prepare_control_fixture() {
  local scope_user_name="coffer-control-scope"
  local service_user_name="coffer-control-service"
  local scope_user_password
  local service_user_password
  local scope_user_id
  local service_user_id
  local project_token
  local domain_token
  local system_token
  local service_token
  local service_credential_json
  local service_credential_id
  local service_credential_secret
  local expiration

  delete_named_user_if_present "${domain_a_id}" "${scope_user_name}"
  delete_named_user_if_present "${domain_a_id}" "${service_user_name}"
  scope_user_password="$(openssl rand -hex 16)"
  service_user_password="$(openssl rand -hex 16)"
  scope_user_id="$(openstack user create --domain "${domain_a_id}" \
    --password "${scope_user_password}" --enable "${scope_user_name}" \
    -f value -c id)"
  service_user_id="$(openstack user create --domain "${domain_a_id}" \
    --password "${service_user_password}" --enable "${service_user_name}" \
    -f value -c id)"
  umask 077
  jq -n \
    --arg scope_user_id "${scope_user_id}" \
    --arg service_user_id "${service_user_id}" \
    '{scope_user_id: $scope_user_id, service_user_id: $service_user_id}' \
    >"${control_fixture_file}"
  chmod 600 "${control_fixture_file}"
  openstack role add --domain "${domain_a_id}" --user "${scope_user_id}" reader
  openstack role add --system all --user "${scope_user_id}" admin
  openstack role add --project "${project_a_id}" --user "${service_user_id}" \
    service

  project_token="$(user_openstack "${user_password_a}" "${domain_a_id}" \
    "${project_a_id}" token issue -f value -c id)"
  domain_token="$(domain_user_openstack "${scope_user_name}" \
    "${scope_user_password}" "${domain_a_id}" "${domain_a_id}" \
    token issue -f value -c id)"
  system_token="$(system_user_openstack "${scope_user_name}" \
    "${scope_user_password}" "${domain_a_id}" token issue -f value -c id)"
  service_token="$(env -u OS_TOKEN \
    -u OS_USER_DOMAIN_NAME \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_NAME \
    -u OS_DOMAIN_ID \
    -u OS_DOMAIN_NAME \
    -u OS_SYSTEM_SCOPE \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=password \
    OS_USERNAME="${service_user_name}" \
    OS_PASSWORD="${service_user_password}" \
    OS_USER_DOMAIN_ID="${domain_a_id}" \
    OS_PROJECT_ID="${project_a_id}" \
    OS_PROJECT_DOMAIN_ID="${domain_a_id}" \
    OS_CACERT="${ca_file}" \
    openstack token issue -f value -c id)"
  expiration="$(date -u -d '+1 hour' +%Y-%m-%dT%H:%M:%S)"
  service_credential_json="$(env -u OS_TOKEN \
    -u OS_USER_DOMAIN_NAME \
    -u OS_PROJECT_NAME \
    -u OS_PROJECT_DOMAIN_NAME \
    -u OS_DOMAIN_ID \
    -u OS_DOMAIN_NAME \
    -u OS_SYSTEM_SCOPE \
    OS_AUTH_URL="${auth_url}" \
    OS_IDENTITY_API_VERSION=3 \
    OS_AUTH_TYPE=password \
    OS_USERNAME="${service_user_name}" \
    OS_PASSWORD="${service_user_password}" \
    OS_USER_DOMAIN_ID="${domain_a_id}" \
    OS_PROJECT_ID="${project_a_id}" \
    OS_PROJECT_DOMAIN_ID="${domain_a_id}" \
    OS_CACERT="${ca_file}" \
    openstack application credential create --role service \
      --expiration "${expiration}" -f json \
      "coffer-control-middleware-$(date +%s)")"
  service_credential_id="$(jq -er '.id // .ID' <<<"${service_credential_json}")"
  service_credential_secret="$(jq -er '.secret // .Secret' \
    <<<"${service_credential_json}")"
  unset service_credential_json scope_user_password service_user_password

  jq -n \
    --arg project_token "${project_token}" \
    --arg domain_token "${domain_token}" \
    --arg system_token "${system_token}" \
    --arg service_token "${service_token}" \
    --arg project_id "${project_a_id}" \
    --arg user_id "${user_a_id}" \
    --arg scope_user_id "${scope_user_id}" \
    --arg service_user_id "${service_user_id}" \
    --arg service_credential_id "${service_credential_id}" \
    --arg service_credential_secret "${service_credential_secret}" \
    '{project_token: $project_token, domain_token: $domain_token, system_token: $system_token, service_token: $service_token, project_id: $project_id, user_id: $user_id, scope_user_id: $scope_user_id, service_user_id: $service_user_id, service_credential_id: $service_credential_id, service_credential_secret: $service_credential_secret}' \
    >"${control_fixture_file}"
  chmod 600 "${control_fixture_file}"
  unset project_token domain_token system_token service_token
  unset service_credential_secret
  printf '%s\n' "${control_fixture_file}"
}

revoke_control_project_token() {
  local project_token
  test -f "${control_fixture_file}"
  project_token="$(jq -er '.project_token' "${control_fixture_file}")"
  openstack token revoke "${project_token}"
  unset project_token
}

command_name="${1:-matrix}"
load_admin
instance_ip="$(host_ip)"
auth_url="https://${instance_ip}/identity/v3"
ca_file="/opt/stack/data/CA/int-ca/ca-chain.pem"
test -r "${ca_file}"

case "${command_name}" in
  cleanup-host-fixture)
    cleanup_host_fixture
    exit 0
    ;;
  cleanup-control-fixture)
    cleanup_control_fixture
    exit 0
    ;;
  cleanup-registry-fixture)
    cleanup_registry_fixture
    exit 0
    ;;
  revoke-control-project-token)
    revoke_control_project_token
    exit 0
    ;;
  matrix)
    prepare_identities
    ;;
  prepare-host-fixture)
    cleanup_host_fixture
    prepare_identities
    ;;
  delete-host-credential)
    delete_host_credential
    exit 0
    ;;
  prepare-control-fixture)
    cleanup_control_fixture
    prepare_identities
    ;;
  prepare-registry-fixture)
    cleanup_registry_fixture
    prepare_identities
    ;;
  *)
    printf 'unknown command: %s\n' "${command_name}" >&2
    exit 2
    ;;
esac

case "${command_name}" in
  matrix) verify_matrix ;;
  prepare-host-fixture) prepare_host_fixture "${2:-member}" ;;
  prepare-control-fixture) prepare_control_fixture ;;
  prepare-registry-fixture) prepare_registry_fixture ;;
esac
