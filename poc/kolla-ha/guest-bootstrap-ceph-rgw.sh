#!/usr/bin/env bash

set -Eeuo pipefail

primary_hostname="coffer-rgw-ha-stage5-storage-1"
hostnames=(
    coffer-rgw-ha-stage5-storage-1
    coffer-rgw-ha-stage5-storage-2
    coffer-rgw-ha-stage5-storage-3
)
storage_addresses=(
    192.168.253.31
    192.168.253.32
    192.168.253.33
)
storage_network="192.168.253.0/24"
rgw_service="rgw.coffer"
ingress_service="ingress.rgw.coffer"
backend_port=9443
frontend_port=8443
monitor_port=1967
ingress_vip="192.168.253.30"
ingress_name="rgw.coffer.stage5"
cert_dir="/etc/ceph/coffer-stage5-ingress"
backend_ca="/etc/ceph/coffer-stage5-rgw-backend-ca.crt"

test "$(id -u)" -eq 0
test "$(hostname)" = "${primary_hostname}"
test -f /etc/ceph/coffer-stage5-release.txt
grep -Fqx 'release=20.2.2' /etc/ceph/coffer-stage5-release.txt
test "$(
    cephadm shell -- ceph quorum_status --format json </dev/null |
        jq '.quorum_names | length'
)" -eq 3
test "$(
    cephadm shell -- ceph orch ps --daemon_type mgr --format json \
        </dev/null |
        jq '[.[] | select(.status_desc == "running")] | length'
)" -eq 2
osd_status="$(
    cephadm shell -- ceph osd stat --format json </dev/null
)"
test "$(jq -r '.num_osds' <<<"${osd_status}")" -eq 3
test "$(jq -r '.num_up_osds' <<<"${osd_status}")" -eq 3
test "$(jq -r '.num_in_osds' <<<"${osd_status}")" -eq 3
test "$(
    cephadm shell -- ceph status --format json </dev/null |
        jq -r '.health.status'
)" = HEALTH_OK

rgw_daemons="$(
    cephadm shell -- ceph orch ps --daemon_type rgw --format json </dev/null
)"
test "$(
    jq --arg service "${rgw_service}" \
        '[.[] | select(.service_name != $service)] | length' \
        <<<"${rgw_daemons}"
)" -eq 0
ingress_daemons="$(
    cephadm shell -- ceph orch ps --format json </dev/null |
        jq '[.[] | select(
            .daemon_type == "haproxy" or .daemon_type == "keepalived"
        )]'
)"
test "$(
    jq --arg service "${ingress_service}" \
        '[.[] | select(.service_name != $service)] | length' \
        <<<"${ingress_daemons}"
)" -eq 0

apply_rgw() {
    cephadm shell -- ceph orch apply -i - "$@" <<EOF
service_type: rgw
service_id: coffer
placement:
  hosts:
    - ${hostnames[0]}
    - ${hostnames[1]}
    - ${hostnames[2]}
networks:
  - ${storage_network}
spec:
  rgw_frontend_port: ${backend_port}
  rgw_frontend_type: beast
  ssl: true
  generate_cert: true
  only_bind_port_on_networks: true
EOF
}

apply_rgw --dry-run --format json-pretty >/dev/null
apply_rgw >/dev/null

for _ in $(seq 1 180); do
    rgw_daemons="$(
        cephadm shell -- ceph orch ps --service_name "${rgw_service}" \
            --format json </dev/null
    )"
    running_rgws="$(
        jq '[.[] | select(
            .daemon_type == "rgw" and .status_desc == "running"
        )] | length' <<<"${rgw_daemons}"
    )"
    if test "${running_rgws}" -eq 3; then
        break
    fi
    sleep 2
done
test "${running_rgws}" -eq 3
test "$(
    jq -r '[.[] | select(
        .daemon_type == "rgw" and .status_desc == "running"
    ) | .hostname] | sort | join(",")' <<<"${rgw_daemons}"
)" = "$(
    printf '%s\n' "${hostnames[@]}" | sort | paste -sd, -
)"

cephadm shell -- ceph orch certmgr cert get cephadm_root_ca_cert \
    </dev/null >"${backend_ca}"
chmod 0644 "${backend_ca}"
openssl x509 -in "${backend_ca}" -noout -checkend 86400

for index in "${!hostnames[@]}"; do
    for _ in $(seq 1 60); do
        backend_status="$(
            curl --silent --show-error --output /dev/null \
                --write-out '%{http_code}' \
                --connect-timeout 3 --max-time 10 \
                --cacert "${backend_ca}" \
                --resolve \
                "${hostnames[$index]}:${backend_port}:${storage_addresses[$index]}" \
                "https://${hostnames[$index]}:${backend_port}/" || true
        )"
        case "${backend_status}" in
            200|403) break ;;
        esac
        sleep 2
    done
    case "${backend_status}" in
        200|403) ;;
        *)
            echo "RGW backend failed verified TLS readiness" >&2
            exit 30
            ;;
    esac
done

install -d -o root -g root -m 0700 "${cert_dir}"
cert_paths=(
    "${cert_dir}/ca.key"
    "${cert_dir}/ca.crt"
    "${cert_dir}/server.key"
    "${cert_dir}/server.crt"
)
present_cert_paths=0
for path in "${cert_paths[@]}"; do
    if test -e "${path}"; then
        present_cert_paths="$((present_cert_paths + 1))"
    fi
done
if test "${present_cert_paths}" -eq 0; then
    temporary_directory="$(mktemp -d)"
    cleanup() {
        rm -rf -- "${temporary_directory}"
    }
    trap cleanup EXIT
    openssl genpkey -algorithm RSA \
        -pkeyopt rsa_keygen_bits:3072 \
        -out "${temporary_directory}/ca.key" 2>/dev/null
    openssl req -new -x509 -sha256 -days 14 \
        -key "${temporary_directory}/ca.key" \
        -subj '/CN=Coffer Stage5 RGW Lab CA' \
        -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' \
        -out "${temporary_directory}/ca.crt"
    openssl genpkey -algorithm RSA \
        -pkeyopt rsa_keygen_bits:3072 \
        -out "${temporary_directory}/server.key" 2>/dev/null
    openssl req -new -sha256 \
        -key "${temporary_directory}/server.key" \
        -subj "/CN=${ingress_name}" \
        -out "${temporary_directory}/server.csr"
    cat >"${temporary_directory}/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:${ingress_name},IP:${ingress_vip}
EOF
    openssl x509 -req -sha256 -days 14 \
        -in "${temporary_directory}/server.csr" \
        -CA "${temporary_directory}/ca.crt" \
        -CAkey "${temporary_directory}/ca.key" \
        -CAcreateserial \
        -extfile "${temporary_directory}/server.ext" \
        -out "${temporary_directory}/server.crt" 2>/dev/null
    install -o root -g root -m 0600 \
        "${temporary_directory}/ca.key" "${cert_dir}/ca.key"
    install -o root -g root -m 0644 \
        "${temporary_directory}/ca.crt" "${cert_dir}/ca.crt"
    install -o root -g root -m 0600 \
        "${temporary_directory}/server.key" "${cert_dir}/server.key"
    install -o root -g root -m 0644 \
        "${temporary_directory}/server.crt" "${cert_dir}/server.crt"
    cleanup
    trap - EXIT
elif test "${present_cert_paths}" -ne 4; then
    echo "refusing an incomplete ingress certificate set" >&2
    exit 31
fi

test "$(stat -c '%a' "${cert_dir}/ca.key")" = 600
test "$(stat -c '%a' "${cert_dir}/server.key")" = 600
openssl x509 -in "${cert_dir}/ca.crt" -noout -checkend 86400
openssl x509 -in "${cert_dir}/server.crt" -noout -checkend 86400
openssl verify -CAfile "${cert_dir}/ca.crt" "${cert_dir}/server.crt" \
    >/dev/null
certificate_sans="$(
    openssl x509 -in "${cert_dir}/server.crt" \
        -noout -ext subjectAltName
)"
grep -Fq "DNS:${ingress_name}" <<<"${certificate_sans}"
grep -Fq "IP Address:${ingress_vip}" <<<"${certificate_sans}"
certificate_public_key="$(
    openssl x509 -in "${cert_dir}/server.crt" -pubkey -noout |
        openssl pkey -pubin -outform DER 2>/dev/null |
        sha256sum | awk '{print $1}'
)"
private_public_key="$(
    openssl pkey -in "${cert_dir}/server.key" -pubout -outform DER \
        2>/dev/null |
        sha256sum | awk '{print $1}'
)"
test "${certificate_public_key}" = "${private_public_key}"

apply_ingress() {
    {
        cat <<EOF
service_type: ingress
service_id: rgw.coffer
placement:
  hosts:
    - ${hostnames[0]}
    - ${hostnames[1]}
networks:
  - ${storage_network}
spec:
  backend_service: ${rgw_service}
  virtual_ip: ${ingress_vip}/24
  virtual_interface_networks:
    - ${storage_network}
  frontend_port: ${frontend_port}
  monitor_port: ${monitor_port}
  health_check_interval: 2s
  use_keepalived_multicast: false
  ssl: true
  ssl_cert: |
EOF
        sed 's/^/    /' "${cert_dir}/server.crt"
        printf '  ssl_key: |\n'
        sed 's/^/    /' "${cert_dir}/server.key"
    } | cephadm shell -- ceph orch apply -i - "$@"
}

apply_ingress --dry-run --format json-pretty >/dev/null
apply_ingress >/dev/null

for _ in $(seq 1 180); do
    ingress_daemons="$(
        cephadm shell -- ceph orch ps \
            --service_name "${ingress_service}" --format json </dev/null
    )"
    running_haproxy="$(
        jq '[.[] | select(
            .daemon_type == "haproxy" and .status_desc == "running"
        )] | length' <<<"${ingress_daemons}"
    )"
    running_keepalived="$(
        jq '[.[] | select(
            .daemon_type == "keepalived" and .status_desc == "running"
        )] | length' <<<"${ingress_daemons}"
    )"
    if test "${running_haproxy}" -eq 2 &&
        test "${running_keepalived}" -eq 2; then
        break
    fi
    sleep 2
done
test "${running_haproxy}" -eq 2
test "${running_keepalived}" -eq 2

for _ in $(seq 1 90); do
    frontend_status="$(
        curl --silent --show-error --output /dev/null \
            --write-out '%{http_code}' \
            --connect-timeout 3 --max-time 10 \
            --cacert "${cert_dir}/ca.crt" \
            --resolve "${ingress_name}:${frontend_port}:${ingress_vip}" \
            "https://${ingress_name}:${frontend_port}/" || true
    )"
    case "${frontend_status}" in
        200|403) break ;;
    esac
    sleep 2
done
case "${frontend_status}" in
    200|403) ;;
    *)
        echo "RGW ingress failed verified TLS readiness" >&2
        exit 32
        ;;
esac
if curl --silent --show-error --output /dev/null \
    --connect-timeout 3 --max-time 10 \
    --resolve "${ingress_name}:${frontend_port}:${ingress_vip}" \
    "https://${ingress_name}:${frontend_port}/" 2>/dev/null; then
    echo "RGW ingress unexpectedly trusted without its CA" >&2
    exit 33
fi
if curl --silent --show-error --output /dev/null \
    --connect-timeout 3 --max-time 10 \
    --resolve "${ingress_name}:${frontend_port}:${ingress_vip}" \
    "http://${ingress_name}:${frontend_port}/" 2>/dev/null; then
    echo "RGW ingress TLS port unexpectedly accepted plaintext HTTP" >&2
    exit 34
fi

for _ in $(seq 1 180); do
    inactive_pgs="$(
        cephadm shell -- ceph pg stat --format json </dev/null |
            jq '[.pg_summary.num_pg_by_state[]? |
                select(.name != "active+clean") | .num] | add // 0'
    )"
    health_status="$(
        cephadm shell -- ceph status --format json </dev/null |
            jq -r '.health.status'
    )"
    if test "${inactive_pgs}" -eq 0 &&
        test "${health_status}" = HEALTH_OK; then
        break
    fi
    sleep 2
done
test "${inactive_pgs}" -eq 0
test "${health_status}" = HEALTH_OK
test "$(
    cephadm shell -- ceph osd pool ls detail --format json </dev/null |
        jq '[.[] | select(.size != 3 or .min_size != 2)] | length'
)" -eq 0
test "$(
    cephadm shell -- radosgw-admin user list --format json </dev/null |
        jq 'length'
)" -eq 0

printf 'ceph_rgw rgw=3 haproxy=2 keepalived=2 vip=%s:%s tls=verified users=0 health=%s\n' \
    "${ingress_vip}" "${frontend_port}" "${health_status}"
