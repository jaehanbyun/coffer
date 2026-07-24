#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 ]]; then
    echo "usage: $0 <ssh-target>" >&2
    exit 64
fi

ssh_target="$1"
if [[ -z "${ssh_target}" || "${ssh_target}" == -* ]]; then
    echo "refusing an empty or option-shaped SSH target" >&2
    exit 64
fi

ssh \
    -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -- "${ssh_target}" python3 - <<'PYTHON'
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from typing import Any


def run(arguments: list[str], *, required: bool = True) -> str:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if required and result.returncode != 0:
        raise RuntimeError(
            f"read-only command failed ({result.returncode}): "
            + " ".join(arguments)
        )
    return result.stdout.strip()


def parse_colon_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip().lower().replace(" ", "_")] = value.strip()
    return fields


def numeric_prefix(value: str) -> int:
    return int(value.split()[0])


def parse_memory() -> dict[str, int]:
    selected = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    result: dict[str, int] = {}
    with open("/proc/meminfo", encoding="utf-8") as source:
        for line in source:
            key, value = line.split(":", maxsplit=1)
            if key in selected:
                result[f"{key.lower()}_bytes"] = int(value.split()[0]) * 1024
    return result


def filesystem(path: str) -> dict[str, Any]:
    stats = os.statvfs(path)
    return {
        "path": path,
        "size_bytes": stats.f_blocks * stats.f_frsize,
        "available_bytes": stats.f_bavail * stats.f_frsize,
    }


def json_command(arguments: list[str]) -> list[dict[str, Any]]:
    output = run(arguments, required=False)
    return json.loads(output) if output else []


def virsh(*arguments: str, required: bool = True) -> str:
    return run(
        ["virsh", "--connect", "qemu:///system", *arguments],
        required=required,
    )


def domains() -> list[dict[str, Any]]:
    names = [
        name.strip()
        for name in virsh("list", "--all", "--name").splitlines()
        if name.strip()
    ]
    result: list[dict[str, Any]] = []
    for name in names:
        fields = parse_colon_fields(virsh("dominfo", name))
        interfaces: list[dict[str, str]] = []
        for line in virsh("domiflist", name, required=False).splitlines():
            columns = line.split()
            if (
                len(columns) >= 5
                and columns[0] != "Interface"
                and not set(columns[0]) <= {"-"}
            ):
                interfaces.append(
                    {
                        "interface": columns[0],
                        "type": columns[1],
                        "source": columns[2],
                        "model": columns[3],
                        "mac": columns[4].lower(),
                    }
                )
        result.append(
            {
                "name": name,
                "state": fields.get("state", ""),
                "autostart": fields.get("autostart", ""),
                "vcpus": int(fields.get("cpu(s)", "0")),
                "max_memory_kib": int(
                    fields.get("max_memory", "0 KiB").split()[0]
                ),
                "interfaces": interfaces,
            }
        )
    return result


def pools() -> list[dict[str, Any]]:
    names = [
        name.strip()
        for name in virsh("pool-list", "--all", "--name").splitlines()
        if name.strip()
    ]
    result: list[dict[str, Any]] = []
    for name in names:
        fields = parse_colon_fields(virsh("pool-info", name, "--bytes"))
        result.append(
            {
                "name": name,
                "state": fields.get("state", ""),
                "autostart": fields.get("autostart", ""),
                "capacity_bytes": numeric_prefix(
                    fields.get("capacity", "0")
                ),
                "allocation_bytes": numeric_prefix(
                    fields.get("allocation", "0")
                ),
                "available_bytes": numeric_prefix(
                    fields.get("available", "0")
                ),
            }
        )
    return result


def networks() -> list[dict[str, str]]:
    names = [
        name.strip()
        for name in virsh("net-list", "--all", "--name").splitlines()
        if name.strip()
    ]
    return [
        {
            "name": name,
            **{
                key: value
                for key, value in parse_colon_fields(
                    virsh("net-info", name)
                ).items()
                if key in {"active", "persistent", "autostart", "bridge"}
            },
        }
        for name in names
    ]


def pool_volumes(pool_name: str) -> list[dict[str, Any]]:
    listing = virsh("vol-list", "--pool", pool_name, required=False)
    names = [
        line.split(maxsplit=1)[0]
        for line in listing.splitlines()
        if line.strip()
        and not line.lstrip().startswith("Name ")
        and not set(line.strip()) <= {"-"}
    ]
    result: list[dict[str, Any]] = []
    for name in names:
        fields = parse_colon_fields(
            virsh(
                "vol-info",
                "--pool",
                pool_name,
                name,
                "--bytes",
            )
        )
        result.append(
            {
                "name": name,
                "capacity_bytes": numeric_prefix(
                    fields.get("capacity", "0")
                ),
                "allocation_bytes": numeric_prefix(
                    fields.get("allocation", "0")
                ),
            }
        )
    return result


def service_state(name: str) -> str:
    state = run(["systemctl", "is-active", name], required=False)
    return state or "unavailable"


def docker_containers() -> list[dict[str, str]]:
    if shutil.which("docker") is None:
        return []
    output = run(
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
        ],
        required=False,
    )
    result: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) == 4:
            result.append(
                dict(zip(("name", "image", "status", "ports"), fields))
            )
    return result


domain_inventory = domains()
pool_inventory = pools()
host_addresses = json_command(["ip", "-json", "address", "show"])
host_routes = json_command(["ip", "-json", "route", "show", "table", "all"])
report = {
    "schema": "coffer.stage5.host-inventory.v1",
    "host": {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "load_average": list(os.getloadavg()),
        "memory": parse_memory(),
        "storage": filesystem("/srv/nfs"),
        "network": {
            "interfaces": [
                {
                    "name": item.get("ifname", ""),
                    "ipv4_addresses": [
                        {
                            "address": address.get("local", ""),
                            "prefix_length": address.get("prefixlen", 0),
                        }
                        for address in item.get("addr_info", [])
                        if address.get("family") == "inet"
                    ],
                }
                for item in host_addresses
            ],
            "routes": [
                {
                    key: route[key]
                    for key in ("dst", "gateway", "dev")
                    if key in route
                }
                for route in host_routes
                if route.get("family", "inet") == "inet"
            ],
        },
    },
    "services": {
        name: service_state(name)
        for name in ("libvirtd", "virtqemud", "docker", "haproxy")
    },
    "libvirt": {
        "domains": domain_inventory,
        "domain_count": len(domain_inventory),
        "running_domain_count": sum(
            item["state"] == "running" for item in domain_inventory
        ),
        "allocated_vcpus": sum(item["vcpus"] for item in domain_inventory),
        "allocated_max_memory_kib": sum(
            item["max_memory_kib"] for item in domain_inventory
        ),
        "pools": pool_inventory,
        "networks": networks(),
        "coffer_pool_volumes": pool_volumes("coffer-rgw"),
        "default_network_leases": virsh(
            "net-dhcp-leases", "default", required=False
        ).splitlines(),
        "default_network_neighbors": json_command(
            ["ip", "-json", "neigh", "show", "dev", "virbr0"]
        ),
    },
    "listeners": run(["ss", "-H", "-lnt"], required=False).splitlines(),
    "docker_containers": docker_containers(),
}

print(json.dumps(report, indent=2, sort_keys=True))
PYTHON
