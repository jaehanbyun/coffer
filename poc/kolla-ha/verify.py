from __future__ import annotations

import copy
import importlib.util
import io
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import yaml


HARNESS = Path(__file__).resolve().parent


def load_remote_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "coffer_stage5_libvirt_remote",
        HARNESS / "libvirt_remote.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Stage 5 remote helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    remote = load_remote_module()
    document = yaml.safe_load(
        (HARNESS / "topology.yml").read_text(encoding="utf-8")
    )

    remote.validate_allowlist(document)
    assert len(remote.all_domains(document)) == 6
    assert len(remote.planned_volumes(document)) == 16

    invalid = copy.deepcopy(document)
    invalid["domains"]["controllers"][0]["name"] = "unrelated-controller"
    try:
        remote.validate_allowlist(invalid)
    except ValueError as error:
        assert "allowlist" in str(error)
    else:
        raise AssertionError("invalid domain allowlist unexpectedly passed")

    management_xml = remote.network_xml(document["networks"]["management"])
    storage_xml = remote.network_xml(document["networks"]["storage"])
    assert "<forward mode='nat'/>" in management_xml
    assert "<forward" not in storage_xml

    controller_config = remote.network_config(
        document,
        document["domains"]["controllers"][0],
    )
    storage_config = remote.network_config(
        document,
        document["domains"]["storage"][0],
    )
    assert '"ens5"' in controller_config
    assert '"ens5"' not in storage_config

    destroyed_domains: list[str] = []
    destroyed_networks: list[str] = []
    deleted_volumes: list[str] = []
    live_domains = {item["name"] for item in remote.all_domains(document)}
    live_networks = {
        item["name"] for item in document["networks"].values()
    }
    live_volumes = set(remote.planned_volumes(document))

    def fake_virsh(*arguments: str, **_kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if arguments[0] == "vol-delete":
            name = arguments[-1]
            assert name in live_volumes
            live_volumes.remove(name)
            deleted_volumes.append(name)
        return Result()

    def fake_destroy_domain(name: str) -> None:
        assert name in live_domains
        live_domains.remove(name)
        destroyed_domains.append(name)

    def fake_destroy_network(name: str) -> None:
        assert name in live_networks
        live_networks.remove(name)
        destroyed_networks.append(name)

    with (
        patch.object(remote, "virsh", fake_virsh),
        patch.object(
            remote,
            "exists_domain",
            lambda name: name in live_domains,
        ),
        patch.object(
            remote,
            "exists_network",
            lambda name: name in live_networks,
        ),
        patch.object(
            remote,
            "exists_volume",
            lambda name: name in live_volumes,
        ),
        patch.object(remote, "destroy_domain", fake_destroy_domain),
        patch.object(remote, "destroy_network", fake_destroy_network),
        patch("sys.stdout", new=io.StringIO()),
    ):
        remote.destroy(document)

    assert set(destroyed_domains) == remote.EXPECTED_CONTROLLERS | (
        remote.EXPECTED_STORAGE
    )
    assert set(destroyed_networks) == remote.EXPECTED_NETWORKS
    assert set(deleted_volumes) == set(remote.planned_volumes(document))

    rollback_calls: dict[str, list[str]] = {
        "domains": [],
        "volumes": [],
        "networks": [],
    }
    rollback_volumes = {"coffer-kolla-ha-stage5-controller-1-root.qcow2"}

    def rollback_virsh(*arguments: str, **_kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if arguments[0] == "vol-delete":
            rollback_calls["volumes"].append(arguments[-1])
        return Result()

    with (
        patch.object(
            remote,
            "destroy_domain",
            lambda name: rollback_calls["domains"].append(name),
        ),
        patch.object(
            remote,
            "destroy_network",
            lambda name: rollback_calls["networks"].append(name),
        ),
        patch.object(
            remote,
            "exists_volume",
            lambda name: name in rollback_volumes,
        ),
        patch.object(remote, "virsh", rollback_virsh),
    ):
        remote.rollback(
            ["coffer-kolla-ha-stage5-controller-1"],
            ["coffer-kolla-ha-stage5-controller-1-root.qcow2"],
            ["coffer-stage5-mgmt"],
        )

    assert rollback_calls == {
        "domains": ["coffer-kolla-ha-stage5-controller-1"],
        "volumes": ["coffer-kolla-ha-stage5-controller-1-root.qcow2"],
        "networks": ["coffer-stage5-mgmt"],
    }
    print("Stage 5 libvirt allowlist and rollback contract passed")


if __name__ == "__main__":
    main()
