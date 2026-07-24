from __future__ import annotations

from pathlib import Path
import sys


PINNED_COMMIT = "cec5b77ddc0af37e9b9a8df92f7458ae014fb5dc"
BOUNDARY = "[baremetal:children]"
CONTROLLERS = (
    ("coffer-kolla-ha-stage5-controller-1", "192.168.252.11", "local"),
    ("coffer-kolla-ha-stage5-controller-2", "192.168.252.12", "ssh"),
    ("coffer-kolla-ha-stage5-controller-3", "192.168.252.13", "ssh"),
)
PRIVATE_KEY = "/home/ubuntu/.ssh/coffer-stage5-kolla"
KNOWN_HOSTS = "/home/ubuntu/.ssh/coffer-stage5-known_hosts"


def controller_line(name: str, address: str, connection: str) -> str:
    values = [name, f"ansible_host={address}", "ansible_user=ubuntu"]
    if connection == "local":
        values.append("ansible_connection=local")
    else:
        values.append(f"ansible_ssh_private_key_file={PRIVATE_KEY}")
        values.append(
            "ansible_ssh_common_args="
            f"'-o UserKnownHostsFile={KNOWN_HOSTS} "
            "-o StrictHostKeyChecking=yes'"
        )
    return " ".join(values)


def render(source: Path) -> str:
    document = source.read_text(encoding="utf-8")
    if document.count(BOUNDARY) != 1:
        raise RuntimeError("upstream multinode boundary changed")
    _, tail = document.split(BOUNDARY, maxsplit=1)
    hosts = "\n".join(controller_line(*item) for item in CONTROLLERS)
    return (
        "# Generated from the pinned Kolla-Ansible multinode inventory.\n"
        f"# Upstream commit: {PINNED_COMMIT}\n\n"
        "[control]\n"
        f"{hosts}\n\n"
        "[network]\n"
        f"{hosts}\n\n"
        "[compute]\n\n"
        "[monitoring]\n\n"
        "[storage]\n\n"
        "[deployment]\n"
        "localhost ansible_connection=local\n\n"
        f"{BOUNDARY}{tail}"
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: render-kolla-inventory.py UPSTREAM_MULTINODE OUTPUT"
        )
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    rendered = render(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
