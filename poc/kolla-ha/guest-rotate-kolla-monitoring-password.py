#!/usr/bin/env python3

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

import yaml


EXPECTED_HOSTNAME = "coffer-kolla-ha-stage5-controller-1"
KOLLA_COMMIT = "cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
PASSWORD_KEY = "rabbitmq_monitoring_password"
STATE_ROOT = Path("/home/ubuntu/coffer-stage5")
PASSWORDS_PATH = Path("/etc/kolla/passwords.yml")


def require_root_only(path: Path) -> None:
    metadata = path.stat()
    if (
        metadata.st_uid != 0
        or metadata.st_gid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise SystemExit(f"owner-only file contract mismatch: {path}")


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("monitoring password rotation requires root")
    if os.uname().nodename != EXPECTED_HOSTNAME:
        raise SystemExit("refusing an unexpected Kolla controller")
    if (STATE_ROOT / "OWNER").read_text(encoding="utf-8").strip() != KOLLA_COMMIT:
        raise SystemExit("Kolla owner marker mismatch")

    for phase in ("bootstrap", "prechecks", "pull"):
        marker = STATE_ROOT / "lifecycle" / f"{phase}.complete"
        require_root_only(marker)
        if marker.read_text(encoding="utf-8").strip() != KOLLA_COMMIT:
            raise SystemExit(f"Kolla lifecycle marker mismatch: {phase}")
    if (STATE_ROOT / "lifecycle" / "deploy.complete").exists():
        raise SystemExit("refusing rotation while deploy is accepted")

    require_root_only(PASSWORDS_PATH)
    original_bytes = PASSWORDS_PATH.read_bytes()
    original = yaml.safe_load(original_bytes)
    old_value = original.get(PASSWORD_KEY)
    if not isinstance(old_value, str) or len(old_value) < 16:
        raise SystemExit("existing monitoring password contract mismatch")

    pattern = re.compile(
        rb"^" + PASSWORD_KEY.encode() + rb":[^\r\n]*(?:\r?\n|$)",
        re.MULTILINE,
    )
    if len(pattern.findall(original_bytes)) != 1:
        raise SystemExit("monitoring password line count mismatch")

    new_value = secrets.token_urlsafe(32)
    if new_value == old_value or len(new_value) < 32 or ":" in new_value:
        raise SystemExit("generated monitoring password contract mismatch")
    replacement = yaml.safe_dump(
        {PASSWORD_KEY: new_value},
        default_flow_style=False,
        sort_keys=False,
    ).encode()
    updated_bytes = pattern.sub(replacement, original_bytes, count=1)
    updated = yaml.safe_load(updated_bytes)
    if updated.get(PASSWORD_KEY) != new_value:
        raise SystemExit("updated monitoring password mismatch")
    if set(updated) != set(original):
        raise SystemExit("password key set changed during rotation")
    for key, value in original.items():
        if key != PASSWORD_KEY and updated[key] != value:
            raise SystemExit(f"unrelated password changed during rotation: {key}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix="passwords.yml.rotate.",
        dir=PASSWORDS_PATH.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, 0o600)
        os.replace(temporary, PASSWORDS_PATH)
        directory_descriptor = os.open(PASSWORDS_PATH.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()

    require_root_only(PASSWORDS_PATH)
    final = yaml.safe_load(PASSWORDS_PATH.read_bytes())
    if final != updated or final[PASSWORD_KEY] == old_value:
        raise SystemExit("monitoring password rotation verification failed")
    print(
        "kolla_password_rotation key=rabbitmq_monitoring_password "
        "backup=none new=generated mode=root-only deploy_marker=absent"
    )


if __name__ == "__main__":
    main()
