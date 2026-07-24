from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree


LIBVIRT_URI = "qemu:///system"
TARGET = "coffer-rgw-ha-stage5-storage-3"
OTHER_DOMAINS = {
    "coffer-kolla-ha-stage5-controller-1",
    "coffer-kolla-ha-stage5-controller-2",
    "coffer-kolla-ha-stage5-controller-3",
    "coffer-rgw-ha-stage5-storage-1",
    "coffer-rgw-ha-stage5-storage-2",
}
EXPECTED_DISKS = {
    ("disk", "vda", "coffer-rgw-ha-stage5-storage-3-root.qcow2"),
    ("disk", "vdb", "coffer-rgw-ha-stage5-storage-3-osd.raw"),
    ("cdrom", "sda", "coffer-rgw-ha-stage5-storage-3-seed.iso"),
}
EXPECTED_INTERFACES = {
    ("52:54:00:c5:13:11", "coffer-stage5-mgmt"),
    ("52:54:00:c5:13:12", "coffer-stage5-storage"),
}


class CommandFailure(RuntimeError):
    pass


def virsh(*arguments: str, required: bool = True) -> str:
    result = subprocess.run(
        ["virsh", "--connect", LIBVIRT_URI, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if required and result.returncode != 0:
        raise CommandFailure(
            f"virsh {' '.join(arguments)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def domain_state(name: str) -> str:
    return virsh("domstate", name).splitlines()[0].strip()


def domain_info(name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in virsh("dominfo", name).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip()
    return result


def validate_target() -> None:
    info = domain_info(TARGET)
    if info.get("Name") != TARGET:
        raise RuntimeError("target domain name mismatch")
    if info.get("Persistent") != "yes":
        raise RuntimeError("target domain is not persistent")
    if info.get("Autostart") != "disable":
        raise RuntimeError("target domain autostart is not disabled")
    if info.get("Managed save") != "no":
        raise RuntimeError("target domain has unexpected managed state")
    if info.get("CPU(s)") != "4":
        raise RuntimeError("target domain vCPU mismatch")
    if info.get("Max memory") != "8388608 KiB":
        raise RuntimeError("target domain memory mismatch")

    root = ElementTree.fromstring(virsh("dumpxml", TARGET))
    if root.findtext("name") != TARGET or root.findtext("vcpu") != "4":
        raise RuntimeError("target domain XML identity mismatch")
    memory = root.find("memory")
    if (
        memory is None
        or memory.get("unit") != "KiB"
        or memory.text != "8388608"
    ):
        raise RuntimeError("target domain XML memory mismatch")

    disks: set[tuple[str, str, str]] = set()
    for disk in root.findall("./devices/disk"):
        source = disk.find("source")
        target = disk.find("target")
        if source is None or target is None:
            raise RuntimeError("target domain has an incomplete disk")
        source_path = source.get("file")
        if not source_path:
            raise RuntimeError("target domain disk is not file-backed")
        disks.add(
            (
                disk.get("device", ""),
                target.get("dev", ""),
                Path(source_path).name,
            )
        )
    if disks != EXPECTED_DISKS:
        raise RuntimeError("target domain disk allowlist mismatch")

    interfaces: set[tuple[str, str]] = set()
    for interface in root.findall("./devices/interface"):
        mac = interface.find("mac")
        source = interface.find("source")
        if mac is None or source is None:
            raise RuntimeError("target domain has an incomplete interface")
        interfaces.add(
            (
                mac.get("address", "").lower(),
                source.get("network", ""),
            )
        )
    if interfaces != EXPECTED_INTERFACES:
        raise RuntimeError("target domain interface allowlist mismatch")


def require_other_domains_running() -> None:
    for name in sorted(OTHER_DOMAINS):
        if domain_state(name) != "running":
            raise RuntimeError(f"unrelated Stage 5 domain is not running: {name}")


def wait_for_state(expected: str, attempts: int = 120) -> None:
    state = domain_state(TARGET)
    for _ in range(attempts):
        state = domain_state(TARGET)
        if state == expected:
            return
        time.sleep(1)
    raise RuntimeError(f"target state is {state}, expected {expected}")


def output(action: str) -> None:
    print(
        json.dumps(
            {
                "action": action,
                "autostart_disabled": True,
                "other_domains_running": len(OTHER_DOMAINS),
                "state": domain_state(TARGET),
                "target": TARGET,
            },
            sort_keys=True,
        )
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: storage_vm_fault_remote.py ACTION")
    action = sys.argv[1]
    validate_target()
    require_other_domains_running()

    if action in {"preflight", "status"}:
        if domain_state(TARGET) != "running":
            raise RuntimeError("target domain is not running")
    elif action == "poweroff":
        if domain_state(TARGET) != "running":
            raise RuntimeError("refusing to power off a non-running target")
        virsh("destroy", TARGET)
        wait_for_state("shut off")
    elif action == "restore":
        state = domain_state(TARGET)
        if state == "shut off":
            virsh("start", TARGET)
        elif state != "running":
            raise RuntimeError(f"refusing unexpected target state: {state}")
        wait_for_state("running")
    else:
        raise SystemExit("refusing an unknown VM fault action")

    require_other_domains_running()
    output(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
