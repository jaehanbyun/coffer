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
        str(path.relative_to(secret_dir)): path.read_text(encoding="utf-8").strip()
        for path in secret_dir.rglob("*")
        if path.is_file()
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
    public = (
        lambda name: WORK
        / "source-config"
        / "coffer"
        / "public"
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
    assert_failure_case(
        "metrics without Prometheus",
        lambda: None,
        "-e",
        "enable_prometheus=false",
    )
    assert_failure_case(
        "metrics without Alertmanager rule loading",
        lambda: None,
        "-e",
        "enable_prometheus_alertmanager=false",
    )
    assert_failure_case(
        "metrics without Grafana dashboard loading",
        lambda: None,
        "-e",
        "enable_grafana=false",
    )
    assert_failure_case(
        "metrics with multiple API workers",
        lambda: None,
        "-e",
        "coffer_api_workers=2",
    )
    assert_failure_case(
        "metrics with multiple edge workers",
        lambda: None,
        "-e",
        "coffer_edge_workers=2",
    )
    assert_failure_case(
        "metrics proxy with multiple workers",
        lambda: None,
        "-e",
        "coffer_registry_metrics_workers=2",
    )
    assert_failure_case(
        "metrics proxy and Distribution debug port collision",
        lambda: None,
        "-e",
        "coffer_registry_debug_port=18791",
    )
    assert_failure_case(
        "metrics target aliases the internal VIP",
        lambda: None,
        "-e",
        "kolla_internal_vip_address=127.0.0.1",
    )
    assert_failure_case(
        "maintenance reconciliation remains disabled",
        lambda: None,
        "-e",
        "coffer_enable_reconcile=true",
    )
    assert_failure_case(
        "unsafe maintenance secret permission",
        lambda: secret(
            "maintenance/coffer-stage3-contract/"
            "application-credential-secret"
        ).chmod(0o644),
    )
    assert_failure_case(
        "mismatched maintenance client key",
        lambda: secret(
            "maintenance/coffer-stage3-contract/client.key"
        ).write_text("not-a-private-key\n", encoding="utf-8"),
    )
    assert_failure_case(
        "maintenance client certificate from the wrong CA",
        lambda: public(
            "maintenance/coffer-stage3-contract/client.crt"
        ).write_bytes(
            (
                WORK
                / "source-config"
                / "certificates"
                / "backend-cert.pem"
            ).read_bytes()
        ),
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
        "coffer_registry_metrics",
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
        >= {
            "haproxy",
            "coffer_api",
            "coffer_edge",
            "coffer_registry",
            "coffer_registry_metrics",
        },
        "deploy starts HAProxy and the four enabled Coffer processes",
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
        in {
            "coffer_api",
            "coffer_edge",
            "coffer_registry",
            "coffer_registry_metrics",
        }
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
    maintenance_haproxy = (
        target / "haproxy" / "services.d" / "coffer-maintenance.cfg"
    ).read_text(encoding="utf-8")
    check(
        "bind 127.0.0.2:18790 ssl" in maintenance_haproxy
        and "coffer-maintenance-client-ca.crt verify required" in maintenance_haproxy
        and "ssl_c_der,sha2(256),hex" in maintenance_haproxy,
        "private maintenance frontend requires the exact client CA and certificate",
    )
    check(
        "http-request del-header X-Coffer-Maintenance-Workload"
        in maintenance_haproxy
        and (
            "http-request set-header X-Coffer-Maintenance-Workload "
            "reconciler-coffer-stage3-contract"
        )
        in maintenance_haproxy
        and "/v1/internal/maintenance/registry-token" in maintenance_haproxy,
        "private frontend strips caller identity and maps only the broker route",
    )
    api_haproxy = (
        target / "haproxy" / "services.d" / "coffer-api.cfg"
    ).read_text(encoding="utf-8")
    operational_denials = (
        "http-request deny if { path -i /healthz }",
        "http-request deny if { path -i /readyz }",
        "http-request deny if { path -i /metrics }",
        "http-request deny if { path -i -m beg /debug }",
    )
    check(
        "http-request del-header X-Coffer-Maintenance-Workload"
        in api_haproxy
        and "http-request deny if { path -i -m beg /v1/internal/ }"
        in api_haproxy
        and all(rule in api_haproxy for rule in operational_denials),
        "ordinary API frontend strips assertions and denies private paths",
    )
    edge_haproxy = (
        target / "haproxy" / "services.d" / "coffer-edge.cfg"
    ).read_text(encoding="utf-8")
    check(
        all(edge_haproxy.count(rule) >= 3 for rule in operational_denials),
        "edge internal frontend and both mapped backends deny private paths",
    )

    expected_modes = {
        "coffer-api/coffer.conf": 0o600,
        "coffer-api/signing-key.pem": 0o600,
        "coffer-edge/coffer.conf": 0o600,
        "coffer-registry/config.yml": 0o600,
        "coffer-registry-metrics/coffer.conf": 0o600,
        "coffer-registry-metrics/registry-metrics.key": 0o600,
        "coffer-bootstrap/coffer.conf": 0o600,
        "coffer-reconcile/coffer.conf": 0o600,
        "coffer-reconcile/reconcile-metrics.key": 0o600,
        "coffer-reconcile/maintenance-application-credential-id": 0o600,
        "coffer-reconcile/maintenance-application-credential-secret": 0o600,
        "coffer-reconcile/maintenance-client.key": 0o600,
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
        recipients(
            secret_values[
                "maintenance/coffer-stage3-contract/"
                "application-credential-id"
            ]
        )
        == {"coffer-reconcile/maintenance-application-credential-id"},
        "maintenance application-credential ID has one reconciler recipient",
    )
    check(
        recipients(
            secret_values[
                "maintenance/coffer-stage3-contract/"
                "application-credential-secret"
            ]
        )
        == {"coffer-reconcile/maintenance-application-credential-secret"},
        "maintenance application-credential secret has one reconciler recipient",
    )
    maintenance_private_key = secret_values[
        "maintenance/coffer-stage3-contract/client.key"
    ].encode()
    check(
        {
            path
            for path, content in all_target_files.items()
            if maintenance_private_key in content
        }
        == {"coffer-reconcile/maintenance-client.key"},
        "maintenance client private key has one reconciler recipient",
    )
    reconcile_config_json = (
        target / "coffer-reconcile" / "config.json"
    ).read_text(encoding="utf-8")
    reconcile_config_document = json.loads(reconcile_config_json)
    reconcile_destinations = {
        item["dest"]
        for item in reconcile_config_document["config_files"]
    }
    check(
        {
            "/etc/coffer/reconcile-metrics.crt",
            "/etc/coffer/reconcile-metrics.key",
            "/etc/coffer/maintenance-application-credential-id",
            "/etc/coffer/maintenance-application-credential-secret",
            "/etc/coffer/maintenance-client.crt",
            "/etc/coffer/maintenance-client.key",
        }
        <= reconcile_destinations,
        "disabled reconciler fixture declares exact future runtime recipients",
    )
    reconcile_config = (
        target / "coffer-reconcile" / "coffer.conf"
    ).read_text(encoding="utf-8")
    check(
        "mode = periodic" in reconcile_config
        and "management_bind_host = 127.0.0.1" in reconcile_config
        and "management_bind_port = 18790" in reconcile_config
        and (
            "management_tls_certfile = "
            "/etc/coffer/reconcile-metrics.crt"
        )
        in reconcile_config
        and (
            "management_tls_keyfile = "
            "/etc/coffer/reconcile-metrics.key"
        )
        in reconcile_config,
        "periodic reconciler fixture renders the private TLS management listener",
    )
    api_config = (target / "coffer-api" / "coffer.conf").read_text(
        encoding="utf-8"
    )
    check(
        "[maintenance]" in api_config
        and "enabled = True" in api_config
        and (
            "workload_ids = reconciler-coffer-stage3-contract"
            in api_config
        )
        and "trusted_proxy_addresses = 127.0.0.1" in api_config,
        "API fixture renders the trusted proxy and workload allowlists",
    )
    check(
        recipients(secret_values["database-password"])
        == {
            "coffer-api/coffer.conf",
            "coffer-edge/coffer.conf",
            "coffer-reconcile/coffer.conf",
            "coffer-bootstrap/coffer.conf",
        },
        "database secret recipients match API, edge, reconciler, and bootstrap",
    )
    registry_metrics_config = (
        target / "coffer-registry-metrics" / "coffer.conf"
    ).read_text(encoding="utf-8")
    check(
        "[registry_metrics]" in registry_metrics_config
        and "bind_port = 18791" in registry_metrics_config
        and (
            "upstream_url = http://127.0.0.1:18792/metrics"
            in registry_metrics_config
        )
        and "[database]" not in registry_metrics_config
        and secret_values["database-password"] not in registry_metrics_config,
        "registry metrics proxy is loopback-only upstream and receives no DB secret",
    )
    registry_metrics_container = json.loads(
        (
            target / "coffer-registry-metrics" / "config.json"
        ).read_text(encoding="utf-8")
    )
    check(
        registry_metrics_container["command"]
        == "coffer-registry-metrics --config-file /etc/coffer/coffer.conf"
        and {
            item["dest"]
            for item in registry_metrics_container["config_files"]
        }
        == {
            "/etc/coffer/coffer.conf",
            "/etc/coffer/registry-metrics.crt",
            "/etc/coffer/registry-metrics.key",
        },
        "registry metrics container receives only config and listener TLS files",
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
    registry_config = yaml.safe_load(
        (target / "coffer-registry" / "config.yml").read_text(
            encoding="utf-8"
        )
    )
    check(
        registry_config["http"]["debug"]
        == {
            "addr": "127.0.0.1:18792",
            "prometheus": {"enabled": True, "path": "/metrics"},
        },
        "Distribution debug mux is bound only to loopback for the allowlist proxy",
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
    prometheus_path = (
        WORK
        / "source-config"
        / "prometheus"
        / "prometheus.yml.d"
        / "15-coffer.yml"
    )
    prometheus_document = yaml.safe_load(
        prometheus_path.read_text(encoding="utf-8")
    )
    scrape_configs = prometheus_document["scrape_configs"]
    check(
        [job["job_name"] for job in scrape_configs]
        == ["coffer-api", "coffer-edge", "coffer-registry"],
        "Prometheus omits the disabled reconciler and owns enabled direct jobs",
    )
    targets = {
        target_value
        for job in scrape_configs
        for static_config in job["static_configs"]
        for target_value in static_config["targets"]
    }
    check(
        targets
        == {"127.0.0.1:18787", "127.0.0.1:18788", "127.0.0.1:18791"}
        and "127.0.0.2" not in prometheus_path.read_text(encoding="utf-8")
        and "registry.internal.example.test:18787"
        not in prometheus_path.read_text(encoding="utf-8"),
        "Prometheus targets direct backend addresses and never a VIP or FQDN",
    )
    check(
        "coffer-reconcile" not in prometheus_path.read_text(encoding="utf-8")
        and "127.0.0.1:18790"
        not in prometheus_path.read_text(encoding="utf-8"),
        "disabled one-shot or periodic reconciler creates no phantom scrape target",
    )
    check(
        all(
            job["scheme"] == "https"
            and job["metrics_path"] == "/metrics"
            and job["tls_config"]
            == {
                "ca_file": "/etc/ssl/certs/ca-certificates.crt",
                "server_name": "registry.internal.example.test",
            }
            for job in scrape_configs
        ),
        "direct metric scrapes use the operator CA and fixed TLS server name",
    )
    check(
        all(
            static_config["labels"]
            == {
                "service": job["job_name"],
                "instance": "coffer-stage3-contract",
            }
            for job in scrape_configs
            for static_config in job["static_configs"]
        ),
        "direct metric targets retain only stable service and instance labels",
    )
    rules_path = (
        WORK
        / "source-config"
        / "prometheus"
        / "coffer.rules"
    )
    rule_document = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    rendered_rules = [
        rule
        for group in rule_document["groups"]
        for rule in group["rules"]
    ]
    topology = json.loads(
        (
            ROOT / "poc" / "observability" / "topology.json"
        ).read_text(encoding="utf-8")
    )
    check(
        [rule["record"] for rule in rendered_rules if "record" in rule]
        == topology["recording_rules"]
        and [rule["alert"] for rule in rendered_rules if "alert" in rule]
        == topology["alerts"],
        "Prometheus recording and alert rules match the fixed topology",
    )
    dashboard_path = (
        WORK
        / "source-config"
        / "grafana"
        / "dashboards"
        / "coffer-operator.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    check(
        dashboard["uid"] == "coffer-operator"
        and [
            panel["title"]
            for panel in dashboard["panels"]
            if panel["type"] == "row"
        ]
        == topology["dashboard_rows"],
        "Grafana operator dashboard matches the fixed topology",
    )
    check(
        rules_path.stat().st_mode & 0o777 == 0o640
        and dashboard_path.stat().st_mode & 0o777 == 0o640,
        "operator rules and dashboard use controller-owner-only write modes",
    )
    edge_config = (target / "coffer-edge" / "coffer.conf").read_text(
        encoding="utf-8"
    )
    check(
        "[observability]" in edge_config
        and "metrics_enabled = True" in edge_config,
        "edge runtime enables its private operational dispatcher",
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
    run_action("reconfigure", "-e", "coffer_enable_metrics=false")
    disabled_state = state()["containers"]
    check(
        not (
            WORK
            / "source-config"
            / "prometheus"
            / "prometheus.yml.d"
            / "15-coffer.yml"
        ).exists()
        and not (
            WORK
            / "source-config"
            / "prometheus"
            / "coffer.rules"
        ).exists()
        and not (
            WORK
            / "source-config"
            / "grafana"
            / "dashboards"
            / "coffer-operator.json"
        ).exists()
        and "coffer_registry_metrics" not in disabled_state,
        "disabling metrics removes only Coffer scrape, rule, dashboard, and sidecar state",
    )
    disabled_reconfigure = run_action(
        "reconfigure",
        "-e",
        "coffer_enable_metrics=false",
    )
    check(
        re.search(r"changed=0\b", disabled_reconfigure.stdout) is not None,
        "disabled metrics reconfigure is idempotent",
    )
    run_action("reconfigure")
    restored_state = state()["containers"]
    check(
        (
            WORK
            / "source-config"
            / "prometheus"
            / "prometheus.yml.d"
            / "15-coffer.yml"
        ).exists()
        and (
            WORK
            / "source-config"
            / "prometheus"
            / "coffer.rules"
        ).exists()
        and (
            WORK
            / "source-config"
            / "grafana"
            / "dashboards"
            / "coffer-operator.json"
        ).exists()
        and "coffer_registry_metrics" in restored_state,
        "re-enabling metrics restores exact controller artifacts and sidecar",
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
        not {
            "coffer_api",
            "coffer_edge",
            "coffer_registry",
            "coffer_registry_metrics",
        }.intersection(stopped),
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
