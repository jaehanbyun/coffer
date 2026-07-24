from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import yaml

from prepare_fixture import prepare
from verify import (
    ANSIBLE_PLAYBOOK,
    CAPTURED_OUTPUTS,
    GENERATED_SECRETS,
    HARNESS,
    KOLLA,
    ROOT,
    WORK,
    contract_environment,
    remember_generated_secrets,
)


REMOTE_ROOT = "/tmp/coffer-stage3-contract"
REMOTE_ANSIBLE_TMP = "/tmp/coffer-stage3-ansible"


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def ssh_command(remote_command: str) -> list[str]:
    jump_host = required_environment("COFFER_STAGE3_JUMP_HOST")
    guest_host = required_environment("COFFER_STAGE3_GUEST_HOST")
    known_hosts = required_environment("COFFER_STAGE3_KNOWN_HOSTS")
    return [
        "ssh",
        "-J",
        jump_host,
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        f"ubuntu@{guest_host}",
        remote_command,
    ]


def run_ssh(remote_command: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ssh_command(remote_command),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    CAPTURED_OUTPUTS.append(result.stdout + result.stderr)
    if result.returncode != 0:
        raise AssertionError(
            f"remote command failed with {result.returncode}: "
            f"{remote_command}\n{result.stdout}{result.stderr}"
        )
    return result


def prepare_remote_inventory() -> Path:
    jump_host = required_environment("COFFER_STAGE3_JUMP_HOST")
    guest_host = required_environment("COFFER_STAGE3_GUEST_HOST")
    known_hosts = required_environment("COFFER_STAGE3_KNOWN_HOSTS")
    inventory = {
        "all": {
            "hosts": {
                "coffer-stage3-validation": {
                    "ansible_become": True,
                    "ansible_connection": "ssh",
                    "ansible_host": guest_host,
                    "ansible_python_interpreter": "/usr/bin/python3",
                    "ansible_ssh_common_args": (
                        f"-o ProxyJump={jump_host} "
                        "-o BatchMode=yes "
                        "-o StrictHostKeyChecking=yes "
                        f"-o UserKnownHostsFile={known_hosts}"
                    ),
                    "ansible_user": "ubuntu",
                }
            },
            "children": {
                "coffer": {
                    "children": {
                        "coffer-api": {},
                        "coffer-edge": {},
                        "coffer-reconcile": {},
                        "coffer-registry": {},
                    }
                },
                "coffer-api": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "coffer-edge": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "coffer-reconcile": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "coffer-registry": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "cron": {},
                "fluentd": {},
                "loadbalancer": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "mariadb": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
                "prometheus": {},
                "tls-backend": {
                    "hosts": {"coffer-stage3-validation": {}}
                },
            },
        }
    }
    inventory_path = WORK / "inventory-remote.yml"
    inventory_path.write_text(
        yaml.safe_dump(inventory, sort_keys=False),
        encoding="utf-8",
    )

    runtime_path = WORK / "runtime-vars.yml"
    runtime = yaml.safe_load(runtime_path.read_text(encoding="utf-8"))
    runtime.pop("ansible_become_exe", None)
    runtime.update(
        {
            "api_interface": "ens3",
            "ansible_python_interpreter": "/usr/bin/python3",
            "config_owner_group": "ubuntu",
            "config_owner_user": "ubuntu",
            "node_config": f"{REMOTE_ROOT}/kolla-config",
            "node_config_directory": f"{REMOTE_ROOT}/target-config",
        }
    )
    runtime_path.write_text(
        yaml.safe_dump(runtime, sort_keys=True),
        encoding="utf-8",
    )
    runtime_path.chmod(0o600)
    return inventory_path


def run_action(
    inventory: Path,
    action: str,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(ANSIBLE_PLAYBOOK),
        "-i",
        str(inventory),
        str(ROOT / "ansible" / "coffer.yml"),
        "-e",
        f"@{HARNESS / 'globals.yml'}",
        "-e",
        f"@{HARNESS / 'passwords.yml'}",
        "-e",
        f"@{WORK / 'runtime-vars.yml'}",
        "-e",
        f"coffer_kolla_ansible_data_path={KOLLA / 'ansible'}",
        "-e",
        f"coffer_source_root={ROOT}",
        "-e",
        f"kolla_action={action}",
    ]
    environment = contract_environment()
    environment["ANSIBLE_FILTER_PLUGINS"] = str(
        KOLLA / "ansible" / "filter_plugins"
    )
    environment["ANSIBLE_REMOTE_TMP"] = REMOTE_ANSIBLE_TMP
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    combined = result.stdout + result.stderr
    CAPTURED_OUTPUTS.append(combined)
    if result.returncode != 0:
        raise AssertionError(
            f"remote {action} failed with {result.returncode}:\n"
            + "\n".join(combined.splitlines()[-60:])
        )
    return result


def verify_remote_state() -> None:
    result = run_ssh(
        f"sudo cat {REMOTE_ROOT}/state.json; "
        f"sudo cat {REMOTE_ROOT}/events.jsonl"
    )
    lines = result.stdout.splitlines()
    state_end = next(
        index
        for index, line in enumerate(lines)
        if line == "}" and index > 0
    )
    state = json.loads("\n".join(lines[: state_end + 1]))
    events = [json.loads(line) for line in lines[state_end + 1 :] if line]
    assert set(state["containers"]) >= {
        "haproxy",
        "coffer_api",
        "coffer_edge",
        "coffer_registry",
    }
    bootstrap_index = next(
        index
        for index, event in enumerate(events)
        if event.get("action") == "start_container"
        and event.get("name") == "bootstrap_coffer"
    )
    process_indexes = [
        index
        for index, event in enumerate(events)
        if event.get("action") == "recreate_or_restart_container"
        and event.get("name")
        in {"coffer_api", "coffer_edge", "coffer_registry"}
    ]
    assert process_indexes and bootstrap_index < min(process_indexes)

    permissions = run_ssh(
        f"sudo find {REMOTE_ROOT}/target-config -type f "
        "-printf '%m %p\\n' | sort"
    ).stdout
    for path in (
        "coffer-api/coffer.conf",
        "coffer-api/signing-key.pem",
        "coffer-edge/coffer.conf",
        "coffer-registry/config.yml",
        "coffer-bootstrap/coffer.conf",
    ):
        assert re.search(
            rf"^600 {re.escape(REMOTE_ROOT)}/target-config/{re.escape(path)}$",
            permissions,
            re.MULTILINE,
        )


def verify_secret_safe_outputs() -> None:
    output = "\n".join(CAPTURED_OUTPUTS)
    leaked = [
        value
        for value in GENERATED_SECRETS
        if value and value in output
    ]
    if leaked:
        raise AssertionError("generated secret appeared in remote output")


def main() -> None:
    prepare()
    remember_generated_secrets()
    inventory = prepare_remote_inventory()
    try:
        run_ssh(
            f"sudo install -d -m 0700 {REMOTE_ROOT}; "
            f"install -d -m 0700 {REMOTE_ANSIBLE_TMP}; "
            "sudo install -d -o ubuntu -g ubuntu -m 0770 "
            f"{REMOTE_ROOT}/target-config/haproxy/services.d "
            f"{REMOTE_ROOT}/target-config/proxysql/users "
            f"{REMOTE_ROOT}/target-config/proxysql/rules; "
            f"sudo sh -c 'python3 -m http.server 61313 "
            f"--bind 127.0.0.1 >{REMOTE_ROOT}/readiness.log 2>&1 "
            f"& echo $! >{REMOTE_ROOT}/readiness.pid'"
        )
        run_action(inventory, "precheck")
        run_action(inventory, "deploy")
        verify_remote_state()
        reconfigure = run_action(inventory, "reconfigure")
        assert re.search(r"changed=0\b", reconfigure.stdout)
        run_action(inventory, "pull")
        run_action(inventory, "upgrade")
        run_action(inventory, "stop")
        stopped_state = json.loads(
            run_ssh(f"sudo cat {REMOTE_ROOT}/state.json").stdout
        )
        assert not {
            "coffer_api",
            "coffer_edge",
            "coffer_registry",
        }.intersection(stopped_state["containers"])
        verify_secret_safe_outputs()
    finally:
        run_ssh(
            f"sudo pkill -F {REMOTE_ROOT}/readiness.pid 2>/dev/null || true; "
            f"sudo rm -rf -- {REMOTE_ROOT}; "
            f"rm -rf -- {REMOTE_ANSIBLE_TMP}"
        )
        shutil.rmtree(WORK, ignore_errors=True)

    residue = run_ssh(
        f"test ! -e {REMOTE_ROOT} && "
        f"test ! -e {REMOTE_ANSIBLE_TMP} && "
        "test \"$(hostname)\" = coffer-kolla-stage3"
    )
    assert residue.returncode == 0
    print("Coffer Kolla role remote contract: passed")


if __name__ == "__main__":
    main()
