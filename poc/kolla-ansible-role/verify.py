from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import subprocess
import threading
from typing import Iterator

import yaml

from prepare_fixture import prepare


ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
WORK = HARNESS / "work"
KOLLA = ROOT / "work" / "kolla-ansible-stage3"
ANSIBLE_PLAYBOOK = KOLLA / ".venv" / "bin" / "ansible-playbook"
PIN = (ROOT / "ansible" / "KOLLA_ANSIBLE_COMMIT").read_text().strip()

CAPTURED_OUTPUTS: list[str] = []
GENERATED_SECRETS: set[str] = set()
PASSED_CHECKS: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    PASSED_CHECKS.append(message)


def remember_generated_secrets() -> dict[str, str]:
    secret_dir = WORK / "source-config" / "coffer" / "secrets"
    values = {
        path.name: path.read_text(encoding="utf-8").strip()
        for path in secret_dir.iterdir()
        if path.name != "signing-key.pem"
    }
    GENERATED_SECRETS.update(values.values())
    return values


def contract_environment(
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "ANSIBLE_ACTION_PLUGINS": str(
                KOLLA / "ansible" / "action_plugins"
            ),
            "ANSIBLE_DISPLAY_SKIPPED_HOSTS": "false",
            "ANSIBLE_FILTER_PLUGINS": os.pathsep.join(
                [
                    str(HARNESS / "filter_plugins"),
                    str(KOLLA / "ansible" / "filter_plugins"),
                ]
            ),
            "ANSIBLE_LIBRARY": os.pathsep.join(
                [
                    str(HARNESS / "library"),
                    str(KOLLA / "ansible" / "library"),
                ]
            ),
            "ANSIBLE_LOCAL_TEMP": "/private/tmp/coffer-stage3-ansible/local",
            "ANSIBLE_MODULE_UTILS": os.pathsep.join(
                [
                    str(HARNESS / "module_utils"),
                    str(KOLLA / "ansible" / "module_utils"),
                ]
            ),
            "ANSIBLE_REMOTE_TMP": "/private/tmp/coffer-stage3-ansible/remote",
            "ANSIBLE_ROLES_PATH": os.pathsep.join(
                [
                    str(ROOT / "ansible" / "roles"),
                    str(KOLLA / "ansible" / "roles"),
                ]
            ),
            "COFFER_KOLLA_EVENT_FILE": str(WORK / "events.jsonl"),
            "COFFER_KOLLA_STATE_FILE": str(WORK / "state.json"),
            "PATH": os.pathsep.join(
                [
                    str(WORK / "bin"),
                    environment.get("PATH", ""),
                ]
            ),
        }
    )
    if extra:
        environment.update(extra)
    return environment


def action_command(action: str, *extra_arguments: str) -> list[str]:
    return [
        str(ANSIBLE_PLAYBOOK),
        "-i",
        str(HARNESS / "inventory.yml"),
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
        *extra_arguments,
    ]


def run_action(
    action: str,
    *extra_arguments: str,
    expect_success: bool = True,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        action_command(action, *extra_arguments),
        cwd=ROOT,
        env=contract_environment(extra_environment),
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    combined = result.stdout + result.stderr
    CAPTURED_OUTPUTS.append(combined)
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"{action} unexpectedly failed with {result.returncode}:\n"
            + "\n".join(combined.splitlines()[-40:])
        )
    if not expect_success and result.returncode == 0:
        raise AssertionError(f"{action} unexpectedly passed")
    return result


class _ReadinessHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        return


class _ReadinessServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextmanager
def listening(port: int) -> Iterator[None]:
    server = _ReadinessServer(("127.0.0.1", port), _ReadinessHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def state() -> dict:
    return json.loads((WORK / "state.json").read_text(encoding="utf-8"))


def events() -> list[dict]:
    return [
        json.loads(line)
        for line in (WORK / "events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line
    ]


def assert_failure_case(
    name: str,
    mutate,
    *extra_arguments: str,
) -> None:
    prepare()
    remember_generated_secrets()
    mutate()
    result = run_action(
        "precheck",
        *extra_arguments,
        expect_success=False,
    )
    check("failed=1" in result.stdout, f"negative precheck: {name}")


def verify_pin_and_syntax() -> None:
    check(
        re.fullmatch(r"[0-9a-f]{40}", PIN) is not None,
        "Kolla-Ansible pin is an exact commit",
    )
    check((KOLLA / ".git").exists(), "pinned Kolla checkout exists")
    checkout_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=KOLLA,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    check(checkout_head == PIN, "Kolla checkout matches the recorded pin")
    check(ANSIBLE_PLAYBOOK.is_file(), "isolated Ansible runtime exists")

    prepare()
    remember_generated_secrets()
    for action in (
        "precheck",
        "deploy",
        "reconfigure",
        "pull",
        "upgrade",
        "stop",
        "config_validate",
    ):
        run_action(action, "--syntax-check")
    check(True, "all required lifecycle actions pass syntax-check")


def verify_wrapper_contract() -> None:
    fake_kolla = WORK / "bin" / "kolla-ansible"
    argument_file = WORK / "wrapper-arguments.txt"
    fake_kolla.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\" >\"${COFFER_WRAPPER_ARGUMENT_FILE}\"\n",
        encoding="utf-8",
    )
    fake_kolla.chmod(0o755)
    environment = os.environ.copy()
    environment.update(
        {
            "COFFER_WRAPPER_ARGUMENT_FILE": str(argument_file),
            "KOLLA_ANSIBLE_PYTHON": str(KOLLA / ".venv" / "bin" / "python3"),
            "PATH": os.pathsep.join(
                [str(WORK / "bin"), environment.get("PATH", "")]
            ),
        }
    )
    wrapper = ROOT / "ansible" / "kolla-ansible-coffer"
    result = subprocess.run(
        [
            str(wrapper),
            "deploy",
            "-i",
            "/contract/inventory",
            "--check",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    CAPTURED_OUTPUTS.append(result.stdout + result.stderr)
    check(
        result.returncode == 0,
        "operator wrapper accepts action-first syntax: "
        f"rc={result.returncode}, output={(result.stdout + result.stderr).strip()!r}",
    )
    arguments = argument_file.read_text(encoding="utf-8").splitlines()
    check(
        arguments
        == [
            "deploy",
            "-p",
            str(ROOT / "ansible" / "coffer.yml"),
            "-e",
            f"coffer_kolla_ansible_data_path={KOLLA / 'ansible'}",
            "-e",
            f"coffer_source_root={ROOT}",
            "-i",
            "/contract/inventory",
            "--check",
        ],
        "operator wrapper injects its playbook before user action arguments",
    )
    argument_file.unlink()
    refusal = subprocess.run(
        [str(wrapper), "destroy"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    CAPTURED_OUTPUTS.append(refusal.stdout + refusal.stderr)
    check(
        refusal.returncode == 64 and not argument_file.exists(),
        "operator wrapper refuses destructive unrelated Kolla actions",
    )


def verify_disabled_and_negative_prechecks() -> None:
    prepare()
    remember_generated_secrets()
    run_action("deploy", "-e", "enable_coffer=false")
    disabled_state = state()
    check(
        disabled_state == {"containers": {}, "operations": []},
        "enable_coffer=false is a deployment no-op",
    )

    secret = (
        lambda name: WORK
        / "source-config"
        / "coffer"
        / "secrets"
        / name
    )
    assert_failure_case(
        "missing secret",
        lambda: secret("database-password").unlink(),
    )
    assert_failure_case(
        "unsafe secret permission",
        lambda: secret("database-password").chmod(0o644),
    )
    assert_failure_case(
        "plaintext RGW endpoint",
        lambda: None,
        "-e",
        "coffer_rgw_endpoint=http://rgw.example.test:8080",
    )
    assert_failure_case(
        "backend TLS disabled",
        lambda: None,
        "-e",
        "coffer_enable_tls_backend=false",
    )
    assert_failure_case(
        "direct registry bypass",
        lambda: None,
        "-e",
        "coffer_registry_external=true",
    )

    prepare()
    remember_generated_secrets()
    with listening(18787):
        result = run_action("precheck", expect_success=False)
    check("failed=1" in result.stdout, "occupied backend port is rejected")


def verify_bootstrap_failure() -> None:
    prepare()
    remember_generated_secrets()
    result = run_action(
        "deploy",
        expect_success=False,
        extra_environment={"COFFER_STUB_FAIL_BOOTSTRAP": "1"},
    )
    failed_state = state()
    coffer_containers = {
        "coffer_api",
        "coffer_edge",
        "coffer_registry",
        "coffer_reconcile",
    }
    check(
        not coffer_containers.intersection(failed_state["containers"]),
        "bootstrap failure prevents Coffer process rollout",
    )
    failed_events = events()
    check(
        not any(
            event.get("action") == "recreate_or_restart_container"
            and event.get("name") in coffer_containers
            for event in failed_events
        ),
        "bootstrap failure emits no Coffer restart event",
    )
    check("failed=1" in result.stdout, "bootstrap failure is visible")


def verify_isolated_lab_protocol_split() -> None:
    prepare()
    database_password = (
        WORK / "source-config" / "coffer" / "secrets" / "database-password"
    )
    database_password.write_text("stage3/a+b=c@d:e\n", encoding="utf-8")
    database_password.chmod(0o600)
    remember_generated_secrets()
    run_action(
        "precheck",
        "-e",
        "coffer_deployment_profile=isolated-lab",
        "-e",
        "kolla_enable_tls_internal=false",
    )
    with listening(61313):
        run_action(
            "deploy",
            "-e",
            "coffer_deployment_profile=isolated-lab",
            "-e",
            "kolla_enable_tls_internal=false",
        )
    edge_config = (
        WORK / "target-config" / "coffer-edge" / "coffer.conf"
    ).read_text(encoding="utf-8")
    check(
        "api_upstream_url = https://127.0.0.1:18787"
        in edge_config
        and (
            "registry_upstream_url = "
            "https://127.0.0.1:18789"
        )
        in edge_config,
        "isolated lab uses direct TLS backends when Kolla internal VIP is HTTP",
    )
    api_config = (
        WORK / "target-config" / "coffer-api" / "coffer.conf"
    ).read_text(encoding="utf-8")
    check(
        "stage3%2Fa%2Bb%3Dc%40d%3Ae" in api_config
        and "stage3/a+b=c@d:e" not in api_config,
        "database credentials are URL-encoded in SQLAlchemy connection URLs",
    )
    endpoint_events = {
        event["label"]
        for event in events()
        if event.get("action") == "toolbox"
        and event.get("label", "").startswith("coffer:")
    }
    check(
        any(
            ":internal:http://registry.internal.example.test:18788/v1"
            in label
            for label in endpoint_events
        )
        and any(
            ":public:https://registry.example.test/v1" in label
            for label in endpoint_events
        ),
        "isolated lab separates HTTP internal endpoint from HTTPS public origin",
    )


def verify_rendered_contract(secret_values: dict[str, str]) -> None:
    target = WORK / "target-config"
    event_list = events()
    current_state = state()

    check(
        set(current_state["containers"])
        >= {"haproxy", "coffer_api", "coffer_edge", "coffer_registry"},
        "deploy starts HAProxy and the three enabled Coffer processes",
    )
    check(
        "coffer_reconcile" not in current_state["containers"],
        "unresolved reconciliation identity remains disabled",
    )
    bootstrap_index = next(
        index
        for index, event in enumerate(event_list)
        if event.get("action") == "start_container"
        and event.get("name") == "bootstrap_coffer"
    )
    process_indexes = [
        index
        for index, event in enumerate(event_list)
        if event.get("action") == "recreate_or_restart_container"
        and event.get("name")
        in {"coffer_api", "coffer_edge", "coffer_registry"}
    ]
    check(
        process_indexes and bootstrap_index < min(process_indexes),
        "one-shot bootstrap completes before Coffer process restart",
    )

    toolbox_labels = {
        event["label"]
        for event in event_list
        if event.get("action") == "toolbox"
    }
    check(
        "coffer:oci-registry" in toolbox_labels,
        "Keystone service type is oci-registry",
    )
    endpoint_labels = {
        label for label in toolbox_labels if label.startswith("coffer:")
    }
    check(
        any(":public:https://registry.example.test/v1" in x for x in endpoint_labels)
        and any(
            ":internal:https://registry.internal.example.test:18788/v1" in x
            for x in endpoint_labels
        )
        and any(
            ":admin:https://registry.internal.example.test:18788/v1" in x
            for x in endpoint_labels
        ),
        "public, internal, and admin Keystone endpoints are registered",
    )

    external_map = (
        target / "haproxy" / "external-frontend-map"
    ).read_text(encoding="utf-8")
    check(
        "registry.example.test coffer_edge_external_back" in external_map
        and "coffer_api" not in external_map
        and "coffer_registry" not in external_map,
        "the sole external tenant route targets coffer-edge",
    )
    for service in ("coffer-api", "coffer-edge", "coffer-registry"):
        haproxy_config = (
            target / "haproxy" / "services.d" / f"{service}.cfg"
        ).read_text(encoding="utf-8")
        check(
            "ssl verify required" in haproxy_config,
            f"{service} HAProxy backend verifies TLS",
        )

    expected_modes = {
        "coffer-api/coffer.conf": 0o600,
        "coffer-api/signing-key.pem": 0o600,
        "coffer-edge/coffer.conf": 0o600,
        "coffer-registry/config.yml": 0o600,
        "coffer-bootstrap/coffer.conf": 0o600,
    }
    for relative_path, expected_mode in expected_modes.items():
        mode = (target / relative_path).stat().st_mode & 0o777
        check(mode == expected_mode, f"{relative_path} is mode 0600")

    all_target_files = {
        str(path.relative_to(target)): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }

    def recipients(value: str) -> set[str]:
        encoded = value.encode()
        return {
            path
            for path, content in all_target_files.items()
            if encoded in content
        }

    check(
        recipients(secret_values["rgw-access-key"])
        == {"coffer-registry/config.yml"},
        "RGW access key is delivered only to Distribution",
    )
    check(
        recipients(secret_values["rgw-secret-key"])
        == {"coffer-registry/config.yml"},
        "RGW secret key is delivered only to Distribution",
    )
    check(
        recipients(secret_values["distribution-http-secret"])
        == {"coffer-registry/config.yml"},
        "Distribution HTTP secret is delivered only to Distribution",
    )
    check(
        recipients(secret_values["keystone-service-password"])
        == {"coffer-api/coffer.conf"},
        "Keystone service password is delivered only to the API",
    )
    check(
        recipients(secret_values["database-password"])
        == {
            "coffer-api/coffer.conf",
            "coffer-edge/coffer.conf",
            "coffer-bootstrap/coffer.conf",
        },
        "database secret recipients match API, edge, and bootstrap",
    )
    check(
        "coffer-api/signing-key.pem" in all_target_files
        and not any(
            path.endswith("signing-key.pem")
            for path in all_target_files
            if not path.startswith("coffer-api/")
        ),
        "token signing key is delivered only to the API",
    )
    check(
        {
            path
            for path in all_target_files
            if path.endswith("jwks.json")
        }
        == {"coffer-edge/jwks.json", "coffer-registry/jwks.json"},
        "public JWKS recipients are edge and Distribution",
    )
    check(
        (
            target
            / "coffer-registry"
            / "ca-certificates"
            / "coffer-rgw-ca.crt"
        ).exists(),
        "Distribution receives the RGW CA through Kolla system trust input",
    )

    check(
        (WORK / "source-config" / "fluentd" / "input" / "15-coffer.conf").exists(),
        "Fluentd extension input is installed",
    )
    check(
        (
            WORK
            / "source-config"
            / "cron"
            / "cron-logrotate-global.conf"
        ).exists(),
        "logrotate extension template is installed",
    )


def verify_successful_lifecycle() -> None:
    prepare()
    secret_values = remember_generated_secrets()
    run_action("precheck")
    run_action("deploy")
    verify_rendered_contract(secret_values)

    reconfigure = run_action("reconfigure")
    check(
        re.search(r"changed=0\b", reconfigure.stdout) is not None,
        "reconfigure is idempotent",
    )
    run_action("config_validate")
    check(True, "config_validate executes for running processes")

    run_action("pull")
    second_pull = run_action("pull")
    check(
        re.search(r"changed=0\b", second_pull.stdout) is not None,
        "image pull is idempotent",
    )
    run_action("upgrade")
    run_action("check")
    run_action("stop")
    stopped = state()["containers"]
    check(
        not {"coffer_api", "coffer_edge", "coffer_registry"}.intersection(
            stopped
        ),
        "stop removes only Coffer-owned process containers",
    )
    second_stop = run_action("stop")
    check(
        re.search(r"changed=0\b", second_stop.stdout) is not None,
        "stop is idempotent",
    )


def verify_secret_safe_outputs() -> None:
    output = "\n".join(CAPTURED_OUTPUTS)
    state_and_events = ""
    if WORK.exists():
        state_and_events = (
            (WORK / "state.json").read_text(encoding="utf-8")
            + (WORK / "events.jsonl").read_text(encoding="utf-8")
        )
    leaked = [
        secret
        for secret in GENERATED_SECRETS
        if secret and (secret in output or secret in state_and_events)
    ]
    check(not leaked, "generated secrets are absent from output and event state")


def main() -> None:
    for directory in (
        Path("/private/tmp/coffer-stage3-ansible/local"),
        Path("/private/tmp/coffer-stage3-ansible/remote"),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    try:
        verify_pin_and_syntax()
        verify_wrapper_contract()
        verify_disabled_and_negative_prechecks()
        verify_isolated_lab_protocol_split()
        with listening(61313):
            verify_bootstrap_failure()
            verify_successful_lifecycle()
        verify_secret_safe_outputs()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)

    check(not WORK.exists(), "contract work directory is removed")
    print(f"Coffer Kolla role contract: {len(PASSED_CHECKS)} checks passed")


if __name__ == "__main__":
    main()
