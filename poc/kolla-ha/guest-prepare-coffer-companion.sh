#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

if [[ "$#" -lt 1 ]]; then
    echo "usage: $0 {status|prepare|complete} [GLOBALS RGW_ARCHIVE]" >&2
    exit 64
fi

action="$1"
case "${action}" in
    status|complete)
        test "$#" -eq 1 || exit 64
        ;;
    prepare)
        test "$#" -eq 3 || exit 64
        ;;
    *)
        echo "refusing an unknown Coffer companion preparation action" >&2
        exit 64
        ;;
esac

expected_hostname="coffer-kolla-ha-stage5-controller-1"
state_root="/home/ubuntu/coffer-stage5"
owner_marker="${state_root}/companion.owner"
inputs_marker="${state_root}/companion.inputs-prepared"
complete_marker="${state_root}/companion.prepared"
owner_value="coffer-stage5-companion-v1"
source_commit="4f1ff7ddfd89d21f17ab7cbb531c335e85d94542"
source_root="${state_root}/coffer-source"
image_marker="${state_root}/images.complete"
inventory="/etc/kolla/multinode"
globals="/etc/kolla/coffer-globals.yml"
config_root="/etc/kolla/config"
input_root="/etc/kolla/config/coffer"
secret_root="${input_root}/secrets"
public_root="${input_root}/public"
python_binary="${state_root}/venv/bin/python3"
hostnames=(
    coffer-kolla-ha-stage5-controller-1
    coffer-kolla-ha-stage5-controller-2
    coffer-kolla-ha-stage5-controller-3
)
groups=(
    coffer-api
    coffer-edge
    coffer-registry
    coffer-reconcile
)

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(uname -m)" = x86_64
test -x "${python_binary}"
test "$(git -C "${source_root}" rev-parse HEAD)" = "${source_commit}"
test -z "$(git -C "${source_root}" status --porcelain --untracked-files=all)"
test "$(stat -c '%U:%G:%a' "${image_marker}")" = root:root:600
for phase in deploy reconfigure; do
    test "$(stat -c '%U:%G:%a' "${state_root}/lifecycle/${phase}.complete")" = \
        root:root:600
done

validate_marker() {
    local path="$1"
    local value="$2"

    test "$(stat -c '%U:%G:%a' "${path}")" = root:root:600
    test "$(cat "${path}")" = "${value}"
}

validate_committed_inputs() {
    local name

    validate_marker "${owner_marker}" "${owner_value}"
    validate_marker "${inputs_marker}" "${owner_value}"
    test "$(stat -c '%U:%G:%a' "${globals}")" = root:root:644
    test "$(stat -c '%U:%G:%a' "${input_root}")" = root:root:700
    test "$(stat -c '%U:%G:%a' "${secret_root}")" = root:root:700
    test "$(stat -c '%U:%G:%a' "${public_root}")" = root:root:755
    for name in \
        database-password \
        keystone-service-password \
        signing-key.pem \
        distribution-http-secret \
        rgw-access-key \
        rgw-secret-key \
        backend-ca-key.pem \
        backend-key.pem; do
        test "$(stat -c '%U:%G:%a' "${secret_root}/${name}")" = \
            root:root:600
    done
    for name in jwks.json rgw-ca.crt backend-ca.crt backend.crt; do
        test "$(stat -c '%U:%G:%a' "${public_root}/${name}")" = \
            root:root:644
    done
    openssl pkey -in "${secret_root}/signing-key.pem" \
        -check -noout >/dev/null 2>&1
    openssl verify -CAfile "${public_root}/backend-ca.crt" \
        "${public_root}/backend.crt" >/dev/null
    for address in 192.168.252.10 192.168.252.11 192.168.252.12 192.168.252.13; do
        openssl verify -CAfile "${public_root}/backend-ca.crt" \
            -verify_ip "${address}" "${public_root}/backend.crt" >/dev/null
    done
    openssl x509 -in "${public_root}/rgw-ca.crt" \
        -checkend 86400 -noout >/dev/null

    ANSIBLE_COLLECTIONS_PATH=\
/home/ubuntu/.ansible/collections:/usr/share/ansible/collections \
        "${state_root}/venv/bin/ansible-inventory" \
        -i "${inventory}" --list |
        "${python_binary}" -c '
import json
import sys

document = json.load(sys.stdin)
separator = sys.argv.index("--")
hosts = set(sys.argv[1:separator])
for group in sys.argv[separator + 1:]:
    actual = set(document.get(group, {}).get("hosts", []))
    if actual != hosts:
        raise SystemExit(f"companion inventory mismatch: {group}")
' "${hostnames[@]}" -- "${groups[@]}"
}

if test "${action}" = status; then
    if test -e "${complete_marker}"; then
        validate_marker "${complete_marker}" "${owner_value}"
        validate_committed_inputs
        state=complete
    elif test -e "${inputs_marker}"; then
        validate_committed_inputs
        state=inputs
    else
        if test -e "${owner_marker}"; then
            validate_marker "${owner_marker}" "${owner_value}"
            state=owned
        else
            state=absent
        fi
        test ! -e "${globals}"
        test ! -e "${input_root}"
        for group in "${groups[@]}"; do
            if grep -Fxq "[${group}]" "${inventory}"; then
                echo "unexpected Coffer inventory group: ${group}" >&2
                exit 20
            fi
        done
    fi
    printf 'coffer_companion state=%s runtime=absent database=absent catalog=absent mutation=none\n' \
        "${state}"
    exit 0
fi

if test "${action}" = complete; then
    validate_committed_inputs
    test ! -e "${complete_marker}"
    printf '%s\n' "${owner_value}" >"${complete_marker}"
    chown root:root "${complete_marker}"
    chmod 0600 "${complete_marker}"
    printf 'coffer_companion state=complete marker=root:0600\n'
    exit 0
fi

globals_input="$2"
rgw_archive="$3"
test -f "${globals_input}"
test -f "${rgw_archive}"
test ! -e "${complete_marker}"
if test -e "${inputs_marker}"; then
    validate_committed_inputs
    printf 'coffer_companion state=inputs idempotent=yes\n'
    exit 0
fi
if test -e "${owner_marker}"; then
    validate_marker "${owner_marker}" "${owner_value}"
else
    test ! -e "${globals}"
    test ! -e "${input_root}"
    for group in "${groups[@]}"; do
        if grep -Fxq "[${group}]" "${inventory}"; then
            echo "unexpected Coffer inventory group: ${group}" >&2
            exit 20
        fi
    done
    printf '%s\n' "${owner_value}" >"${owner_marker}"
    chown root:root "${owner_marker}"
    chmod 0600 "${owner_marker}"
fi

temporary="$(mktemp -d /etc/kolla/coffer-stage5.prepare.XXXXXX)"
inventory_changed=false
inputs_installed=false
globals_installed=false
config_root_created=false
committed=false
cleanup() {
    local exit_code=$?

    if test "${committed}" != true; then
        if test "${inventory_changed}" = true; then
            install -o root -g root -m 0644 \
                "${temporary}/multinode.original" "${inventory}"
        fi
        if test "${globals_installed}" = true; then
            rm -f -- "${globals}"
        fi
        if test "${inputs_installed}" = true; then
            rm -rf -- "${input_root}"
        fi
        if test "${config_root_created}" = true; then
            rmdir -- "${config_root}"
        fi
        rm -f -- "${inputs_marker}"
    fi
    if [[ "${temporary}" == /etc/kolla/coffer-stage5.prepare.* ]]; then
        rm -rf -- "${temporary}"
    fi
    exit "${exit_code}"
}
trap cleanup EXIT

install -d -o root -g root -m 0700 "${temporary}/coffer"
install -d -o root -g root -m 0700 "${temporary}/coffer/secrets"
install -d -o root -g root -m 0755 "${temporary}/coffer/public"
install -o root -g root -m 0644 "${globals_input}" \
    "${temporary}/coffer-globals.yml"
install -o root -g root -m 0644 "${inventory}" \
    "${temporary}/multinode.original"

"${python_binary}" - "${rgw_archive}" \
    "${temporary}/coffer/secrets" "${temporary}/coffer/public" <<'PY'
from pathlib import Path
import os
import sys
import tarfile

archive_path = Path(sys.argv[1])
secret_root = Path(sys.argv[2])
public_root = Path(sys.argv[3])
expected = {
    "rgw-access-key": (secret_root / "rgw-access-key", 0o600),
    "rgw-secret-key": (secret_root / "rgw-secret-key", 0o600),
    "rgw-ca.crt": (public_root / "rgw-ca.crt", 0o644),
}
with tarfile.open(archive_path, mode="r:*") as archive:
    members = archive.getmembers()
    if {member.name for member in members} != set(expected):
        raise SystemExit("RGW transfer archive member mismatch")
    for member in members:
        if not member.isfile() or member.size <= 0 or member.size > 1024 * 1024:
            raise SystemExit("RGW transfer archive member is invalid")
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit("RGW transfer archive content is absent")
        path, mode = expected[member.name]
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(stream.read())
PY

for spec in \
    database-password:base64 \
    keystone-service-password:base64 \
    distribution-http-secret:hex; do
    name="${spec%%:*}"
    encoding="${spec##*:}"
    case "${encoding}" in
        base64)
            openssl rand -base64 48 \
                >"${temporary}/coffer/secrets/${name}"
            ;;
        hex)
            openssl rand -hex 32 \
                >"${temporary}/coffer/secrets/${name}"
            ;;
    esac
    chmod 0600 "${temporary}/coffer/secrets/${name}"
done

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
    -out "${temporary}/coffer/secrets/signing-key.pem" >/dev/null 2>&1
openssl req -x509 -newkey rsa:3072 -nodes -sha256 \
    -keyout "${temporary}/coffer/secrets/backend-ca-key.pem" \
    -out "${temporary}/coffer/public/backend-ca.crt" \
    -days 7 \
    -subj "/CN=Coffer Stage 5 backend CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" >/dev/null 2>&1

cat >"${temporary}/backend.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:192.168.252.10,IP:192.168.252.11,IP:192.168.252.12,IP:192.168.252.13,DNS:coffer-kolla-ha-stage5-controller-1,DNS:coffer-kolla-ha-stage5-controller-2,DNS:coffer-kolla-ha-stage5-controller-3
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOF
openssl req -new -newkey rsa:3072 -nodes -sha256 \
    -keyout "${temporary}/coffer/secrets/backend-key.pem" \
    -out "${temporary}/backend.csr" \
    -subj "/CN=192.168.252.10" >/dev/null 2>&1
openssl x509 -req -sha256 -days 7 \
    -in "${temporary}/backend.csr" \
    -CA "${temporary}/coffer/public/backend-ca.crt" \
    -CAkey "${temporary}/coffer/secrets/backend-ca-key.pem" \
    -CAcreateserial \
    -extfile "${temporary}/backend.ext" \
    -out "${temporary}/coffer/public/backend.crt" >/dev/null 2>&1
rm -f -- "${temporary}/coffer/public/backend-ca.srl"

"${python_binary}" - \
    "${temporary}/coffer/secrets/signing-key.pem" \
    "${temporary}/coffer/public/jwks.json" <<'PY'
import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization

private_key_path, output_path = sys.argv[1:]
with open(private_key_path, "rb") as stream:
    public_numbers = serialization.load_pem_private_key(
        stream.read(), password=None
    ).public_key().public_numbers()

def encode(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

document = {
    "keys": [{
        "alg": "RS256",
        "e": encode(public_numbers.e),
        "kid": "stage5-20260724",
        "kty": "RSA",
        "n": encode(public_numbers.n),
        "use": "sig",
    }]
}
with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(document, stream, sort_keys=True)
    stream.write("\n")
os.chmod(output_path, 0o644)
PY

"${python_binary}" - "${inventory}" \
    "${temporary}/multinode.prepared" "${hostnames[@]}" "${groups[@]}" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
output = Path(sys.argv[2])
hosts = sys.argv[3:6]
groups = sys.argv[6:]
text = source.read_text(encoding="utf-8").rstrip() + "\n"
for group in groups:
    if f"[{group}]" in text:
        raise SystemExit(f"companion group already exists: {group}")
sections = []
for group in groups:
    sections.append(f"[{group}]\n" + "\n".join(hosts))
output.write_text(text + "\n" + "\n\n".join(sections) + "\n", encoding="utf-8")
PY
chmod 0644 "${temporary}/multinode.prepared"

for name in \
    signing-key.pem backend-ca-key.pem backend-key.pem \
    database-password keystone-service-password distribution-http-secret \
    rgw-access-key rgw-secret-key; do
    chmod 0600 "${temporary}/coffer/secrets/${name}"
done
for name in jwks.json rgw-ca.crt backend-ca.crt backend.crt; do
    chmod 0644 "${temporary}/coffer/public/${name}"
done
openssl verify -CAfile "${temporary}/coffer/public/backend-ca.crt" \
    -verify_ip 192.168.252.10 \
    "${temporary}/coffer/public/backend.crt" >/dev/null
openssl x509 -in "${temporary}/coffer/public/rgw-ca.crt" \
    -checkend 86400 -noout >/dev/null
"${python_binary}" -m json.tool \
    "${temporary}/coffer/public/jwks.json" >/dev/null
"${python_binary}" - "${temporary}/coffer-globals.yml" <<'PY'
from pathlib import Path
import sys
import yaml

document = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = {
    "enable_coffer": True,
    "coffer_deployment_profile": "production",
    "coffer_enable_reconcile": False,
    "coffer_image_full": "localhost/coffer:stage5",
    "coffer_registry_image_full": "localhost/coffer-registry:stage5",
    "coffer_rgw_endpoint": "https://192.168.253.30:8443",
    "coffer_rgw_bucket": "coffer-stage5-registry",
    "coffer_token_key_id": "stage5-20260724",
}
for name, value in expected.items():
    if document.get(name) != value:
        raise SystemExit(f"Coffer globals mismatch: {name}")
PY

if test -e "${config_root}"; then
    test -d "${config_root}"
    test "$(stat -c '%U:%G:%a' "${config_root}")" = root:root:755
else
    install -d -o root -g root -m 0755 "${config_root}"
    config_root_created=true
fi
test ! -e "${input_root}"
test ! -e "${globals}"
mv "${temporary}/coffer" "${input_root}"
inputs_installed=true
mv "${temporary}/coffer-globals.yml" "${globals}"
globals_installed=true
install -o root -g root -m 0644 \
    "${temporary}/multinode.prepared" "${inventory}"
inventory_changed=true
printf '%s\n' "${owner_value}" >"${inputs_marker}"
chown root:root "${inputs_marker}"
chmod 0600 "${inputs_marker}"

validate_committed_inputs
committed=true
printf 'coffer_companion state=inputs groups=4 hosts=3 secrets=owner-only runtime=absent\n'
