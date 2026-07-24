from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def render_bootstrap_config(copy_ca: bool) -> dict[str, object]:
    text = (
        ROOT / "docker" / "config" / "coffer-bootstrap.json.j2"
    ).read_text(encoding="utf-8")
    text = re.sub(
        r"{% if kolla_copy_ca_into_containers \| bool %}(.*?){% endif %}",
        lambda match: match.group(1) if copy_ca else "",
        text,
        flags=re.DOTALL,
    )
    text = text.replace(
        "{{ container_config_directory }}",
        "/var/lib/kolla/config_files",
    )
    return json.loads(text)


def test_bootstrap_config_installs_kolla_ca_bundle_when_enabled() -> None:
    document = render_bootstrap_config(True)

    assert {
        "source": "/var/lib/kolla/config_files/ca-certificates",
        "dest": "/var/lib/kolla/share/ca-certificates",
        "owner": "root",
        "perm": "0644",
    } in document["config_files"]


def test_bootstrap_config_omits_kolla_ca_bundle_when_disabled() -> None:
    document = render_bootstrap_config(False)

    assert all(
        item["dest"] != "/var/lib/kolla/share/ca-certificates"
        for item in document["config_files"]
    )


def test_service_cert_copy_includes_one_shot_bootstrap() -> None:
    config_tasks = (
        ROOT / "ansible" / "roles" / "coffer" / "tasks" / "config.yml"
    ).read_text(encoding="utf-8")

    assert 'project_services: "{{ coffer_processes }}"' in config_tasks


def test_edge_and_reconciler_trust_the_kolla_frontend_ca() -> None:
    config_tasks = (
        ROOT / "ansible" / "roles" / "coffer" / "tasks" / "config.yml"
    ).read_text(encoding="utf-8")

    assert (
        config_tasks.count('src: "{{ kolla_certificates_dir }}/ca/root.crt"')
        == 2
    )


def test_multinode_lifecycle_scans_every_runtime_log_without_retaining_it() -> (
    None
):
    lifecycle = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-companion-lifecycle.sh"
    ).read_text(encoding="utf-8")

    assert "verify_runtime_logs_secret_free" in lifecycle
    assert lifecycle.count("docker logs coffer_") == 3
    assert "mktemp -d" in lifecycle
    assert 'rm -f -- "${runtime_log}"' in lifecycle
    assert 'rmdir -- "${temporary_root}"' in lifecycle
    assert "bearer token found in retained Coffer log" in lifecycle
    deployed_boundary = lifecycle.split(
        "require_deployed_boundary() {", maxsplit=1
    )[1].split("run_companion() {", maxsplit=1)[0]
    assert "verify_runtime_logs_secret_free" in deployed_boundary


def test_multinode_tenant_fixture_is_finite_and_exactly_bounded() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "run-coffer-tenant-fixture.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-tenant-fixture.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|prepare|status|cleanup}" in outer
    assert "{preflight|prepare|status|cleanup}" in guest
    assert "run-coffer-companion-lifecycle.sh" in outer
    assert 'timedelta(hours=12)' in guest
    assert guest.count('"coffer-stage5-project-') == 2
    assert guest.count('"coffer-stage5-user-') == 2
    assert guest.count('"coffer-stage5-credential-') == 2
    assert "unrestricted=False" in guest
    assert "docker exec --user root -i kolla_toolbox" in guest
    assert 'AUTH_URL = "https://192.168.252.10:5000/v3"' in guest
    assert "auth_url=AUTH_URL" in guest
    assert guest.count('interface="internal"') == 3
    assert guest.count('region_name="RegionOne"') == 3
    assert '"/run/coffer-stage5-tenant-admin-password"' in guest
    assert 'rm -f -- "${toolbox_state}" "${admin_password}"' in guest
    assert "assign_project_role_to_user" in guest
    assert "delete_application_credential" in guest
    assert "delete_user" in guest
    assert "delete_project" in guest
    assert "dns=override-required" in guest
    assert 'grep -F -- "${registry_name}" /etc/hosts' in guest
    assert "rm -rf" not in guest
    assert "--remove-all-storage" not in guest


def test_multinode_tenant_acceptance_is_owner_local_and_fail_closed() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "run-coffer-tenant-acceptance.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-tenant-acceptance.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|accept|status}" in outer
    assert "{preflight|accept|status}" in guest
    assert "run-coffer-tenant-fixture.sh" in outer
    assert guest.count("/var/lib/kolla/venv/bin/python3") == 3
    assert '"${repository_name}" "${project_a}" "${project_b}"' in guest
    assert "192.168.254.10/32" in guest
    assert "192.168.254.10 %s" in guest
    assert "cp --preserve=all" in guest
    assert "docker_ca_created" in guest
    assert "project logical quota exceeded" in guest
    assert "test \"${quota_status}\" = 429" in guest
    assert "set_quota_limit 2147483648" in guest
    assert guest.count("--request PATCH") == 1
    assert "for part in 1 2" in guest
    assert "project B unexpectedly pulled" in guest
    assert "project B unexpectedly pushed" in guest
    assert "coffer_tenant_runtime_log_audit" in guest
    assert "write_marker \"${accepted_marker}\"" in guest
    assert guest.index("scan_runtime_logs") < guest.rindex(
        'write_marker "${accepted_marker}"'
    )
    assert "rm -rf" not in guest
    assert "--remove-all-storage" not in guest
