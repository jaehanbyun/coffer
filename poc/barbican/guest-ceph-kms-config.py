#!/usr/bin/env python3
"""Apply the bounded RGW KMS config without placing values in process argv."""

from __future__ import annotations

import json
import os
import stat
import sys

import rados


ENV_PATH = "/tmp/coffer-barbican.env"
CONFIG_SECTION = "client.rgw.coffer"
EXPECTED_ENV_KEYS = {
    "COFFER_KMS_USERNAME",
    "COFFER_KMS_USER_PASSWORD",
    "COFFER_KMS_PROJECT",
    "COFFER_KMS_DOMAIN",
    "COFFER_KMS_PROJECT_ID",
    "COFFER_KMS_USER_ID",
    "COFFER_KMS_KEY_ID",
}
CONFIG = {
    "rgw_crypt_s3_kms_backend": "barbican",
    "rgw_crypt_require_ssl": "true",
    "rgw_barbican_url": "https://localhost:19311/key-manager",
    "rgw_keystone_url": "https://localhost:19311/identity",
    "rgw_keystone_verify_ssl": "true",
    "rgw_keystone_barbican_user": "COFFER_KMS_USERNAME",
    "rgw_keystone_barbican_password": "COFFER_KMS_USER_PASSWORD",
    "rgw_keystone_barbican_project": "COFFER_KMS_PROJECT",
    "rgw_keystone_barbican_domain": "COFFER_KMS_DOMAIN",
}


def load_binding() -> dict[str, str]:
    metadata = os.stat(ENV_PATH)
    if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != 0:
        raise RuntimeError("owner-only Barbican binding has unsafe metadata")
    values: dict[str, str] = {}
    with open(ENV_PATH, encoding="utf-8") as binding:
        for raw_line in binding:
            key, separator, value = raw_line.rstrip("\n").partition("=")
            if not separator or not key or key in values or not value:
                raise RuntimeError("invalid owner-only Barbican binding")
            values[key] = value
    if set(values) != EXPECTED_ENV_KEYS:
        raise RuntimeError("unexpected owner-only Barbican binding keys")
    return values


def mon_command(cluster: rados.Rados, command: dict[str, str]) -> None:
    result, _output, _status = cluster.mon_command(
        json.dumps(command, separators=(",", ":")), b""
    )
    if result != 0:
        raise RuntimeError("Ceph rejected the bounded RGW KMS config mutation")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"set", "remove"}:
        raise SystemExit("usage: guest-ceph-kms-config.py {set|remove}")
    binding = load_binding()
    cluster = rados.Rados(conffile="/etc/ceph/ceph.conf")
    cluster.connect()
    try:
        if sys.argv[1] == "set":
            for name, source in CONFIG.items():
                value = binding[source] if source.startswith("COFFER_") else source
                mon_command(
                    cluster,
                    {
                        "prefix": "config set",
                        "who": CONFIG_SECTION,
                        "name": name,
                        "value": value,
                    },
                )
        else:
            for name in CONFIG:
                mon_command(
                    cluster,
                    {"prefix": "config rm", "who": CONFIG_SECTION, "name": name},
                )
    finally:
        cluster.shutdown()
    print(f"Bounded RGW KMS config {sys.argv[1]} completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
