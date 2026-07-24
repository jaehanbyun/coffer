#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 {status|prepare}" >&2
    exit 64
fi

action="$1"
expected_hostname="coffer-kolla-ha-stage5-controller-1"
config_root="/etc/kolla"
globals="${config_root}/globals.yml"
certificate_root="${config_root}/certificates-stage5"
root_ca="${certificate_root}/ca/root.crt"
root_key="${certificate_root}/private/root/root.key"
external_certificate="${certificate_root}/haproxy.pem"
internal_certificate="${certificate_root}/haproxy-internal.pem"
proxysql_ca="${certificate_root}/proxysql-ca.pem"
proxysql_certificate="${certificate_root}/proxysql-cert.pem"
proxysql_key="${certificate_root}/proxysql-key.pem"
marker="/home/ubuntu/coffer-stage5/production-profile.prepared"
legacy_marker_value_v1="coffer-stage5-production-profile-v1"
legacy_marker_value_v2="coffer-stage5-production-profile-v2"
marker_value="coffer-stage5-production-profile-v3"
expected_containers=(
    cron
    fluentd
    haproxy
    keepalived
    keystone
    keystone_fernet
    keystone_ssh
    kolla_toolbox
    mariadb
    memcached
    proxysql
    rabbitmq
)

case "${action}" in
    status|prepare)
        ;;
    *)
        echo "refusing an unknown Kolla production-profile action" >&2
        exit 64
        ;;
esac

test "$(id -u)" -eq 0
test "$(hostname)" = "${expected_hostname}"
test "$(stat -c '%U:%G:%a' "${globals}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${root_ca}")" = root:root:644
test "$(stat -c '%U:%G:%a' "${root_key}")" = root:root:600
openssl x509 -in "${root_ca}" -checkend 86400 -noout >/dev/null
openssl pkey -in "${root_key}" -check -noout >/dev/null 2>&1
test "$(
    openssl x509 -in "${root_ca}" -pubkey -noout |
        openssl pkey -pubin -outform DER 2>/dev/null |
        sha256sum |
        awk '{print $1}'
)" = "$(
    openssl pkey -in "${root_key}" -pubout -outform DER 2>/dev/null |
        sha256sum |
        awk '{print $1}'
)"

runtime_snapshot() {
    local actual_containers

    systemctl is-active --quiet docker
    actual_containers="$(
        docker ps -a --format '{{.Names}}' | sort
    )"
    test "${actual_containers}" = "$(
        printf '%s\n' "${expected_containers[@]}" | sort
    )"
    test "$(
        docker ps -a --format '{{.State}}' |
            awk '$1 != "running" {count += 1} END {print count + 0}'
    )" -eq 0
    test "$(
        docker ps -a --format '{{.Status}}' |
            awk '/\(unhealthy\)/ {count += 1} END {print count + 0}'
    )" -eq 0
    docker inspect \
        --format '{{.Name}} {{.Id}} {{.State.StartedAt}}' \
        "${expected_containers[@]}" |
        sort |
        sha256sum |
        awk '{print $1}'
}

require_no_coffer_state() {
    local path

    for name in \
        coffer_api coffer_edge coffer_registry coffer_reconcile \
        bootstrap_coffer; do
        if docker container inspect "${name}" >/dev/null 2>&1; then
            echo "unexpected Coffer container exists: ${name}" >&2
            exit 20
        fi
    done
    for image in \
        localhost/coffer:stage5 \
        localhost/coffer-registry:stage5; do
        if docker image inspect "${image}" >/dev/null 2>&1; then
            echo "unexpected Coffer pilot image exists" >&2
            exit 21
        fi
    done
    for path in \
        /etc/kolla/config/coffer \
        /etc/kolla/coffer-globals.yml \
        /home/ubuntu/coffer-stage5/coffer-source \
        /etc/kolla/coffer-api \
        /etc/kolla/coffer-edge \
        /etc/kolla/coffer-registry \
        /etc/kolla/coffer-reconcile \
        /etc/kolla/coffer-bootstrap; do
        test ! -e "${path}"
    done
    for port in 8787 8788 8789; do
        if ss -H -lnt |
            awk '{print $4}' |
            grep -Eq "(^|[.:])${port}$"; then
            echo "reserved Coffer port is already listening: ${port}" >&2
            exit 22
        fi
    done
}

validate_globals() {
    local state="$1"

    python3 - "${globals}" "${state}" <<'PY'
from pathlib import Path
import sys

import yaml


path = Path(sys.argv[1])
state = sys.argv[2]
document = yaml.safe_load(path.read_text(encoding="utf-8"))
expected = {
    "kolla_enable_tls_external": True,
    "kolla_internal_fqdn": "192.168.252.10",
    "kolla_external_fqdn": "192.168.254.10",
}
for name, value in expected.items():
    if document.get(name) != value:
        raise SystemExit(f"Kolla globals mismatch: {name}")

if state == "clean":
    if document.get("kolla_enable_tls_internal") is not False:
        raise SystemExit("internal TLS is not in the clean state")
    if bool(document.get("haproxy_single_external_frontend", False)):
        raise SystemExit("single external frontend is unexpectedly enabled")
    if "haproxy_single_external_frontend_public_port" in document:
        raise SystemExit("single frontend port is unexpectedly explicit")
elif state in {"prepared-v2", "prepared"}:
    expected_profile = {
        "kolla_enable_tls_internal": True,
        "haproxy_single_external_frontend": True,
        "haproxy_single_external_frontend_public_port": "443",
    }
    for name, value in expected_profile.items():
        if document.get(name) != value:
            raise SystemExit(f"production profile mismatch: {name}")
    if state == "prepared":
        if document.get("openstack_cacert") != (
            "/etc/ssl/certs/ca-certificates.crt"
        ):
            raise SystemExit("OpenStack container CA bundle path is missing")
    elif "openstack_cacert" in document:
        raise SystemExit("v2 profile unexpectedly has an OpenStack CA path")
else:
    raise SystemExit("unknown globals validation state")
PY
}

validate_certificate() {
    local path="$1"
    local identity_type="$2"
    local identity="$3"

    test "$(stat -c '%U:%G:%a' "${path}")" = root:root:600
    openssl x509 -in "${path}" -checkend 86400 -noout >/dev/null
    openssl verify \
        -CAfile "${root_ca}" \
        "-verify_${identity_type}" "${identity}" \
        "${path}" >/dev/null
}

validate_clean() {
    test ! -e "${marker}"
    test ! -e "${internal_certificate}"
    validate_globals clean
    validate_certificate "${external_certificate}" ip 192.168.254.10
    if openssl verify \
        -CAfile "${root_ca}" \
        -verify_hostname registry.coffer.stage5 \
        "${external_certificate}" >/dev/null 2>&1; then
        echo "external certificate already has the Coffer DNS identity" >&2
        exit 23
    fi
}

validate_prepared() {
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${marker_value}"
    validate_globals prepared
    validate_certificate "${internal_certificate}" ip 192.168.252.10
    validate_certificate "${external_certificate}" ip 192.168.254.10
    validate_certificate \
        "${external_certificate}" hostname registry.coffer.stage5
    test "$(stat -c '%U:%G:%a' "${proxysql_ca}")" = root:root:644
    test "$(stat -c '%U:%G:%a' "${proxysql_certificate}")" = \
        root:root:644
    test "$(stat -c '%U:%G:%a' "${proxysql_key}")" = root:root:600
    cmp --silent "${root_ca}" "${proxysql_ca}"
    openssl verify \
        -CAfile "${proxysql_ca}" \
        -verify_ip 192.168.252.10 \
        "${proxysql_certificate}" >/dev/null
    test "$(
        openssl x509 -in "${proxysql_certificate}" -pubkey -noout |
            openssl pkey -pubin -outform DER 2>/dev/null |
            sha256sum |
            awk '{print $1}'
    )" = "$(
        openssl pkey -in "${proxysql_key}" -pubout -outform DER 2>/dev/null |
            sha256sum |
            awk '{print $1}'
    )"
}

validate_legacy_prepared() {
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${legacy_marker_value_v1}"
    validate_globals prepared-v2
    validate_certificate "${internal_certificate}" ip 192.168.252.10
    validate_certificate "${external_certificate}" ip 192.168.254.10
    validate_certificate \
        "${external_certificate}" hostname registry.coffer.stage5
    test ! -e "${proxysql_ca}"
    test ! -e "${proxysql_certificate}"
    test ! -e "${proxysql_key}"
}

validate_intermediate_prepared() {
    test "$(stat -c '%U:%G:%a' "${marker}")" = root:root:600
    test "$(cat "${marker}")" = "${legacy_marker_value_v2}"
    validate_globals prepared-v2
    validate_certificate "${internal_certificate}" ip 192.168.252.10
    validate_certificate "${external_certificate}" ip 192.168.254.10
    validate_certificate \
        "${external_certificate}" hostname registry.coffer.stage5
    test "$(stat -c '%U:%G:%a' "${proxysql_ca}")" = root:root:644
    test "$(stat -c '%U:%G:%a' "${proxysql_certificate}")" = \
        root:root:644
    test "$(stat -c '%U:%G:%a' "${proxysql_key}")" = root:root:600
    cmp --silent "${root_ca}" "${proxysql_ca}"
    openssl verify \
        -CAfile "${proxysql_ca}" \
        -verify_ip 192.168.252.10 \
        "${proxysql_certificate}" >/dev/null
}

runtime_before="$(runtime_snapshot)"
require_no_coffer_state

if test "${action}" = status; then
    if test -e "${marker}"; then
        case "$(cat "${marker}")" in
            "${marker_value}")
                validate_prepared
                profile_state=prepared
                ;;
            "${legacy_marker_value_v1}")
                validate_legacy_prepared
                echo "Kolla production profile requires ProxySQL TLS inputs" >&2
                exit 78
                ;;
            "${legacy_marker_value_v2}")
                validate_intermediate_prepared
                echo "Kolla production profile requires a container CA path" >&2
                exit 78
                ;;
            *)
                echo "refusing an unknown production-profile marker" >&2
                exit 78
                ;;
        esac
    else
        validate_clean
        profile_state=clean
    fi
    test "$(runtime_snapshot)" = "${runtime_before}"
    printf 'kolla_production_profile state=%s runtime_sha256=%s mutation=none\n' \
        "${profile_state}" "${runtime_before}"
    exit 0
fi

starting_state=clean
if test -e "${marker}"; then
    case "$(cat "${marker}")" in
        "${marker_value}")
            validate_prepared
            test "$(runtime_snapshot)" = "${runtime_before}"
            printf 'kolla_production_profile state=prepared runtime_sha256=%s idempotent=yes reconfigure=not-run\n' \
                "${runtime_before}"
            exit 0
            ;;
        "${legacy_marker_value_v1}")
            validate_legacy_prepared
            starting_state=legacy-v1
            ;;
        "${legacy_marker_value_v2}")
            validate_intermediate_prepared
            starting_state=legacy-v2
            ;;
        *)
            echo "refusing an unknown production-profile marker" >&2
            exit 78
            ;;
    esac
else
    validate_clean
fi

temporary="$(mktemp -d /run/coffer-stage5-profile.XXXXXX)"
changed=0

cleanup_temporary() {
    find "${temporary}" -depth -delete
}

rollback_profile() {
    install -o root -g root -m 0644 \
        "${temporary}/globals.original" "${globals}"
    if test "${starting_state}" = clean; then
        install -o root -g root -m 0600 \
            "${temporary}/external.original" "${external_certificate}"
        rm -f -- \
            "${internal_certificate}" \
            "${proxysql_ca}" \
            "${proxysql_certificate}" \
            "${proxysql_key}" \
            "${marker}"
    elif test "${starting_state}" = legacy-v1; then
        rm -f -- \
            "${proxysql_ca}" \
            "${proxysql_certificate}" \
            "${proxysql_key}"
        printf '%s\n' "${legacy_marker_value_v1}" >"${marker}"
        chown root:root "${marker}"
        chmod 0600 "${marker}"
    else
        printf '%s\n' "${legacy_marker_value_v2}" >"${marker}"
        chown root:root "${marker}"
        chmod 0600 "${marker}"
    fi
}

finish() {
    local rc="$?"

    trap - EXIT
    if test "${rc}" -ne 0 && test "${changed}" -eq 1; then
        rollback_profile
    fi
    cleanup_temporary
    exit "${rc}"
}
trap finish EXIT

install -o root -g root -m 0644 "${globals}" \
    "${temporary}/globals.original"
if test "${starting_state}" = clean; then
    install -o root -g root -m 0600 "${external_certificate}" \
        "${temporary}/external.original"
fi

python3 - \
    "${globals}" \
    "${temporary}/globals.prepared" \
    "${starting_state}" <<'PY'
from pathlib import Path
import sys

import yaml


source = Path(sys.argv[1])
destination = Path(sys.argv[2])
starting_state = sys.argv[3]
text = source.read_text(encoding="utf-8")
before = yaml.safe_load(text)
if starting_state == "clean":
    if text.count("kolla_enable_tls_internal: false") != 1:
        raise SystemExit("expected one disabled internal TLS setting")
    if "haproxy_single_external_frontend:" in text:
        raise SystemExit("single external frontend is already explicit")
    prepared = text.replace(
        "kolla_enable_tls_internal: false",
        "kolla_enable_tls_internal: true",
    )
    prepared += (
        '\nhaproxy_single_external_frontend: true\n'
        'haproxy_single_external_frontend_public_port: "443"\n'
    )
else:
    prepared = text
if "openstack_cacert:" in prepared:
    raise SystemExit("OpenStack CA bundle path is already explicit")
prepared += 'openstack_cacert: "/etc/ssl/certs/ca-certificates.crt"\n'
after = yaml.safe_load(prepared)
changed = {
    key
    for key in before.keys() | after.keys()
    if before.get(key) != after.get(key)
}
expected = {"openstack_cacert"}
if starting_state == "clean":
    expected.update(
        {
            "kolla_enable_tls_internal",
            "haproxy_single_external_frontend",
            "haproxy_single_external_frontend_public_port",
        }
    )
if changed != expected:
    raise SystemExit("Kolla globals mutation exceeded the allowlist")
destination.write_text(prepared, encoding="utf-8")
PY
chmod 0644 "${temporary}/globals.prepared"

generate_leaf() {
    local name="$1"
    local common_name="$2"
    local subject_alt_name="$3"

    openssl req -new -newkey rsa:3072 -nodes -sha256 \
        -keyout "${temporary}/${name}.key" \
        -out "${temporary}/${name}.csr" \
        -subj "/CN=${common_name}" \
        -addext "subjectAltName=${subject_alt_name}" >/dev/null 2>&1
    {
        printf '%s\n' \
            'basicConstraints=critical,CA:FALSE' \
            'keyUsage=critical,digitalSignature,keyEncipherment' \
            'extendedKeyUsage=serverAuth' \
            "subjectAltName=${subject_alt_name}" \
            'subjectKeyIdentifier=hash' \
            'authorityKeyIdentifier=keyid,issuer'
    } >"${temporary}/${name}.ext"
    openssl x509 -req -sha256 -days 14 \
        -in "${temporary}/${name}.csr" \
        -CA "${root_ca}" \
        -CAkey "${root_key}" \
        -CAserial "${temporary}/root.srl" \
        -CAcreateserial \
        -extfile "${temporary}/${name}.ext" \
        -out "${temporary}/${name}.crt" >/dev/null 2>&1
    {
        cat "${temporary}/${name}.crt"
        cat "${temporary}/${name}.key"
    } >"${temporary}/${name}.pem"
    chmod 0600 "${temporary}/${name}.pem"
}

if test "${starting_state}" = clean; then
    generate_leaf \
        internal 192.168.252.10 \
        "IP:192.168.252.10"
    generate_leaf \
        external 192.168.254.10 \
        "IP:192.168.254.10,DNS:registry.coffer.stage5"
elif test "${starting_state}" = legacy-v1; then
    openssl x509 -in "${internal_certificate}" \
        -out "${temporary}/internal.crt"
    openssl pkey -in "${internal_certificate}" \
        -out "${temporary}/internal.key"
fi

if test "${starting_state}" != legacy-v2; then
    install -o root -g root -m 0644 \
        "${root_ca}" "${temporary}/proxysql-ca.pem"
    install -o root -g root -m 0644 \
        "${temporary}/internal.crt" "${temporary}/proxysql-cert.pem"
    install -o root -g root -m 0600 \
        "${temporary}/internal.key" "${temporary}/proxysql-key.pem"
fi

openssl verify \
    -CAfile "${root_ca}" \
    -verify_ip 192.168.254.10 \
    "$(
        if test "${starting_state}" = clean; then
            printf '%s' "${temporary}/external.pem"
        else
            printf '%s' "${external_certificate}"
        fi
    )" >/dev/null
openssl verify \
    -CAfile "${root_ca}" \
    -verify_hostname registry.coffer.stage5 \
    "$(
        if test "${starting_state}" = clean; then
            printf '%s' "${temporary}/external.pem"
        else
            printf '%s' "${external_certificate}"
        fi
    )" >/dev/null
if test "${starting_state}" != legacy-v2; then
    openssl verify \
        -CAfile "${temporary}/proxysql-ca.pem" \
        -verify_ip 192.168.252.10 \
        "${temporary}/proxysql-cert.pem" >/dev/null
fi

changed=1
if test "${starting_state}" = clean; then
    install -o root -g root -m 0600 \
        "${temporary}/internal.pem" "${internal_certificate}"
    install -o root -g root -m 0600 \
        "${temporary}/external.pem" "${external_certificate}"
fi
install -o root -g root -m 0644 \
    "${temporary}/globals.prepared" "${globals}"
if test "${starting_state}" != legacy-v2; then
    install -o root -g root -m 0644 \
        "${temporary}/proxysql-ca.pem" "${proxysql_ca}"
    install -o root -g root -m 0644 \
        "${temporary}/proxysql-cert.pem" "${proxysql_certificate}"
    install -o root -g root -m 0600 \
        "${temporary}/proxysql-key.pem" "${proxysql_key}"
fi
printf '%s\n' "${marker_value}" >"${marker}"
chown root:root "${marker}"
chmod 0600 "${marker}"

validate_prepared
require_no_coffer_state
runtime_after="$(runtime_snapshot)"
test "${runtime_after}" = "${runtime_before}"
changed=0

printf 'kolla_production_profile state=prepared runtime_sha256=%s idempotent=no upgraded_from=%s reconfigure=not-run\n' \
    "${runtime_after}" "${starting_state}"
