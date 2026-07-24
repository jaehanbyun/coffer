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

    expected_actions = (
        "{preflight|prepare|renew-preflight|renew|status|cleanup}"
    )
    assert expected_actions in outer
    assert expected_actions in guest
    assert "run-coffer-companion-lifecycle.sh" in outer
    assert 'timedelta(hours=12)' in guest
    assert guest.count('"coffer-stage5-project-') == 2
    assert guest.count('"coffer-stage5-user-') == 2
    assert guest.count('"coffer-stage5-credential-') == 4
    assert guest.count("-renewal-1") == 2
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
    assert (
        "preflight|prepare|renew-status|renew-stage|renew-finalize|status|cleanup"
        in guest
    )
    assert "pending_retire" in guest
    assert "renewal-staged" in guest
    assert "renewed.complete" in guest
    assert "coffer-stage5-tenant-credential-renewal-v1" in guest
    assert guest.index("run_identity_action renew-stage") < guest.index(
        "run_identity_action renew-finalize"
    )
    assert guest.index("run_identity_action renew-finalize") < guest.rindex(
        "write_renewed_marker"
    )
    assert "refusing credential renewal from non-exact state" in guest
    assert "credentials=4" in guest
    assert "dns=override-required" in guest
    assert 'grep -F -- "${registry_name}" /etc/hosts' in guest
    assert "rm -rf" not in guest
    assert "--remove-all-storage" not in guest


def test_multinode_update_image_is_pinned_and_keeps_runtime_unchanged() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "build-distribute-coffer-update.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-build-distribute-coffer-update.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|status|build}" in outer
    assert "{preflight|status|build}" in guest
    assert "a6f476e65f89048860309dc277406c96fd7fa0e7" in outer
    assert "a6f476e65f89048860309dc277406c96fd7fa0e7" in guest
    assert "7fcaeba415837c624b7618adeaf23be2be5eaa6269b4702be4795aa640c5684f" in outer
    assert "7fcaeba415837c624b7618adeaf23be2be5eaa6269b4702be4795aa640c5684f" in guest
    assert "localhost/coffer:stage5-quota-retry" in guest
    assert 'current_image="localhost/coffer:stage5"' not in guest
    assert "runtime=unchanged" in guest
    assert "require_runtime_unchanged" in guest
    assert "installed quota source digest changed" in guest
    assert "/var/lib/kolla/venv/bin/python3" in guest
    assert "docker run --rm --pull=never -i" in guest
    assert "quota.MAX_TRANSACTION_ATTEMPTS != 3" in guest
    assert "validate_empty_partial_marker" in guest
    assert "grep -Fxq 'update_image_id='" in guest
    assert 'if ! result="$(' in guest
    assert "docker save" in guest
    assert "sudo docker load" in guest
    assert "docker stop" not in guest
    assert "docker restart" not in guest
    assert "docker image rm" not in guest
    assert "kolla-ansible" not in guest
    assert "rm -rf --" in guest
    assert '"${update_root}"/source.*' in guest


def test_multinode_rolling_update_is_serial_and_has_exact_rollback() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "run-coffer-rolling-update.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-rolling-update.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|status|upgrade|rollback}" in outer
    assert "{preflight|status|upgrade|rollback}" in guest
    assert "run-coffer-companion-lifecycle.sh" in outer
    assert "run-coffer-tenant-acceptance.sh" in outer
    assert "path-status" in outer
    assert "during_probe_count" in outer
    assert "test \"${during_probe_count}\" -ge 1" in outer
    assert "localhost/coffer:stage5-quota-retry" in guest
    assert 'current_image="localhost/coffer:stage5"' in guest
    assert 'registry_image="localhost/coffer-registry:stage5"' in guest
    assert "kolla_serial=1" in guest
    assert '\"${entrypoint}\" upgrade' in guest
    assert "coffer-stage5-rolling-globals.yml" in guest
    assert 'changed != expected_changed' in guest
    assert "rolling globals changed outside the Coffer image" in guest
    assert "current=0 updated=3" in guest
    assert "current=3 updated=0" in guest
    assert "wait_cluster_state" in guest
    assert "resume=postcheck" in guest
    assert "rollback.complete" in guest
    assert "docker stop" not in guest
    assert "docker restart" not in guest
    assert "docker image rm" not in guest
    assert "virsh" not in guest


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

    assert (
        "{preflight|accept|status|path-status|data-status|database-status}"
        in outer
    )
    assert "{preflight|accept|status|path-status|database-status}" in guest
    assert "run-coffer-tenant-fixture.sh" in outer
    assert 'test "${action}" != path-status' in outer
    assert 'test "${action}" != database-status' in outer
    assert 'phase_rc="$?"' in outer
    assert "accepted.complete" in outer
    assert "checkpoint=control-tokens" in guest
    assert "checkpoint=repository" in guest
    assert "checkpoint=quota-open" in guest
    assert "checkpoint=owner-full" in guest
    assert 'client_rc="$?"' in guest
    assert "checkpoint=docker-push" in guest
    assert "checkpoint=resumable-finalize" in guest
    assert "checkpoint=status manifest=" in guest
    assert guest.count("sudo -u ubuntu ssh -n") == 4
    assert ". + {acceptance: $evidence[0]}" in guest
    assert ".acceptance.manifest_digest" in guest
    assert guest.count(
        "Accept: application/vnd.oci.image.manifest.v1+json"
    ) == 3
    assert "checkpoint=token-a" in guest
    assert 'if test "${action}" != quota-denial' in guest
    assert "quota_error_code=" in guest
    assert guest.count("/var/lib/kolla/venv/bin/python3") == 3
    assert '"${repository_name}" "${project_a}" "${project_b}"' in guest
    assert "192.168.254.10/32" in guest
    assert "192.168.254.10 %s" in guest
    assert "cp --preserve=all" in guest
    assert "docker_ca_created" in guest
    assert "project logical quota exceeded" in guest
    assert "test \"${quota_status}\" = 429" in guest
    assert "upload_complete_blob" in guest
    assert "quota_config_digest" in guest
    assert "quota_layer_digest" in guest
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
    assert "database_write_probe" in guest
    assert "probe_limit=2147483649" in guest
    assert "restored_limit=2147483648" in guest
    assert "require_path_boundary" in guest
    assert "coffer_tenant_path_probe" in guest


def test_multinode_galera_transactions_use_real_bounded_conflict() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "test-coffer-galera-transactions.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-galera-transactions.sh"
    ).read_text(encoding="utf-8")
    helper = (
        ROOT / "poc" / "kolla-ha" / "guest-coffer-galera-transactions.py"
    ).read_text(encoding="utf-8")

    assert "{preflight|run}" in outer
    assert "{status|start|complete}" in guest
    assert "run-coffer-tenant-acceptance.sh" in outer
    assert "guest-check-kolla-galera.sh" in outer
    assert "docker exec -i coffer_api" in outer
    assert "guest-coffer-galera-transactions.py" in outer
    assert "resume=owned-partial" in outer
    assert "retry_code=1205" in outer
    assert "retry_attempt=2" in outer
    assert "coffer-stage5-galera-transactions.py" in guest
    assert "root:root:700" in guest
    assert guest.count("root:root:600") == 2
    assert "MAX_TRANSACTION_ATTEMPTS != 3" in helper
    assert "innodb_lock_wait_timeout=1" in helper
    assert '"handle_error"' in helper
    assert "conflict_codes != [1205]" in helper
    assert "ThreadPoolExecutor(max_workers=2)" in helper
    assert 'results.count("admitted")' in helper
    assert 'results.count("denied")' in helper
    assert "finally:" in helper
    assert "cleanup(store._engine)" in helper
    assert "residue_count" in helper
    assert "application_credential" not in helper
    for script in (outer, guest):
        assert "docker stop" not in script
        assert "docker restart" not in script
        assert "docker rm" not in script
        assert "virsh" not in script
        assert "rm -rf" not in script


def test_multinode_reconciler_fencing_uses_separate_bounded_workers() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "test-coffer-reconciler-fencing.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT
        / "poc"
        / "kolla-ha"
        / "guest-run-coffer-reconciler-fencing.sh"
    ).read_text(encoding="utf-8")
    helper = (
        ROOT / "poc" / "kolla-ha" / "guest-coffer-reconciler-fencing.py"
    ).read_text(encoding="utf-8")

    assert "{preflight|run}" in outer
    assert "{status|start|complete}" in guest
    assert "192.168.252.11" in outer
    assert "192.168.252.12" in outer
    assert "docker exec -i coffer_api" in outer
    assert "guest-coffer-reconciler-fencing.py" in outer
    assert "resume=owned-partial" in outer
    assert "run_helper 0 claim" in outer
    assert "run_helper 1 claim" in outer
    assert "run_helper 1 abandon" in outer
    assert "run_helper 0 recover" in outer
    assert "worker_zero_pid" in outer
    assert "worker_one_pid" in outer
    assert "cleanup_required" in outer
    assert "root:root:700" in guest
    assert guest.count("root:root:600") == 2
    assert "MAX_TRANSACTION_ATTEMPTS != 3" in helper
    assert "ReconciliationCursor" in helper
    assert "after=parse_cursor(cursor)" in helper
    assert "timedelta(seconds=2)" in helper
    assert "StaleReconciliationClaim" in helper
    assert "an abandoned claim token crossed the fence" in helper
    assert "set(WORKERS)" in helper
    assert "claim batches overlapped" in helper
    assert "cleanup(store._engine)" in helper
    assert "residue_count" in helper
    assert "application_credential" not in helper
    for script in (outer, guest):
        assert "docker stop" not in script
        assert "docker restart" not in script
        assert "docker rm" not in script
        assert "virsh" not in script
        assert "rm -rf" not in script


def test_multinode_service_fault_targets_only_controller_three_containers() -> (
    None
):
    script = (
        ROOT / "poc" / "kolla-ha" / "test-coffer-service-failover.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|run}" in script
    assert "192.168.252.13" in script
    assert script.count("coffer_api") >= 2
    assert script.count("coffer_edge") >= 2
    assert script.count("coffer_registry") >= 2
    assert 'docker stop --time 15 "${service}"' in script
    assert 'docker start "${service}"' in script
    assert "data-status" in script
    assert "for attempt in 1 2 3" in script
    assert "for convergence_attempt in 1 2 3" in script
    assert "trap restore_current EXIT" in script
    assert "true:healthy" in script
    assert "true|healthy" not in script
    assert 'temporary="${marker}.tmp.$$"' in script
    assert (
        "'{{.HostConfig.RestartPolicy.Name}}' \"${container}\")\" = no"
        in script
    )
    assert "docker rm" not in script
    assert "virsh" not in script
    assert "rm -rf" not in script


def test_multinode_haproxy_fault_targets_only_the_active_vip_owner() -> None:
    script = (
        ROOT / "poc" / "kolla-ha" / "test-kolla-haproxy-failover.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|run}" in script
    assert "192.168.254.10/32" in script
    assert "192.168.252.10/32" in script
    assert "wait_vip_moved" in script
    assert "field_index" in script
    assert "rejected VIP ownership before stop" in script
    assert "docker stop --time 15 haproxy" in script
    assert "docker start haproxy" in script
    assert "data-status" in script
    assert "for attempt in 1 2 3" in script
    assert "for convergence_attempt in 1 2 3" in script
    assert "trap restore_current EXIT" in script
    assert "docker stop --time 15 keepalived" not in script
    assert "docker start keepalived" not in script
    assert "docker rm" not in script
    assert "virsh" not in script
    assert "rm -rf" not in script


def test_multinode_galera_fault_targets_only_controller_three_mariadb() -> None:
    outer = (
        ROOT / "poc" / "kolla-ha" / "test-kolla-galera-failover.sh"
    ).read_text(encoding="utf-8")
    guest = (
        ROOT / "poc" / "kolla-ha" / "guest-check-kolla-galera.sh"
    ).read_text(encoding="utf-8")

    assert "{preflight|run}" in outer
    assert "192.168.252.13" in outer
    assert "docker pause mariadb" in outer
    assert "docker unpause mariadb" in outer
    assert "docker stop" not in outer
    assert "database-status" in outer
    assert "trap restore_target EXIT" in outer
    assert "wait_database_state degraded" in outer
    assert "wait_database_state healthy" in outer
    assert "{healthy|degraded}" in guest
    assert "wsrep_cluster_size" in guest
    assert "runtime_mysql_servers" in guest
    assert "offline-hostgroup-3" in guest
    assert "MYSQL_PWD" in guest
    assert "docker exec -e" not in guest
    for script in (outer, guest):
        assert "docker rm" not in script
        assert "virsh" not in script
        assert "rm -rf" not in script
