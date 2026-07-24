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
