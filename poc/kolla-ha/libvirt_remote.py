from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.request import urlopen


LIBVIRT_URI = "qemu:///system"
EXPECTED_CONTROLLERS = {
    f"coffer-kolla-ha-stage5-controller-{index}" for index in range(1, 4)
}
EXPECTED_STORAGE = {
    f"coffer-rgw-ha-stage5-storage-{index}" for index in range(1, 4)
}
EXPECTED_NETWORKS = {
    "coffer-stage5-mgmt",
    "coffer-stage5-storage",
    "coffer-stage5-external",
}
EXPECTED_BRIDGES = {"virbr252", "virbr253", "virbr254"}
EXPECTED_POOL = "coffer-rgw"
EXPECTED_BASE = "coffer-stage5-ubuntu-noble-base.qcow2"


class CommandFailure(RuntimeError):
    pass


def run(
    arguments: list[str],
    *,
    required: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if required and result.returncode != 0:
        raise CommandFailure(
            f"command failed ({result.returncode}): {' '.join(arguments)}\n"
            f"{result.stderr.strip()}"
        )
    return result


def virsh(
    *arguments: str,
    required: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["virsh", "--connect", LIBVIRT_URI, *arguments],
        required=required,
        timeout=timeout,
    )


def topology() -> dict[str, Any]:
    encoded = os.environ.get("COFFER_STAGE5_TOPOLOGY_B64", "")
    if not encoded:
        raise ValueError("COFFER_STAGE5_TOPOLOGY_B64 is required")
    document = json.loads(base64.b64decode(encoded, validate=True))
    if document.get("schema") != "coffer.stage5.topology.v1":
        raise ValueError("unsupported Stage 5 topology schema")
    return document


def all_domains(document: dict[str, Any]) -> list[dict[str, Any]]:
    controllers = document["domains"]["controllers"]
    storage = document["domains"]["storage"]
    if {item["name"] for item in controllers} != EXPECTED_CONTROLLERS:
        raise ValueError("controller allowlist mismatch")
    if {item["name"] for item in storage} != EXPECTED_STORAGE:
        raise ValueError("storage allowlist mismatch")
    return controllers + storage


def validate_allowlist(document: dict[str, Any]) -> None:
    if document["host_safety"]["required_pool"] != EXPECTED_POOL:
        raise ValueError("libvirt pool allowlist mismatch")
    if document["image"]["base_volume"] != EXPECTED_BASE:
        raise ValueError("base volume allowlist mismatch")
    networks = document["networks"]
    if {item["name"] for item in networks.values()} != EXPECTED_NETWORKS:
        raise ValueError("network allowlist mismatch")
    if {item["bridge"] for item in networks.values()} != EXPECTED_BRIDGES:
        raise ValueError("bridge allowlist mismatch")
    if len(all_domains(document)) != 6:
        raise ValueError("domain count allowlist mismatch")
    for item in all_domains(document):
        if not item["name"].startswith(
            ("coffer-kolla-ha-stage5-", "coffer-rgw-ha-stage5-")
        ):
            raise ValueError("domain prefix allowlist mismatch")
        for mac in item["macs"].values():
            if not re.fullmatch(r"52:54:00:c5:[0-9a-f]{2}:[0-9a-f]{2}", mac):
                raise ValueError("MAC allowlist mismatch")
    for item in networks.values():
        subnet = ipaddress.ip_network(item["cidr"])
        host_address = ipaddress.ip_address(item["host_address"])
        if host_address not in subnet:
            raise ValueError("network host address is outside its subnet")


def planned_volumes(document: dict[str, Any]) -> list[str]:
    result = [EXPECTED_BASE]
    for item in all_domains(document):
        result.extend(
            [f"{item['name']}-root.qcow2", f"{item['name']}-seed.iso"]
        )
        if "osd_gib" in item:
            result.append(f"{item['name']}-osd.raw")
    return result


def exists_domain(name: str) -> bool:
    return virsh("dominfo", name, required=False).returncode == 0


def exists_network(name: str) -> bool:
    return virsh("net-info", name, required=False).returncode == 0


def exists_volume(name: str) -> bool:
    return (
        virsh(
            "vol-info",
            "--pool",
            EXPECTED_POOL,
            name,
            required=False,
        ).returncode
        == 0
    )


def assert_absent(document: dict[str, Any]) -> None:
    collisions: list[str] = []
    for item in all_domains(document):
        if exists_domain(item["name"]):
            collisions.append(f"domain:{item['name']}")
    for item in document["networks"].values():
        if exists_network(item["name"]):
            collisions.append(f"network:{item['name']}")
    for name in planned_volumes(document):
        if exists_volume(name):
            collisions.append(f"volume:{name}")
    if collisions:
        raise ValueError(
            "refusing create because Stage 5 resources exist: "
            + ", ".join(collisions)
        )


def authorized_keys() -> list[str]:
    source = Path.home() / ".ssh" / "authorized_keys"
    keys = [
        line.strip()
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and line.split(maxsplit=1)[0].startswith(
            ("ssh-", "ecdsa-", "sk-")
        )
    ]
    if not keys:
        raise ValueError("no public SSH key is available for Stage 5 guests")
    return keys


def network_xml(item: dict[str, Any]) -> str:
    subnet = ipaddress.ip_network(item["cidr"])
    forward = (
        "  <forward mode='nat'/>\n"
        if item["mode"] == "nat"
        else ""
    )
    return (
        "<network>\n"
        f"  <name>{item['name']}</name>\n"
        f"  <bridge name='{item['bridge']}' stp='on' delay='0'/>\n"
        f"{forward}"
        f"  <ip address='{item['host_address']}' "
        f"netmask='{subnet.netmask}'/>\n"
        "</network>\n"
    )


def create_networks(
    document: dict[str, Any],
    temporary: Path,
    created_networks: list[str],
) -> None:
    for key in ("management", "storage", "external"):
        item = document["networks"][key]
        xml_path = temporary / f"{item['name']}.xml"
        xml_path.write_text(network_xml(item), encoding="utf-8")
        virsh("net-define", str(xml_path))
        created_networks.append(item["name"])
        virsh("net-start", item["name"])
        virsh("net-autostart", item["name"], "--disable")


def download_base(document: dict[str, Any], target: Path) -> None:
    image = document["image"]
    source = f"{image['source_base_url']}/{image['source_name']}"
    digest = hashlib.sha256()
    with urlopen(source, timeout=60) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != image["sha256"]:
        raise ValueError("Ubuntu image SHA-256 mismatch")


def create_base_volume(
    document: dict[str, Any],
    temporary: Path,
    created_volumes: list[str],
) -> None:
    local_image = temporary / document["image"]["source_name"]
    download_base(document, local_image)
    image_info = json.loads(
        run(
            ["qemu-img", "info", "--output=json", str(local_image)]
        ).stdout
    )
    virsh(
        "vol-create-as",
        EXPECTED_POOL,
        EXPECTED_BASE,
        str(image_info["virtual-size"]),
        "--format",
        "qcow2",
    )
    created_volumes.append(EXPECTED_BASE)
    virsh(
        "vol-upload",
        EXPECTED_BASE,
        str(local_image),
        "--pool",
        EXPECTED_POOL,
        timeout=900,
    )


def metadata(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "instance-id": item["name"],
            "local-hostname": item["name"],
        },
        indent=2,
    )


def user_data(item: dict[str, Any], keys: list[str]) -> str:
    rendered_keys = "\n".join(f"      - {json.dumps(key)}" for key in keys)
    return f"""#cloud-config
hostname: {item["name"]}
manage_etc_hosts: true
users:
  - default
  - name: ubuntu
    groups: [adm, sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
{rendered_keys}
ssh_pwauth: false
disable_root: true
package_update: false
packages:
  - qemu-guest-agent
runcmd:
  - [systemctl, enable, --now, qemu-guest-agent]
"""


def network_config(
    document: dict[str, Any],
    item: dict[str, Any],
) -> str:
    ethernets: dict[str, Any] = {
        "ens3": {
            "match": {"macaddress": item["macs"]["management"]},
            "set-name": "ens3",
            "dhcp4": False,
            "addresses": [f"{item['management_address']}/24"],
            "routes": [
                {
                    "to": "default",
                    "via": document["networks"]["management"]["host_address"],
                }
            ],
            "nameservers": {"addresses": ["1.1.1.1", "8.8.8.8"]},
        },
        "ens4": {
            "match": {"macaddress": item["macs"]["storage"]},
            "set-name": "ens4",
            "dhcp4": False,
            "addresses": [f"{item['storage_address']}/24"],
        },
    }
    if "external" in item["macs"]:
        ethernets["ens5"] = {
            "match": {"macaddress": item["macs"]["external"]},
            "set-name": "ens5",
            "dhcp4": False,
            "optional": True,
        }
    return json.dumps(
        {"version": 2, "ethernets": ethernets},
        indent=2,
    )


def create_volume(
    name: str,
    size: str,
    disk_format: str,
    created_volumes: list[str],
    *extra: str,
) -> None:
    virsh(
        "vol-create-as",
        EXPECTED_POOL,
        name,
        size,
        "--format",
        disk_format,
        *extra,
    )
    created_volumes.append(name)


def create_domain(
    document: dict[str, Any],
    item: dict[str, Any],
    temporary: Path,
    keys: list[str],
    created_domains: list[str],
    created_volumes: list[str],
) -> None:
    name = item["name"]
    guest_dir = temporary / name
    guest_dir.mkdir()
    (guest_dir / "meta-data").write_text(metadata(item), encoding="utf-8")
    (guest_dir / "user-data").write_text(
        user_data(item, keys),
        encoding="utf-8",
    )
    (guest_dir / "network-config").write_text(
        network_config(document, item),
        encoding="utf-8",
    )
    seed_path = guest_dir / "seed.iso"
    run(
        [
            "cloud-localds",
            f"--network-config={guest_dir / 'network-config'}",
            str(seed_path),
            str(guest_dir / "user-data"),
            str(guest_dir / "meta-data"),
        ]
    )

    root_name = f"{name}-root.qcow2"
    seed_name = f"{name}-seed.iso"
    create_volume(
        root_name,
        f"{item['root_gib']}G",
        "qcow2",
        created_volumes,
        "--backing-vol",
        EXPECTED_BASE,
        "--backing-vol-format",
        "qcow2",
    )
    disk_arguments = [
        "--disk",
        (
            f"vol={EXPECTED_POOL}/{root_name},bus=virtio,"
            "cache=none,discard=unmap"
        ),
    ]
    if "osd_gib" in item:
        osd_name = f"{name}-osd.raw"
        create_volume(
            osd_name,
            f"{item['osd_gib']}G",
            "raw",
            created_volumes,
            "--allocation",
            "0",
        )
        disk_arguments.extend(
            [
                "--disk",
                (
                    f"vol={EXPECTED_POOL}/{osd_name},bus=virtio,"
                    "cache=none,discard=unmap"
                ),
            ]
        )
    create_volume(
        seed_name,
        str(seed_path.stat().st_size),
        "raw",
        created_volumes,
    )
    virsh(
        "vol-upload",
        seed_name,
        str(seed_path),
        "--pool",
        EXPECTED_POOL,
    )
    disk_arguments.extend(
        [
            "--disk",
            f"vol={EXPECTED_POOL}/{seed_name},device=cdrom,bus=sata",
        ]
    )

    network_arguments = [
        "--network",
        (
            f"network={document['networks']['management']['name']},"
            f"model=virtio,mac={item['macs']['management']}"
        ),
        "--network",
        (
            f"network={document['networks']['storage']['name']},"
            f"model=virtio,mac={item['macs']['storage']}"
        ),
    ]
    if "external" in item["macs"]:
        network_arguments.extend(
            [
                "--network",
                (
                    f"network={document['networks']['external']['name']},"
                    f"model=virtio,mac={item['macs']['external']}"
                ),
            ]
        )

    try:
        run(
            [
                "virt-install",
                "--connect",
                LIBVIRT_URI,
                "--name",
                name,
                "--memory",
                str(item["memory_mib"]),
                "--vcpus",
                str(item["vcpus"]),
                "--cpu",
                "host-passthrough",
                "--os-variant",
                "ubuntu24.04",
                "--import",
                *disk_arguments,
                *network_arguments,
                "--rng",
                "/dev/urandom",
                "--graphics",
                "none",
                "--noautoconsole",
            ],
            timeout=300,
        )
    finally:
        if exists_domain(name) and name not in created_domains:
            created_domains.append(name)
    virsh("autostart", "--disable", name)


def rollback(
    created_domains: list[str],
    created_volumes: list[str],
    created_networks: list[str],
) -> None:
    for name in reversed(created_domains):
        destroy_domain(name)
    for name in reversed(created_volumes):
        if exists_volume(name):
            virsh(
                "vol-delete",
                "--pool",
                EXPECTED_POOL,
                name,
                required=False,
            )
    for name in reversed(created_networks):
        destroy_network(name)


def destroy_domain(name: str) -> None:
    if name not in EXPECTED_CONTROLLERS | EXPECTED_STORAGE:
        raise ValueError(f"refusing non-allowlisted domain: {name}")
    if not exists_domain(name):
        return
    state = virsh("domstate", name).stdout.strip()
    if state not in {"shut off", "shutoff"}:
        virsh("destroy", name)
    result = virsh("undefine", name, "--nvram", required=False)
    if result.returncode != 0:
        virsh("undefine", name)


def destroy_network(name: str) -> None:
    if name not in EXPECTED_NETWORKS:
        raise ValueError(f"refusing non-allowlisted network: {name}")
    if not exists_network(name):
        return
    fields = {
        line.partition(":")[0].strip(): line.partition(":")[2].strip()
        for line in virsh("net-info", name).stdout.splitlines()
        if ":" in line
    }
    if fields.get("Active") == "yes":
        virsh("net-destroy", name)
    virsh("net-undefine", name)


def create(document: dict[str, Any]) -> None:
    for command in ("virsh", "virt-install", "cloud-localds", "qemu-img"):
        if shutil.which(command) is None:
            raise ValueError(f"required remote command is unavailable: {command}")
    assert_absent(document)
    keys = authorized_keys()
    created_domains: list[str] = []
    created_volumes: list[str] = []
    created_networks: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="coffer-stage5-") as path:
            temporary = Path(path)
            create_networks(document, temporary, created_networks)
            create_base_volume(document, temporary, created_volumes)
            for item in all_domains(document):
                create_domain(
                    document,
                    item,
                    temporary,
                    keys,
                    created_domains,
                    created_volumes,
                )
    except BaseException:
        rollback(created_domains, created_volumes, created_networks)
        raise
    print(json.dumps(status(document), indent=2, sort_keys=True))


def destroy(document: dict[str, Any]) -> None:
    for item in reversed(all_domains(document)):
        destroy_domain(item["name"])
    for name in reversed(planned_volumes(document)):
        if exists_volume(name):
            virsh("vol-delete", "--pool", EXPECTED_POOL, name)
    for item in reversed(list(document["networks"].values())):
        destroy_network(item["name"])
    result = status(document)
    if any(item["exists"] for item in result["domains"]):
        raise RuntimeError("Stage 5 domain residue remains")
    if any(item["exists"] for item in result["volumes"]):
        raise RuntimeError("Stage 5 volume residue remains")
    if any(item["exists"] for item in result["networks"]):
        raise RuntimeError("Stage 5 network residue remains")
    print(json.dumps(result, indent=2, sort_keys=True))


def status(document: dict[str, Any]) -> dict[str, Any]:
    domain_status = []
    for item in all_domains(document):
        name = item["name"]
        exists = exists_domain(name)
        domain_status.append(
            {
                "name": name,
                "exists": exists,
                "state": (
                    virsh("domstate", name).stdout.strip() if exists else None
                ),
                "autostart_disabled": (
                    "disable"
                    in virsh("dominfo", name).stdout.lower()
                    if exists
                    else None
                ),
            }
        )
    return {
        "schema": "coffer.stage5.libvirt-status.v1",
        "domains": domain_status,
        "volumes": [
            {"name": name, "exists": exists_volume(name)}
            for name in planned_volumes(document)
        ],
        "networks": [
            {"name": item["name"], "exists": exists_network(item["name"])}
            for item in document["networks"].values()
        ],
    }


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "create",
        "destroy",
        "status",
    }:
        print(
            "usage: libvirt_remote.py {create|destroy|status}",
            file=sys.stderr,
        )
        return 64
    action = sys.argv[1]
    document = topology()
    validate_allowlist(document)
    if action == "create":
        create(document)
    elif action == "destroy":
        destroy(document)
    else:
        print(json.dumps(status(document), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
