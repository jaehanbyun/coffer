from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDER_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "render_target.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


RENDER = load_module(
    "coffer_load_native_target_renderer_tests",
    RENDER_PATH,
)
LOAD_TOPOLOGY = RENDER.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = RENDER.observability_contract.load_topology(
    ROOT / "poc" / "observability" / "topology.json"
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
DAEMONS = {
    "rgw.coffer.storage1.a": "storage1",
    "rgw.coffer.storage2.b": "storage2",
    "rgw.coffer.storage3.c": "storage3",
}


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def request_document() -> dict:
    all_hosts = CONTROLLERS + STORAGE
    return {
        "adapter_source_sha256": RENDER.adapter_source_sha256(),
        "inventory": {
            "controllers": list(CONTROLLERS),
            "reconcile_hosts": CONTROLLERS[:2],
            "rgw_daemons": dict(DAEMONS),
            "rgw_ingress_hosts": STORAGE[:2],
            "storage_hosts": list(STORAGE),
        },
        "load_topology_sha256": RENDER.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": RENDER.native_target._hash(
            OBSERVABILITY_TOPOLOGY.raw
        ),
        "origins": {
            "ceph_exporter": "https://ceph-exporter.stage6.test:9926",
            "ceph_mgr": "https://ceph-mgr.stage6.test:9283",
            "evidence": "https://telemetry-adapter.stage6.test:9443",
            "galera": {
                host: f"https://{host}.stage6.test:9104"
                for host in CONTROLLERS
            },
            "haproxy": "https://haproxy.stage6.test:8405",
            "hosts": {
                host: f"https://{host}.stage6.test:9100"
                for host in all_hosts
            },
            "prometheus": "https://prometheus.stage6.test:9091",
            "rgw_ingress": "https://rgw-ingress.stage6.test:8406",
        },
        "schema": RENDER.REQUEST_SCHEMA,
        "target_class": RENDER.native_target.TARGET_CLASS,
    }


def test_renderer_emits_deterministic_owner_only_native_target(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    request = request_document()
    request_path = tmp_path / "render-request.json"
    output_path = tmp_path / "native-target.json"
    owner_file(request_path, canonical(request))

    first = RENDER.render_file(request_path, output_path)
    first_payload = output_path.read_bytes()
    first_mtime = output_path.stat().st_mtime_ns
    second = RENDER.render_file(request_path, output_path)

    assert first == second
    assert first_payload == canonical(first)
    assert output_path.read_bytes() == first_payload
    assert output_path.stat().st_mtime_ns == first_mtime
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    validated = RENDER.native_target.validate_target(
        first,
        topology_sha256=request["load_topology_sha256"],
        load_topology=LOAD_TOPOLOGY,
        observability_topology=OBSERVABILITY_TOPOLOGY,
    )
    assert validated.raw == first
    expected_adapter_contract = RENDER._hash(
        {
            "adapter": RENDER.native_target.ADAPTER,
            "adapter_source_sha256": request[
                "adapter_source_sha256"
            ],
            "load_topology_sha256": request[
                "load_topology_sha256"
            ],
            "observability_topology_sha256": request[
                "observability_topology_sha256"
            ],
        }
    )
    assert first["adapter_contract_sha256"] == expected_adapter_contract
    assert first["target_sha256"] == RENDER.native_target._hash(
        {
            key: value
            for key, value in first.items()
            if key != "target_sha256"
        }
    )


def test_renderer_maps_exact_inventory_and_fixed_routes() -> None:
    target = RENDER.render_request(request_document())
    sources = target["sources"]

    assert sources["prometheus"]["instances"] == {
        "api": CONTROLLERS,
        "edge": CONTROLLERS,
        "reconcile": CONTROLLERS[:2],
        "registry": CONTROLLERS,
    }
    assert sources["haproxy"]["backend_targets"]["registry"] == {
        "proxy": "coffer-registry",
        "servers": CONTROLLERS,
    }
    assert sources["rgw"]["daemons"] == DAEMONS
    assert sources["rgw"]["ingress_target"] == {
        "proxy": "rgw-ingress",
        "servers": STORAGE[:2],
    }
    assert set(sources["hosts"]["instances"]) == set(
        CONTROLLERS + STORAGE
    )
    assert (
        sources["prometheus"]["queries"]["direct_targets"]["url"]
        .split("?", 1)[0]
        .endswith("/api/v1/query")
    )
    assert (
        sources["prometheus"]["rules"]["url"]
        .split("?", 1)[0]
        .endswith("/api/v1/rules")
    )
    for surface in RENDER.native_target.SURFACES:
        if surface == "hosts":
            continue
        evidence_urls = sources[surface].get("evidence_urls")
        if evidence_urls is None:
            continue
        assert set(evidence_urls) == set(RENDER.native_target.PHASES)
        for phase, endpoint in evidence_urls.items():
            assert endpoint["url"].endswith(
                f"/v1/evidence/{surface}/{phase}"
            )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra-field",
        "source-hash",
        "load-topology-hash",
        "observability-topology-hash",
        "target-class",
        "controller-order",
        "reconcile-subset",
        "role-overlap",
        "daemon-placement",
        "origin-http",
        "origin-no-port",
        "origin-credential",
        "origin-path",
        "origin-uppercase",
        "missing-host-origin",
        "duplicate-metrics-url",
    ),
)
def test_renderer_refuses_binding_inventory_and_origin_drift(
    mutation: str,
) -> None:
    request = request_document()
    if mutation == "extra-field":
        request["unexpected"] = True
    elif mutation == "source-hash":
        request["adapter_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "load-topology-hash":
        request["load_topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "observability-topology-hash":
        request["observability_topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "target-class":
        request["target_class"] = "production"
    elif mutation == "controller-order":
        request["inventory"]["controllers"] = list(reversed(CONTROLLERS))
    elif mutation == "reconcile-subset":
        request["inventory"]["reconcile_hosts"] = [
            "controller1",
            "storage1",
        ]
    elif mutation == "role-overlap":
        request["inventory"]["storage_hosts"][-1] = "controller3"
    elif mutation == "daemon-placement":
        request["inventory"]["rgw_daemons"][
            "rgw.coffer.storage3.c"
        ] = "storage2"
    elif mutation == "origin-http":
        request["origins"]["prometheus"] = (
            "http://prometheus.stage6.test:9091"
        )
    elif mutation == "origin-no-port":
        request["origins"]["prometheus"] = (
            "https://prometheus.stage6.test"
        )
    elif mutation == "origin-credential":
        request["origins"]["prometheus"] = (
            "https://user:password@prometheus.stage6.test:9091"
        )
    elif mutation == "origin-path":
        request["origins"]["prometheus"] = (
            "https://prometheus.stage6.test:9091/prometheus"
        )
    elif mutation == "origin-uppercase":
        request["origins"]["prometheus"] = (
            "https://Prometheus.stage6.test:9091"
        )
    elif mutation == "missing-host-origin":
        del request["origins"]["hosts"]["storage3"]
    else:
        request["origins"]["ceph_exporter"] = request["origins"][
            "ceph_mgr"
        ]

    with pytest.raises(RENDER.RenderError):
        RENDER.render_request(request)


@pytest.mark.parametrize(
    "unsafe",
    (
        "request-mode",
        "request-noncanonical",
        "request-symlink",
        "output-parent-mode",
        "output-mode",
        "path-alias",
    ),
)
def test_file_boundary_refuses_unsafe_inputs_without_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    unsafe: str,
) -> None:
    tmp_path.chmod(0o700)
    request = request_document()
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "target.json"
    owner_file(request_path, canonical(request))
    if unsafe == "request-mode":
        request_path.chmod(0o640)
    elif unsafe == "request-noncanonical":
        owner_file(
            request_path,
            json.dumps(request, indent=2).encode("utf-8"),
        )
    elif unsafe == "request-symlink":
        real_path = tmp_path / "real-request.json"
        request_path.rename(real_path)
        request_path.symlink_to(real_path)
    elif unsafe == "output-parent-mode":
        tmp_path.chmod(0o750)
    elif unsafe == "output-mode":
        output_path.write_bytes(b"existing")
        output_path.chmod(0o640)
    else:
        output_path = request_path

    assert RENDER.main([str(request_path), str(output_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "target-render-refused\n"
    if output_path != request_path and unsafe != "output-mode":
        assert not output_path.exists()


def test_cli_emits_only_result_schema_and_target_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tmp_path.chmod(0o700)
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "target.json"
    owner_file(request_path, canonical(request_document()))

    assert RENDER.main([str(request_path), str(output_path)]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    target = json.loads(output_path.read_bytes())
    assert result == {
        "schema": RENDER.RESULT_SCHEMA,
        "target_sha256": target["target_sha256"],
    }
    assert captured.out == canonical(result).decode("utf-8")
    assert captured.err == ""
    assert "https://" not in captured.out
    assert "controller" not in captured.out


def test_cli_exposes_machine_readable_adapter_source_hash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert RENDER.main(["source-hash"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result == {
        "adapter_source_sha256": RENDER.adapter_source_sha256(),
        "schema": RENDER.SOURCE_RESULT_SCHEMA,
    }
    assert captured.out == canonical(result).decode("utf-8")
    assert captured.err == ""


def test_adapter_source_hash_binds_all_renderer_contract_sources() -> None:
    entries = []
    for path in RENDER.SOURCE_FILES:
        entries.append(
            {
                "path": path.name,
                "sha256": digest(path.read_bytes()),
            }
        )
    assert RENDER.adapter_source_sha256() == RENDER._hash(
        {"files": entries}
    )
    source = RENDER_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "http.client" not in source
    assert "urllib.request" not in source
    assert "\nimport socket" not in source
    assert "\nfrom socket" not in source
    assert "requests" not in source
    assert "urlopen" not in source
