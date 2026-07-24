from __future__ import annotations

import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


GIB = 1024**3


def main() -> int:
    topology_path = Path(sys.argv[1])
    inventory_path = Path(sys.argv[2])
    topology = yaml.safe_load(topology_path.read_text(encoding="utf-8"))
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    def unique(values: list[str], label: str) -> None:
        require(len(values) == len(set(values)), f"{label} must be unique")

    require(
        topology.get("schema") == "coffer.stage5.topology.v1",
        "unsupported topology schema",
    )
    require(
        inventory.get("schema") == "coffer.stage5.host-inventory.v1",
        "unsupported host inventory schema",
    )

    safety = topology["host_safety"]
    host = inventory["host"]
    libvirt = inventory["libvirt"]
    budget = topology["budget"]
    controllers = topology["domains"]["controllers"]
    storage_nodes = topology["domains"]["storage"]
    domains = controllers + storage_nodes
    networks = topology["networks"]

    require(
        host["architecture"] == safety["required_architecture"],
        "host architecture does not match the Stage 5 topology",
    )
    require(
        host["logical_cpus"] >= safety["required_logical_cpus"],
        "host logical CPU count is below the Stage 5 minimum",
    )

    pool = next(
        (
            item
            for item in libvirt["pools"]
            if item["name"] == safety["required_pool"]
        ),
        None,
    )
    require(pool is not None, "required libvirt pool is absent")
    if pool is not None:
        require(
            pool["state"] == "running",
            "required libvirt pool is not running",
        )

    calculated_budget = {
        "domain_count": len(domains),
        "vcpus": sum(item["vcpus"] for item in domains),
        "memory_gib": sum(item["memory_mib"] for item in domains) // 1024,
        "root_disk_gib": sum(item["root_gib"] for item in domains),
        "osd_disk_gib": sum(item.get("osd_gib", 0) for item in domains),
    }
    calculated_budget["total_logical_disk_gib"] = (
        calculated_budget["root_disk_gib"]
        + calculated_budget["osd_disk_gib"]
    )
    for key, value in calculated_budget.items():
        require(
            budget.get(key) == value,
            f"declared budget {key} does not match the domain sum",
        )

    available_memory_gib = host["memory"]["memavailable_bytes"] / GIB
    filesystem_available_gib = host["storage"]["available_bytes"] / GIB
    pool_available_gib = (
        pool["available_bytes"] / GIB if pool is not None else 0
    )
    minimum_memory = (
        budget["memory_gib"]
        + safety["minimum_available_memory_gib_after_allocation"]
    )
    minimum_storage = (
        budget["total_logical_disk_gib"]
        + safety["minimum_available_storage_gib_after_allocation"]
    )
    require(
        available_memory_gib >= minimum_memory,
        "live available memory cannot preserve the configured safety margin",
    )
    require(
        filesystem_available_gib >= minimum_storage,
        "live filesystem capacity cannot preserve the configured safety margin",
    )
    require(
        pool_available_gib >= minimum_storage,
        "live libvirt pool capacity cannot preserve the configured safety margin",
    )

    image_checksum = str(topology["image"]["sha256"])
    require(
        re.fullmatch(r"[0-9a-f]{64}", image_checksum) is not None,
        "image.sha256 must be a resolved lowercase SHA-256",
    )

    domain_names = [item["name"] for item in domains]
    unique(domain_names, "planned domain names")
    existing_domain_names = {item["name"] for item in libvirt["domains"]}
    for prefix in safety["forbidden_existing_domain_prefixes"]:
        require(
            not any(name.startswith(prefix) for name in existing_domain_names),
            f"existing domain uses forbidden Stage 5 prefix {prefix}",
        )
    for name in domain_names:
        require(
            name not in existing_domain_names,
            f"domain already exists: {name}",
        )

    planned_volume_names = [topology["image"]["base_volume"]]
    for item in domains:
        planned_volume_names.extend(
            [f"{item['name']}-root.qcow2", f"{item['name']}-seed.iso"]
        )
        if "osd_gib" in item:
            planned_volume_names.append(f"{item['name']}-osd.raw")
    unique(planned_volume_names, "planned volume names")
    existing_volume_names = {
        item["name"] for item in libvirt["coffer_pool_volumes"]
    }
    for name in planned_volume_names:
        require(
            name not in existing_volume_names,
            f"volume already exists: {name}",
        )

    planned_network_names = [item["name"] for item in networks.values()]
    planned_bridges = [item["bridge"] for item in networks.values()]
    unique(planned_network_names, "planned network names")
    unique(planned_bridges, "planned bridge names")
    existing_network_names = {item["name"] for item in libvirt["networks"]}
    existing_bridges = {
        item["bridge"] for item in libvirt["networks"] if item.get("bridge")
    }
    for name in planned_network_names:
        require(
            name not in existing_network_names,
            f"network already exists: {name}",
        )
    for bridge in planned_bridges:
        require(
            bridge not in existing_bridges,
            f"bridge already exists: {bridge}",
        )

    planned_subnets = {
        name: ipaddress.ip_network(item["cidr"])
        for name, item in networks.items()
    }
    for name, subnet in planned_subnets.items():
        for other_name, other_subnet in planned_subnets.items():
            if name < other_name:
                require(
                    not subnet.overlaps(other_subnet),
                    f"planned subnets overlap: {name} and {other_name}",
                )

    existing_subnets: list[ipaddress.IPv4Network] = []
    existing_ip_addresses: set[ipaddress.IPv4Address] = set()
    for interface in host["network"]["interfaces"]:
        for address in interface["ipv4_addresses"]:
            parsed = ipaddress.ip_interface(
                f"{address['address']}/{address['prefix_length']}"
            )
            existing_ip_addresses.add(parsed.ip)
            existing_subnets.append(parsed.network)
    for route in host["network"]["routes"]:
        destination = route.get("dst")
        if destination and destination != "default":
            try:
                existing_subnets.append(ipaddress.ip_network(destination))
            except ValueError:
                failures.append(f"unparseable host route: {destination}")
    for name, subnet in planned_subnets.items():
        require(
            not any(subnet.overlaps(existing) for existing in existing_subnets),
            f"planned subnet overlaps live host state: {name}",
        )

    for neighbor in libvirt["default_network_neighbors"]:
        destination = neighbor.get("dst")
        if destination:
            existing_ip_addresses.add(ipaddress.ip_address(destination))
    for line in libvirt["default_network_leases"]:
        matches = re.findall(
            r"\b(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}\b",
            line,
        )
        for match in matches:
            existing_ip_addresses.add(ipaddress.ip_interface(match).ip)

    planned_addresses: list[ipaddress.IPv4Address] = []
    for network_name, network in networks.items():
        subnet = planned_subnets[network_name]
        for key, value in network.items():
            if (
                key.endswith("_address")
                or key.endswith("_vip")
                or key == "rgw_virtual_ip"
            ):
                address = ipaddress.ip_address(value)
                require(
                    address in subnet,
                    f"{network_name}.{key} is outside its subnet",
                )
                planned_addresses.append(address)
    for item in domains:
        for key, network_name in (
            ("management_address", "management"),
            ("storage_address", "storage"),
        ):
            address = ipaddress.ip_address(item[key])
            require(
                address in planned_subnets[network_name],
                f"{item['name']} {key} is outside its subnet",
            )
            planned_addresses.append(address)
    unique([str(item) for item in planned_addresses], "planned IPv4 addresses")
    for address in planned_addresses:
        require(
            address not in existing_ip_addresses,
            f"planned IPv4 address is already in use: {address}",
        )

    planned_macs = [
        mac.lower() for item in domains for mac in item["macs"].values()
    ]
    unique(planned_macs, "planned MAC addresses")
    existing_macs = {
        interface["mac"].lower()
        for domain in libvirt["domains"]
        for interface in domain.get("interfaces", [])
    }
    for mac in planned_macs:
        require(
            re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac) is not None,
            f"invalid planned MAC address: {mac}",
        )
        require(
            mac not in existing_macs,
            f"planned MAC is already in use: {mac}",
        )

    if failures:
        for failure in failures:
            print(f"preflight failure: {failure}", file=sys.stderr)
        return 1

    result: dict[str, Any] = {
        "schema": "coffer.stage5.preflight.v1",
        "status": "passed",
        "host": host["hostname"],
        "planned_domains": len(domains),
        "planned_vcpus": budget["vcpus"],
        "memory_available_after_budget_gib": round(
            available_memory_gib - budget["memory_gib"],
            1,
        ),
        "filesystem_available_after_budget_gib": round(
            filesystem_available_gib - budget["total_logical_disk_gib"],
            1,
        ),
        "pool_available_after_budget_gib": round(
            pool_available_gib - budget["total_logical_disk_gib"],
            1,
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
