#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import yaml


def load_json(path: str) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != "coffer.stage5.host-inventory.v1":
        raise RuntimeError(f"unexpected host inventory schema: {path}")
    return document


def load_topology(path: str) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != "coffer.stage5.topology.v1":
        raise RuntimeError("unexpected topology schema")
    return document


def domains(topology: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *topology["domains"]["controllers"],
        *topology["domains"]["storage"],
    ]


def planned_volumes(topology: dict[str, Any]) -> set[str]:
    names = {topology["image"]["base_volume"]}
    for item in domains(topology):
        name = item["name"]
        names.update({f"{name}-root.qcow2", f"{name}-seed.iso"})
        if "osd_gib" in item:
            names.add(f"{name}-osd.raw")
    return names


def by_name(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in items}


def domain_signature(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "autostart": item["autostart"],
        "vcpus": item["vcpus"],
        "max_memory_kib": item["max_memory_kib"],
        "interfaces": sorted(
            item["interfaces"],
            key=lambda interface: interface["mac"],
        ),
    }


def network_signature(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item)


def volume_signature(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "capacity_bytes": item["capacity_bytes"],
    }


def docker_signature(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item["name"],
        "image": item["image"],
        "ports": item["ports"],
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def autostart_disabled(value: str) -> bool:
    return value.lower() in {"disable", "disabled", "no"}


def audit_preflight(
    topology: dict[str, Any],
    inventory: dict[str, Any],
) -> None:
    expected_domains = {item["name"] for item in domains(topology)}
    expected_networks = {
        item["name"]: item for item in topology["networks"].values()
    }
    expected_volumes = planned_volumes(topology)
    live_domains = by_name(inventory["libvirt"]["domains"])
    live_networks = by_name(inventory["libvirt"]["networks"])
    live_volumes = by_name(inventory["libvirt"]["coffer_pool_volumes"])

    prefixed_domains = {
        name
        for name in live_domains
        if name.startswith(("coffer-kolla-ha-stage5-", "coffer-rgw-ha-stage5-"))
    }
    require(
        prefixed_domains == expected_domains,
        "Stage 5 domain allowlist changed",
    )
    for name in expected_domains:
        item = live_domains[name]
        require(item["state"] == "running", f"Stage 5 domain is not running: {name}")
        require(
            autostart_disabled(item["autostart"]),
            f"Stage 5 domain autostart changed: {name}",
        )

    prefixed_networks = {
        name for name in live_networks if name.startswith("coffer-stage5-")
    }
    require(
        prefixed_networks == set(expected_networks),
        "Stage 5 network allowlist changed",
    )
    for name, expected in expected_networks.items():
        item = live_networks[name]
        require(item.get("active") == "yes", f"Stage 5 network inactive: {name}")
        require(
            autostart_disabled(item.get("autostart", "")),
            f"Stage 5 network autostart changed: {name}",
        )
        require(
            item.get("bridge") == expected["bridge"],
            f"Stage 5 bridge changed: {name}",
        )

    prefixed_volumes = {
        name
        for name in live_volumes
        if name.startswith(
            (
                "coffer-stage5-",
                "coffer-kolla-ha-stage5-",
                "coffer-rgw-ha-stage5-",
            )
        )
    }
    require(
        prefixed_volumes == expected_volumes,
        "Stage 5 volume allowlist changed",
    )
    require(
        "coffer-rgw-poc" in live_domains,
        "retained coffer-rgw-poc domain is absent",
    )
    require(
        autostart_disabled(live_domains["coffer-rgw-poc"]["autostart"]),
        "retained coffer-rgw-poc autostart changed",
    )
    print(
        "stage5_teardown_audit state=ready "
        f"domains={len(expected_domains)} volumes={len(expected_volumes)} "
        f"networks={len(expected_networks)} retained_rgw=present"
    )


def require_equal_signatures(
    label: str,
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    signature: Any,
) -> None:
    require(set(before) == set(after), f"unrelated {label} names changed")
    for name in before:
        require(
            signature(before[name]) == signature(after[name]),
            f"unrelated {label} definition changed: {name}",
        )


def audit_post(
    topology: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    stage_domains = {item["name"] for item in domains(topology)}
    stage_networks = {
        item["name"] for item in topology["networks"].values()
    }
    stage_bridges = {
        item["bridge"] for item in topology["networks"].values()
    }
    stage_volumes = planned_volumes(topology)

    before_domains = by_name(before["libvirt"]["domains"])
    after_domains = by_name(after["libvirt"]["domains"])
    before_networks = by_name(before["libvirt"]["networks"])
    after_networks = by_name(after["libvirt"]["networks"])
    before_volumes = by_name(before["libvirt"]["coffer_pool_volumes"])
    after_volumes = by_name(after["libvirt"]["coffer_pool_volumes"])

    require(stage_domains.isdisjoint(after_domains), "Stage 5 domain residue")
    require(stage_networks.isdisjoint(after_networks), "Stage 5 network residue")
    require(stage_volumes.isdisjoint(after_volumes), "Stage 5 volume residue")
    require(
        not any(
            name.startswith(
                ("coffer-kolla-ha-stage5-", "coffer-rgw-ha-stage5-")
            )
            for name in after_domains
        ),
        "unexpected Stage 5-prefixed domain residue",
    )
    require(
        not any(name.startswith("coffer-stage5-") for name in after_networks),
        "unexpected Stage 5-prefixed network residue",
    )
    require(
        not any(
            name.startswith(
                (
                    "coffer-stage5-",
                    "coffer-kolla-ha-stage5-",
                    "coffer-rgw-ha-stage5-",
                )
            )
            for name in after_volumes
        ),
        "unexpected Stage 5-prefixed volume residue",
    )

    unrelated_before_domains = {
        name: item
        for name, item in before_domains.items()
        if name not in stage_domains
    }
    unrelated_before_networks = {
        name: item
        for name, item in before_networks.items()
        if name not in stage_networks
    }
    unrelated_before_volumes = {
        name: item
        for name, item in before_volumes.items()
        if name not in stage_volumes
    }
    require_equal_signatures(
        "domain",
        unrelated_before_domains,
        after_domains,
        domain_signature,
    )
    require_equal_signatures(
        "network",
        unrelated_before_networks,
        after_networks,
        network_signature,
    )
    require_equal_signatures(
        "volume",
        unrelated_before_volumes,
        after_volumes,
        volume_signature,
    )

    before_docker = by_name(before["docker_containers"])
    after_docker = by_name(after["docker_containers"])
    require_equal_signatures(
        "host Docker container",
        before_docker,
        after_docker,
        docker_signature,
    )
    require(
        before["services"] == after["services"],
        "shared-host service state changed",
    )
    live_interfaces = {
        interface["name"] for interface in after["host"]["network"]["interfaces"]
    }
    require(
        stage_bridges.isdisjoint(live_interfaces),
        "Stage 5 host bridge residue",
    )
    require(
        "coffer-rgw-poc" in after_domains,
        "retained coffer-rgw-poc domain is absent after teardown",
    )
    print(
        "stage5_teardown_audit state=removed domains=0 volumes=0 networks=0 "
        f"unrelated_domains={len(after_domains)} "
        f"unrelated_networks={len(after_networks)} "
        f"unrelated_volumes={len(after_volumes)} retained_rgw=present"
    )


def main() -> int:
    if len(sys.argv) not in {4, 5}:
        raise SystemExit(
            "usage: audit-teardown.py {preflight|post} "
            "TOPOLOGY BEFORE [AFTER]"
        )
    action = sys.argv[1]
    topology = load_topology(sys.argv[2])
    before = load_json(sys.argv[3])
    if action == "preflight" and len(sys.argv) == 4:
        audit_preflight(topology, before)
    elif action == "post" and len(sys.argv) == 5:
        audit_preflight(topology, before)
        audit_post(topology, before, load_json(sys.argv[4]))
    else:
        raise SystemExit("invalid teardown audit action")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
