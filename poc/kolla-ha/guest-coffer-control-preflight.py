#!/usr/bin/env python3

from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import stat
import subprocess
import sys
import urllib.request

import yaml


EXPECTED_HOSTS = {
    "coffer-kolla-ha-stage5-controller-1",
    "coffer-kolla-ha-stage5-controller-2",
    "coffer-kolla-ha-stage5-controller-3",
}
PUBLISHED_COMMIT = "4f1ff7ddfd89d21f17ab7cbb531c335e85d94542"
STATE_ROOT = Path("/home/ubuntu/coffer-stage5")
SOURCE_ROOT = STATE_ROOT / "coffer-source"
CONFIG_ROOT = Path("/etc/kolla")
GLOBALS = CONFIG_ROOT / "globals.yml"
PASSWORDS = CONFIG_ROOT / "passwords.yml"
INVENTORY = CONFIG_ROOT / "multinode"
COFFER_GLOBALS = CONFIG_ROOT / "coffer-globals.yml"
COFFER_INPUTS = CONFIG_ROOT / "config/coffer"
CERTIFICATES = CONFIG_ROOT / "certificates-stage5"
ROOT_CA = CERTIFICATES / "ca/root.crt"
EXTERNAL_CERT = CERTIFICATES / "haproxy.pem"
INTERNAL_CERT = CERTIFICATES / "haproxy-internal.pem"
PROXYSQL_CA = CERTIFICATES / "proxysql-ca.pem"
PROXYSQL_CERT = CERTIFICATES / "proxysql-cert.pem"
PROXYSQL_KEY = CERTIFICATES / "proxysql-key.pem"
VENV = STATE_ROOT / "venv"
EXPECTED_GROUPS = (
    "coffer-api",
    "coffer-edge",
    "coffer-registry",
    "coffer-reconcile",
)


def require_regular_file(path: Path, mode: int | None = None) -> None:
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
        raise RuntimeError(f"required regular file is invalid: {path.name}")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise RuntimeError(f"required file owner is invalid: {path.name}")
    if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
        raise RuntimeError(f"required file mode is invalid: {path.name}")


def run(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def effective_hosts(inventory: dict[str, object], group: str) -> set[str]:
    definition = inventory.get(group, {})
    if not isinstance(definition, dict):
        return set()
    result = set(definition.get("hosts", []))
    for child in definition.get("children", []):
        result.update(effective_hosts(inventory, child))
    return result


def load_inventory() -> dict[str, object]:
    environment = os.environ.copy()
    environment["ANSIBLE_COLLECTIONS_PATH"] = (
        "/home/ubuntu/.ansible/collections:/usr/share/ansible/collections"
    )
    result = run(
        [
            str(VENV / "bin/ansible-inventory"),
            "-i",
            str(INVENTORY),
            "--list",
        ],
        env=environment,
    )
    return json.loads(result.stdout)


def validate_certificate(
    path: Path,
    *,
    ip_addresses: tuple[str, ...],
    dns_names: tuple[str, ...] = (),
) -> None:
    require_regular_file(path, 0o600)
    run(["openssl", "x509", "-in", str(path), "-checkend", "86400", "-noout"])
    run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(ROOT_CA),
            str(path),
        ]
    )
    for address in ip_addresses:
        run(
            [
                "openssl",
                "verify",
                "-CAfile",
                str(ROOT_CA),
                "-verify_ip",
                address,
                str(path),
            ]
        )
    for name in dns_names:
        run(
            [
                "openssl",
                "verify",
                "-CAfile",
                str(ROOT_CA),
                "-verify_hostname",
                name,
                str(path),
            ]
        )


def query_database(passwords: dict[str, object]) -> tuple[int, int]:
    password = passwords.get("database_password")
    if not isinstance(password, str) or not password:
        raise RuntimeError("database password is missing")
    query = (
        "SELECT "
        "(SELECT COUNT(*) FROM information_schema.SCHEMATA "
        "WHERE SCHEMA_NAME='coffer'),"
        "(SELECT COUNT(*) FROM mysql.user WHERE User='coffer');"
    )
    result = run(
        [
            "docker",
            "exec",
            "-e",
            f"MYSQL_PWD={password}",
            "mariadb",
            "mariadb",
            "-uroot",
            "-Nse",
            query,
        ]
    )
    fields = result.stdout.strip().split("\t")
    if len(fields) != 2:
        raise RuntimeError("unexpected MariaDB count result")
    return int(fields[0]), int(fields[1])


def keystone_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    context: ssl.SSLContext | None = None,
) -> tuple[dict[str, object], str | None]:
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(
        request,
        context=context,
        timeout=10,
    ) as response:
        return json.load(response), response.headers.get("X-Subject-Token")


def query_keystone(
    globals_document: dict[str, object],
    passwords: dict[str, object],
) -> tuple[int, int]:
    password = passwords.get("keystone_admin_password")
    if not isinstance(password, str) or not password:
        raise RuntimeError("Keystone admin password is missing")
    use_tls = bool(globals_document.get("kolla_enable_tls_internal", False))
    scheme = "https" if use_tls else "http"
    context = (
        ssl.create_default_context(cafile=str(ROOT_CA)) if use_tls else None
    )
    base_url = f"{scheme}://192.168.252.10:5000/v3"
    payload = json.dumps(
        {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": "admin",
                            "domain": {"name": "Default"},
                            "password": password,
                        }
                    },
                },
                "scope": {
                    "project": {
                        "name": "admin",
                        "domain": {"name": "Default"},
                    }
                },
            }
        }
    ).encode()
    _, token = keystone_request(
        f"{base_url}/auth/tokens",
        data=payload,
        headers={"Content-Type": "application/json"},
        context=context,
    )
    if not token:
        raise RuntimeError("Keystone token response is missing a token")
    headers = {"X-Auth-Token": token}
    services, _ = keystone_request(
        f"{base_url}/services?type=oci-registry",
        headers=headers,
        context=context,
    )
    users, _ = keystone_request(
        f"{base_url}/users?name=coffer",
        headers=headers,
        context=context,
    )
    return len(services.get("services", [])), len(users.get("users", []))


def validate_clean(
    globals_document: dict[str, object],
    inventory: dict[str, object],
) -> None:
    if globals_document.get("kolla_enable_tls_internal") is not False:
        raise RuntimeError("clean baseline must retain internal TLS disabled")
    if globals_document.get("kolla_enable_tls_external") is not True:
        raise RuntimeError("external TLS baseline changed")
    if bool(
        globals_document.get("haproxy_single_external_frontend", False)
    ):
        raise RuntimeError("single external frontend is unexpectedly enabled")
    if INTERNAL_CERT.exists():
        raise RuntimeError("internal VIP certificate exists before preparation")
    for path in (COFFER_GLOBALS, COFFER_INPUTS, SOURCE_ROOT):
        if path.exists():
            raise RuntimeError(f"unexpected Coffer preparation state: {path.name}")
    for group in EXPECTED_GROUPS:
        if effective_hosts(inventory, group):
            raise RuntimeError(f"unexpected hosts in Coffer group: {group}")

    validate_certificate(
        EXTERNAL_CERT,
        ip_addresses=("192.168.254.10",),
    )
    result = subprocess.run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(ROOT_CA),
            "-verify_hostname",
            "registry.coffer.stage5",
            str(EXTERNAL_CERT),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        raise RuntimeError("Coffer external DNS SAN exists before preparation")


def validate_ready(
    globals_document: dict[str, object],
    inventory: dict[str, object],
) -> None:
    required_globals = {
        "kolla_enable_tls_internal": True,
        "kolla_enable_tls_external": True,
        "haproxy_single_external_frontend": True,
    }
    for name, value in required_globals.items():
        if globals_document.get(name) is not value:
            raise RuntimeError(f"required Kolla production setting missing: {name}")
    if str(
        globals_document.get(
            "haproxy_single_external_frontend_public_port",
            "443",
        )
    ) != "443":
        raise RuntimeError("single external frontend must use port 443")
    if globals_document.get("kolla_internal_fqdn") != "192.168.252.10":
        raise RuntimeError("internal Kolla FQDN changed")
    if globals_document.get("kolla_external_fqdn") != "192.168.254.10":
        raise RuntimeError("external Kolla FQDN changed")

    require_regular_file(ROOT_CA, 0o644)
    validate_certificate(
        INTERNAL_CERT,
        ip_addresses=("192.168.252.10",),
    )
    validate_certificate(
        EXTERNAL_CERT,
        ip_addresses=("192.168.254.10",),
        dns_names=("registry.coffer.stage5",),
    )
    require_regular_file(PROXYSQL_CA, 0o644)
    require_regular_file(PROXYSQL_CERT, 0o644)
    require_regular_file(PROXYSQL_KEY, 0o600)
    if PROXYSQL_CA.read_bytes() != ROOT_CA.read_bytes():
        raise RuntimeError("ProxySQL CA differs from the Kolla root CA")
    run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(PROXYSQL_CA),
            "-verify_ip",
            "192.168.252.10",
            str(PROXYSQL_CERT),
        ]
    )
    certificate_key = run(
        [
            "openssl",
            "x509",
            "-in",
            str(PROXYSQL_CERT),
            "-pubkey",
            "-noout",
        ]
    ).stdout
    private_key = run(
        [
            "openssl",
            "pkey",
            "-in",
            str(PROXYSQL_KEY),
            "-pubout",
        ]
    ).stdout
    if certificate_key != private_key:
        raise RuntimeError("ProxySQL certificate and key do not match")

    if (
        run(["git", "-C", str(SOURCE_ROOT), "rev-parse", "HEAD"])
        .stdout.strip()
        != PUBLISHED_COMMIT
    ):
        raise RuntimeError("Coffer source commit does not match the baseline")
    require_regular_file(COFFER_GLOBALS, 0o644)
    coffer_globals = yaml.safe_load(COFFER_GLOBALS.read_text(encoding="utf-8"))
    expected_values = {
        "enable_coffer": True,
        "coffer_deployment_profile": "production",
        "coffer_enable_reconcile": False,
        "coffer_enable_metrics": False,
        "coffer_image_full": "localhost/coffer:stage5",
        "coffer_registry_image_full": "localhost/coffer-registry:stage5",
        "coffer_enable_tls_backend": True,
        "kolla_verify_tls_backend": True,
        "coffer_internal_fqdn": "192.168.252.10",
        "coffer_external_fqdn": "registry.coffer.stage5",
        "coffer_rgw_endpoint": "https://192.168.253.30:8443",
        "coffer_rgw_bucket": "coffer-stage5-registry",
        "coffer_rgw_skip_verify": False,
        "coffer_token_key_id": "stage5-20260724",
    }
    for name, value in expected_values.items():
        if coffer_globals.get(name) != value:
            raise RuntimeError(f"Coffer deployment input mismatch: {name}")

    secret_root = COFFER_INPUTS / "secrets"
    public_root = COFFER_INPUTS / "public"
    if stat.S_IMODE(secret_root.stat().st_mode) != 0o700:
        raise RuntimeError("Coffer secret directory mode is invalid")
    if secret_root.stat().st_uid != 0 or secret_root.stat().st_gid != 0:
        raise RuntimeError("Coffer secret directory owner is invalid")
    for name in (
        "database-password",
        "keystone-service-password",
        "signing-key.pem",
        "distribution-http-secret",
        "rgw-access-key",
        "rgw-secret-key",
        "backend-ca-key.pem",
        "backend-key.pem",
    ):
        require_regular_file(secret_root / name, 0o600)
    for name in (
        "jwks.json",
        "rgw-ca.crt",
        "backend-ca.crt",
        "backend.crt",
    ):
        require_regular_file(public_root / name, 0o644)
    run(
        [
            "openssl",
            "pkey",
            "-in",
            str(secret_root / "signing-key.pem"),
            "-check",
            "-noout",
        ]
    )
    backend_certificate = public_root / "backend.crt"
    run(
        [
            "openssl",
            "verify",
            "-CAfile",
            str(public_root / "backend-ca.crt"),
            str(backend_certificate),
        ]
    )
    for address in (
        "192.168.252.10",
        "192.168.252.11",
        "192.168.252.12",
        "192.168.252.13",
    ):
        run(
            [
                "openssl",
                "verify",
                "-CAfile",
                str(public_root / "backend-ca.crt"),
                "-verify_ip",
                address,
                str(backend_certificate),
            ]
        )
    jwks = json.loads((public_root / "jwks.json").read_text(encoding="utf-8"))
    matching_keys = [
        key
        for key in jwks.get("keys", [])
        if key.get("kty") == "RSA"
        and key.get("kid") == "stage5-20260724"
    ]
    if len(matching_keys) != 1:
        raise RuntimeError("Coffer JWKS does not contain the exact pilot key")

    for group in EXPECTED_GROUPS:
        if effective_hosts(inventory, group) != EXPECTED_HOSTS:
            raise RuntimeError(f"Coffer inventory group mismatch: {group}")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"clean", "ready"}:
        raise SystemExit("usage: guest-coffer-control-preflight.py {clean|ready}")
    action = sys.argv[1]
    if os.geteuid() != 0:
        raise RuntimeError("Coffer control preflight requires root")
    if os.uname().nodename != "coffer-kolla-ha-stage5-controller-1":
        raise RuntimeError("Coffer control preflight ran on the wrong host")

    require_regular_file(GLOBALS, 0o644)
    require_regular_file(PASSWORDS, 0o600)
    require_regular_file(INVENTORY, 0o644)
    require_regular_file(ROOT_CA, 0o644)
    globals_document = yaml.safe_load(GLOBALS.read_text(encoding="utf-8"))
    passwords = yaml.safe_load(PASSWORDS.read_text(encoding="utf-8"))
    inventory = load_inventory()

    if action == "clean":
        validate_clean(globals_document, inventory)
    else:
        validate_ready(globals_document, inventory)

    database_count, database_user_count = query_database(passwords)
    service_count, service_user_count = query_keystone(
        globals_document,
        passwords,
    )
    if (database_count, database_user_count) != (0, 0):
        raise RuntimeError("Coffer database state exists before deployment")
    if (service_count, service_user_count) != (0, 0):
        raise RuntimeError("Coffer Keystone state exists before deployment")

    print(
        "coffer_control_preflight "
        f"action={action} database=absent database_user=absent "
        "keystone_service=absent keystone_user=absent "
        f"inventory={'clean' if action == 'clean' else 'ready'} "
        f"production_profile={'pending' if action == 'clean' else 'ready'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
