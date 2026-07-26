from __future__ import annotations

import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urlsplit


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent
POC_DIRECTORY = LOAD_DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


native_target = _module(
    "coffer_load_native_target_renderer_target",
    DIRECTORY / "native_target.py",
)
load_contract = _module(
    "coffer_load_native_target_renderer_load_contract",
    LOAD_DIRECTORY / "state_machine.py",
)
observability_contract = _module(
    "coffer_load_native_target_renderer_observability_contract",
    POC_DIRECTORY / "observability" / "contract.py",
)

REQUEST_SCHEMA = "coffer.load-telemetry-native-target-render-request/v1"
RESULT_SCHEMA = "coffer.load-telemetry-native-target-render-result/v1"
SOURCE_RESULT_SCHEMA = (
    "coffer.load-telemetry-native-target-source-result/v1"
)
MAX_REQUEST_BYTES = 64 * 1024
SOURCE_FILES = (
    DIRECTORY / "native_surfaces.py",
    DIRECTORY / "native_target.py",
    DIRECTORY / "render_target.py",
)
ORIGIN_KEYS = frozenset(
    {
        "ceph_exporter",
        "ceph_mgr",
        "evidence",
        "galera",
        "haproxy",
        "hosts",
        "prometheus",
        "rgw_ingress",
    }
)
INVENTORY_KEYS = frozenset(
    {
        "controllers",
        "reconcile_hosts",
        "rgw_daemons",
        "rgw_ingress_hosts",
        "storage_hosts",
    }
)


class RenderError(RuntimeError):
    pass


def _exact(
    value: object,
    keys: set[str] | frozenset[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise RenderError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def adapter_source_sha256() -> str:
    files: list[dict[str, str]] = []
    try:
        for path in SOURCE_FILES:
            files.append(
                {
                    "path": path.name,
                    "sha256": (
                        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                    ),
                }
            )
    except OSError as error:
        raise RenderError("adapter source is unavailable") from error
    return _hash({"files": files})


def _sorted_hosts(
    value: object,
    *,
    category: str,
    length: int,
) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) != length
        or len(set(value)) != length
    ):
        raise RenderError(f"{category} changed")
    try:
        hosts = [
            native_target._host(item, category)
            for item in value
        ]
    except native_target.NativeTargetError as error:
        raise RenderError(f"{category} changed") from error
    if hosts != sorted(hosts):
        raise RenderError(f"{category} order changed")
    return hosts


def _inventory(
    value: object,
    *,
    load_topology: Mapping[str, Any],
) -> dict[str, Any]:
    inventory = _exact(value, INVENTORY_KEYS, "pilot inventory")
    replicas = load_topology["replicas"]
    controllers = _sorted_hosts(
        inventory["controllers"],
        category="controller hosts",
        length=int(replicas["galera"]),
    )
    storage_hosts = _sorted_hosts(
        inventory["storage_hosts"],
        category="storage hosts",
        length=int(replicas["rgw"]),
    )
    if set(controllers) & set(storage_hosts):
        raise RenderError("pilot host roles overlap")
    reconcile_hosts = _sorted_hosts(
        inventory["reconcile_hosts"],
        category="reconcile hosts",
        length=int(replicas["reconcile"]),
    )
    if not set(reconcile_hosts) <= set(controllers):
        raise RenderError("reconcile host topology changed")
    rgw_ingress_hosts = _sorted_hosts(
        inventory["rgw_ingress_hosts"],
        category="RGW ingress hosts",
        length=int(replicas["rgw-ingress"]),
    )
    if not set(rgw_ingress_hosts) <= set(storage_hosts):
        raise RenderError("RGW ingress host topology changed")
    raw_daemons = inventory["rgw_daemons"]
    if (
        not isinstance(raw_daemons, Mapping)
        or len(raw_daemons) != int(replicas["rgw"])
    ):
        raise RenderError("RGW daemon topology changed")
    try:
        rgw_daemons = {
            native_target._name(daemon, "RGW daemon"): native_target._host(
                host,
                "RGW daemon host",
            )
            for daemon, host in raw_daemons.items()
        }
    except native_target.NativeTargetError as error:
        raise RenderError("RGW daemon topology changed") from error
    if (
        any(not daemon.startswith("rgw.") for daemon in rgw_daemons)
        or set(rgw_daemons.values()) != set(storage_hosts)
    ):
        raise RenderError("RGW daemon topology changed")
    return {
        "controllers": controllers,
        "reconcile_hosts": reconcile_hosts,
        "rgw_daemons": dict(sorted(rgw_daemons.items())),
        "rgw_ingress_hosts": rgw_ingress_hosts,
        "storage_hosts": storage_hosts,
    }


def _origin(value: object, category: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RenderError(f"{category} origin is invalid")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise RenderError(f"{category} origin is invalid") from error
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RenderError(f"{category} origin is invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is None:
        if (
            native_target.HOST_PATTERN.fullmatch(hostname) is None
            or hostname != hostname.lower()
            or hostname.endswith(".")
        ):
            raise RenderError(f"{category} origin is invalid")
        rendered_host = hostname
    else:
        rendered_host = (
            f"[{address.compressed}]"
            if address.version == 6
            else address.compressed
        )
    canonical = f"https://{rendered_host}:{port}"
    if value != canonical:
        raise RenderError(f"{category} origin is not canonical")
    return canonical


def _origins(
    value: object,
    *,
    controllers: Sequence[str],
    hosts: Sequence[str],
) -> dict[str, Any]:
    origins = _exact(value, ORIGIN_KEYS, "telemetry origins")
    galera_raw = _exact(
        origins["galera"],
        set(controllers),
        "Galera origins",
    )
    hosts_raw = _exact(
        origins["hosts"],
        set(hosts),
        "node-exporter origins",
    )
    return {
        "ceph_exporter": _origin(
            origins["ceph_exporter"],
            "ceph-exporter",
        ),
        "ceph_mgr": _origin(origins["ceph_mgr"], "Ceph mgr"),
        "evidence": _origin(origins["evidence"], "auxiliary evidence"),
        "galera": {
            host: _origin(galera_raw[host], f"{host} Galera")
            for host in controllers
        },
        "haproxy": _origin(origins["haproxy"], "HAProxy"),
        "hosts": {
            host: _origin(hosts_raw[host], f"{host} node-exporter")
            for host in hosts
        },
        "prometheus": _origin(origins["prometheus"], "Prometheus"),
        "rgw_ingress": _origin(
            origins["rgw_ingress"],
            "RGW ingress",
        ),
    }


def _json_endpoint(url: str) -> dict[str, Any]:
    return {
        "content_types": list(native_target.JSON_CONTENT_TYPES),
        "url": url,
    }


def _exposition_endpoint(url: str) -> dict[str, Any]:
    return {
        "content_types": list(native_target.EXPOSITION_CONTENT_TYPES),
        "url": url,
    }


def _evidence_urls(origin: str, surface: str) -> dict[str, Any]:
    return {
        phase: _json_endpoint(
            f"{origin}/v1/evidence/{surface}/{phase}"
        )
        for phase in native_target.PHASES
    }


def render_request(
    value: object,
) -> dict[str, Any]:
    request = _exact(
        value,
        {
            "adapter_source_sha256",
            "inventory",
            "load_topology_sha256",
            "observability_topology_sha256",
            "origins",
            "schema",
            "target_class",
        },
        "native target render request",
    )
    load_topology = load_contract.load_topology(
        LOAD_DIRECTORY / "topology.json"
    )
    observability_topology = observability_contract.load_topology(
        POC_DIRECTORY / "observability" / "topology.json"
    )
    load_topology_sha256 = native_target._hash(load_topology)
    observability_topology_sha256 = native_target._hash(
        observability_topology.raw
    )
    current_source_sha256 = adapter_source_sha256()
    if (
        request["schema"] != REQUEST_SCHEMA
        or request["target_class"] != native_target.TARGET_CLASS
        or request["adapter_source_sha256"] != current_source_sha256
        or request["load_topology_sha256"] != load_topology_sha256
        or request["observability_topology_sha256"]
        != observability_topology_sha256
    ):
        raise RenderError("native target render binding changed")
    inventory = _inventory(
        request["inventory"],
        load_topology=load_topology,
    )
    all_hosts = [
        *inventory["controllers"],
        *inventory["storage_hosts"],
    ]
    origins = _origins(
        request["origins"],
        controllers=inventory["controllers"],
        hosts=all_hosts,
    )
    component_instances = {
        "api": list(inventory["controllers"]),
        "edge": list(inventory["controllers"]),
        "reconcile": list(inventory["reconcile_hosts"]),
        "registry": list(inventory["controllers"]),
    }
    queries = {
        name: {
            "content_types": list(native_target.JSON_CONTENT_TYPES),
            "promql": promql,
            "promql_sha256": native_target._text_hash(promql),
            "url": (
                f"{origins['prometheus']}/api/v1/query?"
                f"{urlencode([('query', promql)])}"
            ),
        }
        for name, promql in native_target.PROMQL.items()
    }
    required_rules = [
        *load_topology["required_recording_rules"],
        *load_topology["required_alerts"],
    ]
    rules_url = (
        f"{origins['prometheus']}/api/v1/rules?"
        f"{urlencode([('rule_name[]', name) for name in required_rules])}"
    )
    evidence_origin = origins["evidence"]
    target: dict[str, Any] = {
        "adapter": native_target.ADAPTER,
        "adapter_contract_sha256": _hash(
            {
                "adapter": native_target.ADAPTER,
                "adapter_source_sha256": current_source_sha256,
                "load_topology_sha256": load_topology_sha256,
                "observability_topology_sha256": (
                    observability_topology_sha256
                ),
            }
        ),
        "schema": native_target.TARGET_SCHEMA,
        "sources": {
            "galera": {
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "galera",
                ),
                "instances": {
                    host: _exposition_endpoint(
                        f"{origins['galera'][host]}/metrics"
                    )
                    for host in inventory["controllers"]
                },
                "kind": "mysqld-exporter",
            },
            "haproxy": {
                "backend_targets": {
                    component: {
                        "proxy": f"coffer-{component}",
                        "servers": component_instances[component],
                    }
                    for component in ("api", "edge", "registry")
                },
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "haproxy",
                ),
                "kind": "haproxy-exporter",
                "metrics": _exposition_endpoint(
                    f"{origins['haproxy']}/metrics"
                ),
            },
            "hosts": {
                "instances": {
                    host: {
                        **_exposition_endpoint(
                            f"{origins['hosts'][host]}/metrics"
                        ),
                        "role": (
                            "controller"
                            if host in inventory["controllers"]
                            else "storage"
                        ),
                    }
                    for host in all_hosts
                },
                "kind": "node-exporter",
            },
            "prometheus": {
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "prometheus",
                ),
                "instances": component_instances,
                "kind": "prometheus-v1",
                "queries": queries,
                "rules": _json_endpoint(rules_url),
            },
            "quota": {
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "quota",
                ),
                "kind": "phase-evidence",
            },
            "reconciliation": {
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "reconciliation",
                ),
                "kind": "phase-evidence",
            },
            "rgw": {
                "daemon_metadata": _exposition_endpoint(
                    f"{origins['ceph_mgr']}/metrics"
                ),
                "daemon_sockets": _exposition_endpoint(
                    f"{origins['ceph_exporter']}/metrics"
                ),
                "daemons": inventory["rgw_daemons"],
                "evidence_urls": _evidence_urls(
                    evidence_origin,
                    "rgw",
                ),
                "ingress": _exposition_endpoint(
                    f"{origins['rgw_ingress']}/metrics"
                ),
                "ingress_target": {
                    "proxy": "rgw-ingress",
                    "servers": inventory["rgw_ingress_hosts"],
                },
                "kind": "ceph-exporters",
            },
        },
        "target_class": native_target.TARGET_CLASS,
        "topology_sha256": load_topology_sha256,
    }
    target["target_sha256"] = native_target._hash(target)
    try:
        validated = native_target.validate_target(
            target,
            topology_sha256=load_topology_sha256,
            load_topology=load_topology,
            observability_topology=observability_topology,
        )
    except native_target.NativeTargetError as error:
        raise RenderError("rendered native target is invalid") from error
    return dict(validated.raw)


def _read_owner_canonical(path: Path) -> object:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RenderError("render request is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or not 1 <= metadata.st_size <= MAX_REQUEST_BYTES
        ):
            raise RenderError("render request file is unsafe")
        payload = os.read(descriptor, MAX_REQUEST_BYTES + 1)
        if len(payload) != metadata.st_size:
            raise RenderError("render request file changed")
    except OSError as error:
        raise RenderError("render request is unavailable") from error
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RenderError("render request is invalid") from error
    if payload != _canonical(value):
        raise RenderError("render request is not canonical")
    return value


def _safe_output(path: Path, *, request_path: Path) -> None:
    try:
        parent_metadata = path.parent.stat(follow_symlinks=False)
    except OSError as error:
        raise RenderError("target output parent is unavailable") from error
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        or parent_metadata.st_uid != os.getuid()
        or path.name in {"", ".", ".."}
    ):
        raise RenderError("target output parent is unsafe")
    try:
        output_metadata = path.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise RenderError("target output is unavailable") from error
    if (
        not stat.S_ISREG(output_metadata.st_mode)
        or stat.S_IMODE(output_metadata.st_mode) != 0o600
        or output_metadata.st_uid != os.getuid()
        or output_metadata.st_nlink != 1
    ):
        raise RenderError("target output is unsafe")
    try:
        request_metadata = request_path.stat(follow_symlinks=False)
    except OSError as error:
        raise RenderError("render request is unavailable") from error
    if (
        output_metadata.st_dev,
        output_metadata.st_ino,
    ) == (
        request_metadata.st_dev,
        request_metadata.st_ino,
    ):
        raise RenderError("render request and target output alias")


def _atomic_write(path: Path, payload: bytes) -> None:
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
    except OSError as error:
        raise RenderError("target output is unavailable") from error
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise RenderError("target output is unavailable") from error


def render_file(request_path: Path, output_path: Path) -> dict[str, Any]:
    if request_path == output_path:
        raise RenderError("render request and target output alias")
    value = _read_owner_canonical(request_path)
    _safe_output(output_path, request_path=request_path)
    target = render_request(value)
    payload = _canonical(target)
    try:
        if output_path.exists() and output_path.read_bytes() == payload:
            return target
    except OSError as error:
        raise RenderError("target output is unavailable") from error
    _atomic_write(output_path, payload)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["source-hash"]:
        try:
            source_sha256 = adapter_source_sha256()
        except RenderError:
            print("target-render-refused", file=sys.stderr)
            return 2
        print(
            _canonical(
                {
                    "adapter_source_sha256": source_sha256,
                    "schema": SOURCE_RESULT_SCHEMA,
                }
            ).decode("utf-8"),
            end="",
        )
        return 0
    if len(arguments) != 2:
        print("target-render-refused", file=sys.stderr)
        return 2
    try:
        target = render_file(Path(arguments[0]), Path(arguments[1]))
    except (
        RenderError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
    ):
        print("target-render-refused", file=sys.stderr)
        return 2
    print(
        _canonical(
            {
                "schema": RESULT_SCHEMA,
                "target_sha256": target["target_sha256"],
            }
        ).decode("utf-8"),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
