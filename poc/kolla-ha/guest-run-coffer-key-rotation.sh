#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {preflight|status|run|rollback}" >&2
    exit 64
fi

action="$1"
case "${action}" in
    preflight|status|run|rollback)
        ;;
    *)
        echo "refusing an unknown Coffer key-rotation action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
source_root="${state_root}/coffer-operator-source"
entrypoint="${source_root}/ansible/kolla-ansible-coffer"
venv="${state_root}/venv"
inventory="/etc/kolla/multinode"
config_root="/etc/kolla"
passwords="${config_root}/passwords.yml"
globals="${config_root}/coffer-globals.yml"
input_root="${config_root}/config/coffer"
secret_root="${input_root}/secrets"
public_root="${input_root}/public"
identity_state="${state_root}/tenant-fixture/identities.json"
repository_state="${state_root}/tenant-acceptance/repository.json"
evidence_file="${state_root}/tenant-acceptance/evidence.json"
rotation_root="${state_root}/key-rotation"
owner_marker="${rotation_root}/owner"
prepared_marker="${rotation_root}/prepared"
overlap_marker="${rotation_root}/overlap"
signer_marker="${rotation_root}/signer"
retired_marker="${rotation_root}/retired"
complete_marker="${rotation_root}/complete"
rollback_marker="${rotation_root}/rollback"
original_root="${rotation_root}/original"
new_root="${rotation_root}/new"
token_root="${rotation_root}/tokens"
log_root="${rotation_root}/logs"
temporary_globals="/run/coffer-stage5-key-rotation-globals.yml"
owner_value="coffer-stage5-key-rotation-v1"
current_kid="stage5-20260724"
new_kid="stage5-20260725"
update_image="localhost/coffer:stage5-quota-retry"
registry_name="registry.coffer.stage5"
registry_url="https://${registry_name}"
kolla_ca="${config_root}/certificates-stage5/ca/root.crt"
backend_ca="${public_root}/backend-ca.crt"
addresses=(
    192.168.252.11
    192.168.252.12
    192.168.252.13
)
deployment_key="/home/ubuntu/.ssh/coffer-stage5-kolla"
known_hosts="/home/ubuntu/.ssh/coffer-stage5-known_hosts"

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test -x "${entrypoint}"
test -x "${venv}/bin/python3"
test "$(stat -c '%U:%G:%a' "${inventory}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${passwords}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${globals}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${identity_state}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${repository_state}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${evidence_file}")" = root:root:600
test "$(stat -c '%U:%G:%a' "${secret_root}/signing-key.pem")" = root:root:600
test "$(stat -c '%U:%G:%a' "${public_root}/jwks.json")" = root:root:644
test ! -e "${temporary_globals}"

ssh_options=(
    -i "${deployment_key}"
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o StrictHostKeyChecking=yes
    -o UserKnownHostsFile="${known_hosts}"
)

write_marker() {
    local marker="$1"
    local value="$2"
    local temporary="${marker}.tmp.$$"

    printf '%s\n' "${value}" >"${temporary}"
    chown root:root "${temporary}"
    chmod 0600 "${temporary}"
    mv -f -- "${temporary}" "${marker}"
}

require_marker() {
    local marker="$1"
    local value="$2"

    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${value}"
}

require_owner() {
    test "$(stat -c '%U:%G:%a' "${rotation_root}")" = root:root:700
    require_marker "${owner_marker}" "${owner_value}"
}

jwks_kids() {
    jq -er '[.keys[].kid] | sort | join(",")' "$1"
}

private_matches_jwks() {
    "${venv}/bin/python3" - "$1" "$2" "$3" <<'PY'
import base64
import json
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization

key_path, jwks_path, expected_kid = sys.argv[1:]
private_key = serialization.load_pem_private_key(
    Path(key_path).read_bytes(), password=None
)
numbers = private_key.public_key().public_numbers()

def decode(value: str) -> int:
    return int.from_bytes(
        base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)),
        "big",
    )

keys = [
    key
    for key in json.loads(Path(jwks_path).read_text()).get("keys", [])
    if key.get("kid") == expected_kid
]
if len(keys) != 1:
    raise SystemExit("expected signing key is not unique in JWKS")
if decode(keys[0]["n"]) != numbers.n or decode(keys[0]["e"]) != numbers.e:
    raise SystemExit("signing private key does not match JWKS")
PY
}

prepare_material() {
    install -d -o root -g root -m 0700 "${rotation_root}"
    write_marker "${owner_marker}" "${owner_value}"
    install -d -o root -g root -m 0700 \
        "${original_root}" "${new_root}" "${token_root}" "${log_root}"
    install -o root -g root -m 0600 \
        "${secret_root}/signing-key.pem" "${original_root}/signing-key.pem"
    install -o root -g root -m 0600 \
        "${public_root}/jwks.json" "${original_root}/jwks.json"
    test "$(jwks_kids "${original_root}/jwks.json")" = "${current_kid}"
    private_matches_jwks \
        "${original_root}/signing-key.pem" \
        "${original_root}/jwks.json" "${current_kid}"
    "${venv}/bin/python3" - \
        "${new_root}/signing-key.pem" \
        "${new_root}/jwks.json" \
        "${new_root}/overlap-jwks.json" \
        "${original_root}/jwks.json" "${new_kid}" <<'PY'
import json
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from coffer.tokens import public_jwk

key_path, jwks_path, overlap_path, original_path = [
    Path(value) for value in sys.argv[1:5]
]
key_id = sys.argv[5]
private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
key_path.write_bytes(
    private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
new_jwk = public_jwk(private_key.public_key(), key_id=key_id)
jwks_path.write_text(
    json.dumps({"keys": [new_jwk]}, sort_keys=True) + "\n",
    encoding="utf-8",
)
old = json.loads(original_path.read_text(encoding="utf-8"))
overlap_path.write_text(
    json.dumps({"keys": old["keys"] + [new_jwk]}, sort_keys=True) + "\n",
    encoding="utf-8",
)
for path in (key_path, jwks_path, overlap_path):
    os.chmod(path, 0o600)
PY
    test "$(jwks_kids "${new_root}/jwks.json")" = "${new_kid}"
    test "$(jwks_kids "${new_root}/overlap-jwks.json")" = \
        "${current_kid},${new_kid}"
    private_matches_jwks \
        "${new_root}/signing-key.pem" \
        "${new_root}/jwks.json" "${new_kid}"
    write_marker "${prepared_marker}" \
        "old=${current_kid} new=${new_kid} lifetime=300"
}

require_material() {
    require_owner
    require_marker "${prepared_marker}" \
        "old=${current_kid} new=${new_kid} lifetime=300"
    for path in \
        "${original_root}/signing-key.pem" \
        "${original_root}/jwks.json" \
        "${new_root}/signing-key.pem" \
        "${new_root}/jwks.json" \
        "${new_root}/overlap-jwks.json"; do
        test "$(stat -c '%U:%G:%a' "${path}")" = root:root:600
    done
    test "$(jwks_kids "${original_root}/jwks.json")" = "${current_kid}"
    test "$(jwks_kids "${new_root}/jwks.json")" = "${new_kid}"
    test "$(jwks_kids "${new_root}/overlap-jwks.json")" = \
        "${current_kid},${new_kid}"
    private_matches_jwks \
        "${original_root}/signing-key.pem" \
        "${original_root}/jwks.json" "${current_kid}"
    private_matches_jwks \
        "${new_root}/signing-key.pem" \
        "${new_root}/jwks.json" "${new_kid}"
}

install_public_jwks() {
    local source="$1"
    local temporary="${public_root}/jwks.json.tmp.$$"

    install -o root -g root -m 0644 "${source}" "${temporary}"
    mv -f -- "${temporary}" "${public_root}/jwks.json"
}

install_private_key() {
    local source="$1"
    local temporary="${secret_root}/signing-key.pem.tmp.$$"

    install -o root -g root -m 0600 "${source}" "${temporary}"
    mv -f -- "${temporary}" "${secret_root}/signing-key.pem"
}

create_globals() {
    local desired_kid="$1"

    test ! -e "${temporary_globals}"
    "${venv}/bin/python3" - \
        "${globals}" "${temporary_globals}" \
        "${desired_kid}" "${update_image}" <<'PY'
from pathlib import Path
import sys
import yaml

source, output, desired_kid, desired_image = sys.argv[1:]
document = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
document["coffer_token_key_id"] = desired_kid
document["coffer_image_full"] = desired_image
Path(output).write_text(
    yaml.safe_dump(document, sort_keys=False),
    encoding="utf-8",
)
PY
    chown root:root "${temporary_globals}"
    chmod 0600 "${temporary_globals}"
    "${venv}/bin/python3" - \
        "${globals}" "${temporary_globals}" \
        "${desired_kid}" "${update_image}" <<'PY'
from pathlib import Path
import sys
import yaml

source, updated, desired_kid, desired_image = sys.argv[1:]
before = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
after = yaml.safe_load(Path(updated).read_text(encoding="utf-8"))
changed = {
    key for key in set(before) | set(after) if before.get(key) != after.get(key)
}
expected = {
    key
    for key, value in {
        "coffer_token_key_id": desired_kid,
        "coffer_image_full": desired_image,
    }.items()
    if before.get(key) != value
}
if changed != expected:
    raise SystemExit("key-rotation globals changed outside the admitted fields")
if (
    after["coffer_token_key_id"] != desired_kid
    or after["coffer_image_full"] != desired_image
):
    raise SystemExit("key-rotation globals selected unexpected values")
PY
}

verify_log() {
    test "$(stat -c '%U:%G:%a' "$1")" = root:root:600
    ! grep -Eiq \
        '(authorization:|application_credential_secret|private key|password[=:])' \
        "$1"
}

run_upgrade() {
    local phase="$1"
    local desired_kid="$2"
    local log="${log_root}/${phase}.log"
    local rc

    create_globals "${desired_kid}"
    cleanup_globals() {
        rm -f -- "${temporary_globals}"
    }
    trap cleanup_globals EXIT
    install -o root -g root -m 0600 /dev/null "${log}"
    set +e
    env \
        PATH="${venv}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
        LC_ALL=C.UTF-8 \
        LANG=C.UTF-8 \
        ANSIBLE_NOCOLOR=1 \
        ANSIBLE_NO_LOG=True \
        ANSIBLE_COLLECTIONS_PATH=/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        KOLLA_ANSIBLE_PYTHON="${venv}/bin/python3" \
        timeout --signal=INT --kill-after=120 7200 \
        "${entrypoint}" upgrade \
        -i "${inventory}" \
        --configdir "${config_root}" \
        --passwords "${passwords}" \
        -e "@${temporary_globals}" \
        -e kolla_serial=1 \
        >"${log}" 2>&1
    rc="$?"
    set -e
    cleanup_globals
    trap - EXIT
    verify_log "${log}"
    if test "${rc}" -ne 0; then
        printf 'coffer_key_rotation ansible=failed phase=%s rc=%s\n' \
            "${phase}" "${rc}" >&2
        return "${rc}"
    fi
}

update_persistent_kid() {
    local desired="$1"
    local temporary="${globals}.tmp.$$"

    "${venv}/bin/python3" - "${globals}" "${temporary}" "${desired}" <<'PY'
from pathlib import Path
import sys
import yaml

source, output, desired = sys.argv[1:]
document = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
document["coffer_token_key_id"] = desired
Path(output).write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
PY
    "${venv}/bin/python3" - "${globals}" "${temporary}" "${desired}" <<'PY'
from pathlib import Path
import sys
import yaml

source, updated, desired = sys.argv[1:]
before = yaml.safe_load(Path(source).read_text(encoding="utf-8"))
after = yaml.safe_load(Path(updated).read_text(encoding="utf-8"))
changed = {
    key for key in set(before) | set(after) if before.get(key) != after.get(key)
}
expected = (
    set()
    if before.get("coffer_token_key_id") == desired
    else {"coffer_token_key_id"}
)
if changed != expected or after.get("coffer_token_key_id") != desired:
    raise SystemExit("persistent globals changed outside the token key ID")
PY
    chown root:root "${temporary}"
    chmod 0644 "${temporary}"
    mv -f -- "${temporary}" "${globals}"
}

runtime_state() {
    local expected_kid="$1"
    local expected_jwks="$2"
    local index
    local snapshot

    for index in "${!addresses[@]}"; do
        snapshot="$(
            if test "${index}" -eq 0; then
                sudo bash -s -- "${expected_kid}" "${expected_jwks}"
            else
                sudo -u ubuntu ssh "${ssh_options[@]}" \
                    "ubuntu@${addresses[${index}]}" \
                    sudo bash -s -- "${expected_kid}" "${expected_jwks}"
            fi <<'REMOTE'
set -Eeuo pipefail
expected_kid="$1"
expected_jwks="$2"
for container in coffer_api coffer_edge coffer_registry; do
    test "$(docker inspect -f '{{.State.Health.Status}}' "${container}")" = healthy
done
test "$(awk -F' = ' '$1 == "key_id" {print $2}' /etc/kolla/coffer-api/coffer.conf)" = \
    "${expected_kid}"
for path in \
    /etc/kolla/coffer-edge/jwks.json \
    /etc/kolla/coffer-registry/jwks.json; do
    actual="$(jq -er '[.keys[].kid] | sort | join(",")' "${path}")"
    test "${actual}" = "${expected_jwks}"
done
printf 'runtime=healthy signer=%s jwks=%s\n' "${expected_kid}" "${expected_jwks}"
REMOTE
        )"
        printf 'coffer_key_rotation_node controller=%s %s\n' \
            "$((index + 1))" "${snapshot}"
    done
}

issue_token() {
    local label="$1"
    local expected_kid="$2"
    local basic="${token_root}/${label}.basic.curl"
    local response="${token_root}/${label}.json"
    local bearer="${token_root}/${label}.bearer.curl"
    local credential_id
    local secret
    local project_id
    local repository_name
    local repository
    local token

    credential_id="$(jq -er '.project_a.application_credential_id' "${identity_state}")"
    secret="$(jq -er '.project_a.application_credential_secret' "${identity_state}")"
    project_id="$(jq -er '.project_a.project_id' "${identity_state}")"
    repository_name="$(jq -er '.repository.name' "${repository_state}")"
    repository="p/${project_id}/${repository_name}"
    printf 'user = "%s:%s"\n' "${credential_id}" "${secret}" >"${basic}"
    chmod 0600 "${basic}"
    curl --disable --fail --silent --show-error \
        --config "${basic}" \
        --cacert "${kolla_ca}" \
        --resolve "${registry_name}:443:192.168.254.10" \
        --output "${response}" \
        --get \
        --data-urlencode 'service=coffer-registry' \
        --data-urlencode "scope=repository:${repository}:pull,push" \
        "${registry_url}/auth/token"
    chmod 0600 "${response}"
    token="$(jq -er '.token' "${response}")"
    printf 'header = "Authorization: Bearer %s"\n' "${token}" >"${bearer}"
    chmod 0600 "${bearer}"
    "${venv}/bin/python3" - \
        "${response}" "${token_root}/${label}.expires" "${expected_kid}" <<'PY'
from pathlib import Path
import sys
import jwt

response, expiry, expected_kid = sys.argv[1:]
token = __import__("json").loads(Path(response).read_text())["token"]
if jwt.get_unverified_header(token).get("kid") != expected_kid:
    raise SystemExit("registry token used an unexpected signing key")
claims = jwt.decode(token, options={"verify_signature": False})
Path(expiry).write_text(str(int(claims["exp"])) + "\n", encoding="utf-8")
PY
    chmod 0600 "${token_root}/${label}.expires"
    unset credential_id secret token
}

make_synthetic_old_token() {
    "${venv}/bin/python3" - \
        "${original_root}/signing-key.pem" \
        "${identity_state}" "${repository_state}" \
        "${token_root}/synthetic-old.bearer.curl" "${current_kid}" <<'PY'
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
import uuid

import jwt
from cryptography.hazmat.primitives import serialization

key_path, identities_path, repository_path, output_path, key_id = sys.argv[1:]
identities = json.loads(Path(identities_path).read_text())
repository_state = json.loads(Path(repository_path).read_text())
project = identities["project_a"]
repository = f"p/{project['project_id']}/{repository_state['repository']['name']}"
now = datetime.now(UTC).replace(microsecond=0)
key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
token = jwt.encode(
    {
        "iss": "coffer",
        "sub": project["user_id"],
        "aud": "coffer-registry",
        "exp": now + timedelta(seconds=300),
        "nbf": now,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "access": [
            {"type": "repository", "name": repository, "actions": ["pull", "push"]}
        ],
    },
    key,
    algorithm="RS256",
    headers={"alg": "RS256", "kid": key_id, "typ": "JWT"},
)
Path(output_path).write_text(
    f'header = "Authorization: Bearer {token}"\n',
    encoding="utf-8",
)
Path(output_path).chmod(0o600)
PY
}

probe_token() {
    local label="$1"
    local expected_registry="$2"
    local expected_edge="$3"
    local bearer="${token_root}/${label}.bearer.curl"
    local project_id
    local repository_name
    local repository
    local manifest
    local address
    local status

    project_id="$(jq -er '.project_a.project_id' "${identity_state}")"
    repository_name="$(jq -er '.repository.name' "${repository_state}")"
    repository="p/${project_id}/${repository_name}"
    manifest="$(jq -er '.manifest_digest' "${evidence_file}")"
    for address in "${addresses[@]}"; do
        status="$(
            curl --disable --silent --show-error \
                --config "${bearer}" --cacert "${backend_ca}" \
                --output /dev/null --write-out '%{http_code}' \
                --head \
                "https://${address}:8789/v2/${repository}/manifests/${manifest}"
        )"
        test "${status}" = "${expected_registry}"
        status="$(
            curl --disable --silent --show-error \
                --config "${bearer}" --cacert "${backend_ca}" \
                --output /dev/null --write-out '%{http_code}' \
                --request PUT \
                --header 'Content-Type: application/vnd.oci.image.manifest.v1+json' \
                --data-binary '{}' \
                "https://${address}:8788/v2/${repository}/manifests/key-rotation-probe"
        )"
        test "${status}" = "${expected_edge}"
    done
    printf 'coffer_key_rotation_probe token=%s registry=%s/3 edge=%s/3\n' \
        "${label}" "${expected_registry}" "${expected_edge}"
}

remove_tokens() {
    find "${token_root}" -mindepth 1 -maxdepth 1 -type f -delete
    test -z "$(find "${token_root}" -mindepth 1 -maxdepth 1 -print)"
}

rotation_state() {
    if test ! -e "${rotation_root}"; then
        printf 'ready\n'
    else
        require_material
        if test -e "${rollback_marker}"; then
            require_marker "${rollback_marker}" "signer=${current_kid} jwks=${current_kid}"
            printf 'rolled-back\n'
        elif test -e "${complete_marker}"; then
            require_marker "${complete_marker}" "signer=${new_kid} jwks=${new_kid}"
            printf 'completed\n'
        elif test -e "${retired_marker}"; then
            printf 'retired\n'
        elif test -e "${signer_marker}"; then
            printf 'signer-switched\n'
        elif test -e "${overlap_marker}"; then
            printf 'overlap\n'
        else
            printf 'prepared\n'
        fi
    fi
}

if test "${action}" = preflight; then
    test ! -e "${rotation_root}"
    test "$(jwks_kids "${public_root}/jwks.json")" = "${current_kid}"
    private_matches_jwks \
        "${secret_root}/signing-key.pem" "${public_root}/jwks.json" "${current_kid}"
    runtime_state "${current_kid}" "${current_kid}"
    printf 'coffer_key_rotation state=ready mutation=none\n'
    exit 0
fi

if test "${action}" = status; then
    state="$(rotation_state)"
    case "${state}" in
        ready)
            runtime_state "${current_kid}" "${current_kid}"
            ;;
        prepared)
            runtime_state "${current_kid}" "${current_kid}"
            ;;
        overlap)
            runtime_state "${current_kid}" "${current_kid},${new_kid}"
            ;;
        signer-switched)
            runtime_state "${new_kid}" "${current_kid},${new_kid}"
            ;;
        retired|completed)
            runtime_state "${new_kid}" "${new_kid}"
            ;;
        rolled-back)
            runtime_state "${current_kid}" "${current_kid}"
            ;;
    esac
    printf 'coffer_key_rotation state=%s mutation=none\n' "${state}"
    exit 0
fi

exec 9>/run/lock/coffer-stage5-key-rotation.lock
if ! flock -n 9; then
    echo "refusing concurrent Coffer key rotation" >&2
    exit 75
fi

if test "${action}" = rollback; then
    require_marker "${complete_marker}" "signer=${new_kid} jwks=${new_kid}"
    if test -e "${rollback_marker}"; then
        require_marker "${rollback_marker}" "signer=${current_kid} jwks=${current_kid}"
        printf 'coffer_key_rotation phase=rollback result=passed idempotent=yes\n'
        exit 0
    fi
    install_public_jwks "${new_root}/overlap-jwks.json"
    run_upgrade rollback-overlap "${new_kid}"
    runtime_state "${new_kid}" "${current_kid},${new_kid}"
    issue_token rollback-new "${new_kid}"
    install_private_key "${original_root}/signing-key.pem"
    run_upgrade rollback-signer "${current_kid}"
    update_persistent_kid "${current_kid}"
    runtime_state "${current_kid}" "${current_kid},${new_kid}"
    issue_token rollback-old "${current_kid}"
    probe_token rollback-new 200 400
    probe_token rollback-old 200 400
    expiry="$(cat "${token_root}/rollback-new.expires")"
    while test "$(date +%s)" -le "$((expiry + 2))"; do
        sleep 5
    done
    install_public_jwks "${original_root}/jwks.json"
    run_upgrade rollback-retire "${current_kid}"
    runtime_state "${current_kid}" "${current_kid}"
    remove_tokens
    write_marker "${rollback_marker}" "signer=${current_kid} jwks=${current_kid}"
    printf 'coffer_key_rotation phase=rollback result=passed signer=%s\n' \
        "${current_kid}"
    exit 0
fi

if test ! -e "${rotation_root}"; then
    prepare_material
fi
require_material
if test -e "${complete_marker}"; then
    require_marker "${complete_marker}" "signer=${new_kid} jwks=${new_kid}"
    runtime_state "${new_kid}" "${new_kid}"
    printf 'coffer_key_rotation phase=run result=passed idempotent=yes\n'
    exit 0
fi

if test ! -e "${overlap_marker}"; then
    install_public_jwks "${new_root}/overlap-jwks.json"
    run_upgrade overlap "${current_kid}"
    runtime_state "${current_kid}" "${current_kid},${new_kid}"
    issue_token old "${current_kid}"
    write_marker "${overlap_marker}" \
        "signer=${current_kid} jwks=${current_kid},${new_kid}"
fi

if test ! -e "${signer_marker}"; then
    install_private_key "${new_root}/signing-key.pem"
    run_upgrade signer "${new_kid}"
    update_persistent_kid "${new_kid}"
    runtime_state "${new_kid}" "${current_kid},${new_kid}"
    issue_token new "${new_kid}"
    probe_token old 200 400
    probe_token new 200 400
    write_marker "${signer_marker}" \
        "signer=${new_kid} jwks=${current_kid},${new_kid}"
fi

if test ! -e "${retired_marker}"; then
    expiry="$(cat "${token_root}/old.expires")"
    while test "$(date +%s)" -le "$((expiry + 2))"; do
        sleep 5
    done
    install_public_jwks "${new_root}/jwks.json"
    run_upgrade retire "${new_kid}"
    runtime_state "${new_kid}" "${new_kid}"
    issue_token retired-new "${new_kid}"
    make_synthetic_old_token
    probe_token retired-new 200 400
    probe_token synthetic-old 401 401
    remove_tokens
    write_marker "${retired_marker}" "signer=${new_kid} jwks=${new_kid}"
fi

test ! -e "${temporary_globals}"
test -z "$(find "${token_root}" -mindepth 1 -maxdepth 1 -print)"
write_marker "${complete_marker}" "signer=${new_kid} jwks=${new_kid}"
printf 'coffer_key_rotation phase=run result=passed signer=%s overlap=yes old_retired=yes\n' \
    "${new_kid}"
