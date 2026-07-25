from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "poc" / "load-soak" / "telemetry.py"
LOAD_TOPOLOGY_PATH = ROOT / "poc" / "load-soak" / "topology.json"
OBSERVABILITY_TOPOLOGY_PATH = (
    ROOT / "poc" / "observability" / "topology.json"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TELEMETRY = load_module("coffer_load_soak_telemetry_tests", MODULE_PATH)
LOAD_TOPOLOGY = TELEMETRY.load_contract.load_topology(LOAD_TOPOLOGY_PATH)
OBSERVABILITY_TOPOLOGY = TELEMETRY.observability_contract.load_topology(
    OBSERVABILITY_TOPOLOGY_PATH
)


def direct_targets(
    phase: str,
    observed_at: int,
) -> dict[str, list[dict]]:
    result = {}
    for component in TELEMETRY.DIRECT_COMPONENTS:
        count = LOAD_TOPOLOGY["replicas"][component]
        entries = []
        for index in range(count):
            restarted = (
                phase == "after" and component == "edge" and index == 0
            )
            entries.append(
                {
                    "counter": 1 if restarted else {
                        "before": 10,
                        "during": 20,
                        "after": 30,
                    }[phase],
                    "instance": f"{component}{index + 1}",
                    "process_start_seconds": 800 if restarted else 100,
                    "up": 0 if phase == "during" and index == 0 else 1,
                }
            )
        result[component] = entries
    return result


def hosts() -> list[dict]:
    return [
        {
            "clock_offset_milliseconds": index - 3,
            "cpu_usage_percent": 50,
            "disk_usage_percent": 55,
            "file_descriptor_usage_percent": 40,
            "instance": (
                f"controller{index + 1}"
                if index < 3
                else f"storage{index - 2}"
            ),
            "memory_usage_percent": 60,
            "oom_kills": 0,
            "role": "controller" if index < 3 else "storage",
        }
        for index in range(6)
    ]


def snapshot(phase: str, observed_at: int) -> dict:
    during = phase == "during"
    return {
        "galera": {
            "max_transaction_attempts": 2,
            "nodes_primary": 2 if during else 3,
            "nodes_ready": 2 if during else 3,
            "nodes_synced": 2 if during else 3,
            "nodes_total": 3,
            "unexpected_errors": 0,
        },
        "haproxy": {
            "backends": {
                component: {
                    "healthy": (
                        LOAD_TOPOLOGY["replicas"][component] - 1
                        if during
                        else LOAD_TOPOLOGY["replicas"][component]
                    ),
                    "total": LOAD_TOPOLOGY["replicas"][component],
                }
                for component in ("api", "edge", "registry")
            },
            "unexpected_errors": 0,
        },
        "hosts": hosts(),
        "observed_at_seconds": observed_at,
        "phase": phase,
        "prometheus": {
            "alerts_loaded": list(LOAD_TOPOLOGY["required_alerts"]),
            "direct_targets": direct_targets(phase, observed_at),
            "firing_alerts": ["CofferTargetDown"] if during else [],
            "recording_rules_loaded": list(
                LOAD_TOPOLOGY["required_recording_rules"]
            ),
            "schema_mismatches": 0,
            "scrape_interval_seconds": 30,
            "secret_leaks": 0,
            "stale_series": 1 if during else 0,
        },
        "quota": {
            "headroom_percent": 40,
            "invariant": True,
            "limit_usage_percent": 60,
            "max_transaction_attempts": 2,
            "stale_claims": 0,
            "unexpected_errors": 0,
        },
        "reconciliation": {
            "claims_exact": True,
            "fencing_violations": 0,
            "fresh": True,
            "last_success_age_seconds": 30,
            "stale_claims": 0,
            "workers_total": 2,
            "workers_up": 1 if during else 2,
        },
        "rgw": {
            "daemons_total": 3,
            "daemons_up": 2 if during else 3,
            "ingress_total": 2,
            "ingress_up": 1 if during else 2,
            "kms_errors": 0,
            "multipart_uploads": 2 if during else 0,
            "unexpected_errors": 0,
        },
    }


def bundle(*, synthetic: bool = True) -> dict:
    return {
        "load_topology_sha256": TELEMETRY._hash(LOAD_TOPOLOGY),
        "observability_topology_sha256": OBSERVABILITY_TOPOLOGY.digest,
        "schema": "coffer.load-telemetry-bundle/v1",
        "snapshots": [
            snapshot("before", 500),
            snapshot("during", 700),
            snapshot("after", 1000),
        ],
        "source": "fixture" if synthetic else "prometheus-export",
        "synthetic": synthetic,
    }


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def test_exact_windows_produce_load_metrics_phase_without_raw_identities() -> None:
    result = TELEMETRY.verify_document(
        bundle(),
        load_topology=LOAD_TOPOLOGY,
        observability_topology=OBSERVABILITY_TOPOLOGY,
    )

    assert result["schema"] == "coffer.load-telemetry-verified/v1"
    assert result["synthetic"] is True
    assert result["source"] == "fixture"
    assert result["snapshot_count"] == 3
    assert result["restart_count"] == 1
    assert result["metrics_phase"] == {
        "alerts": LOAD_TOPOLOGY["required_alerts"],
        "direct_targets": {
            component: LOAD_TOPOLOGY["replicas"][component]
            for component in TELEMETRY.DIRECT_COMPONENTS
        },
        "recording_rules": LOAD_TOPOLOGY["required_recording_rules"],
        "restart_resets": True,
        "schema_mismatches": 0,
        "secret_leaks": 0,
        "stale_series": True,
    }
    serialized = json.dumps(result, sort_keys=True)
    for identity in (
        "api1",
        "edge1",
        "registry1",
        "controller1",
        "storage1",
    ):
        assert identity not in serialized


def test_non_synthetic_export_is_refused_before_live_collector_exists() -> None:
    with pytest.raises(TELEMETRY.TelemetryError):
        TELEMETRY.verify_document(
            bundle(synthetic=False),
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "binding",
        "window-order",
        "missing-target",
        "target-down",
        "counter-reset",
        "restart-missing",
        "rules",
        "alert-transition",
        "stale-transition",
        "galera",
        "galera-over",
        "rgw",
        "rgw-over",
        "quota",
        "reconciliation",
        "reconciliation-over",
        "haproxy",
        "haproxy-over",
        "host-usage",
        "host-role",
        "nonstring-alert",
        "source",
        "unknown-field",
    ],
)
def test_telemetry_drift_fails_closed(mutation: str) -> None:
    value = bundle()
    if mutation == "binding":
        value["load_topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "window-order":
        value["snapshots"][1]["observed_at_seconds"] = 400
    elif mutation == "missing-target":
        value["snapshots"][1]["prometheus"]["direct_targets"]["api"].pop()
    elif mutation == "target-down":
        value["snapshots"][1]["prometheus"]["direct_targets"]["api"][1]["up"] = 0
    elif mutation == "counter-reset":
        value["snapshots"][1]["prometheus"]["direct_targets"]["edge"][1][
            "counter"
        ] = 1
    elif mutation == "restart-missing":
        value["snapshots"][2]["prometheus"]["direct_targets"]["edge"][0][
            "process_start_seconds"
        ] = 100
        value["snapshots"][2]["prometheus"]["direct_targets"]["edge"][0][
            "counter"
        ] = 30
    elif mutation == "rules":
        value["snapshots"][0]["prometheus"]["recording_rules_loaded"].pop()
    elif mutation == "alert-transition":
        value["snapshots"][2]["prometheus"]["firing_alerts"] = [
            "CofferTargetDown"
        ]
    elif mutation == "stale-transition":
        value["snapshots"][1]["prometheus"]["stale_series"] = 0
    elif mutation == "galera":
        value["snapshots"][2]["galera"]["nodes_ready"] = 2
    elif mutation == "galera-over":
        value["snapshots"][1]["galera"]["nodes_ready"] = 4
    elif mutation == "rgw":
        value["snapshots"][2]["rgw"]["multipart_uploads"] = 1
    elif mutation == "rgw-over":
        value["snapshots"][1]["rgw"]["daemons_up"] = 4
    elif mutation == "quota":
        value["snapshots"][1]["quota"]["headroom_percent"] = 20
    elif mutation == "reconciliation":
        value["snapshots"][1]["reconciliation"]["fencing_violations"] = 1
    elif mutation == "reconciliation-over":
        value["snapshots"][1]["reconciliation"]["workers_up"] = 3
    elif mutation == "haproxy":
        value["snapshots"][0]["haproxy"]["backends"]["api"]["healthy"] = 2
    elif mutation == "haproxy-over":
        value["snapshots"][1]["haproxy"]["backends"]["api"]["healthy"] = 4
    elif mutation == "host-usage":
        value["snapshots"][1]["hosts"][0]["memory_usage_percent"] = 71
    elif mutation == "host-role":
        value["snapshots"][1]["hosts"][0]["role"] = "client"
    elif mutation == "nonstring-alert":
        value["snapshots"][1]["prometheus"]["firing_alerts"] = [{}]
    elif mutation == "source":
        value["source"] = "prometheus-export"
    else:
        value["snapshots"][0]["quota"]["project_id"] = "forbidden"

    with pytest.raises(TELEMETRY.TelemetryError):
        TELEMETRY.verify_document(
            value,
            load_topology=LOAD_TOPOLOGY,
            observability_topology=OBSERVABILITY_TOPOLOGY,
        )


def test_owner_only_cli_emits_canonical_mode_0600_result(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.json"
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output_path = output_root / "verified.json"
    owner_file(input_path, canonical(bundle()))
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = TELEMETRY.run(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--load-topology",
            str(LOAD_TOPOLOGY_PATH),
            "--observability-topology",
            str(OBSERVABILITY_TOPOLOGY_PATH),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 0, stderr.getvalue()
    assert stdout.getvalue() == "load telemetry verified\n"
    assert stderr.getvalue() == ""
    document = json.loads(output_path.read_bytes())
    assert output_path.read_bytes() == canonical(document)
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    assert not any(path.name.startswith(".verified.json.") for path in output_root.iterdir())


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        ("mode", "local-file-unavailable"),
        ("noncanonical", "contract-refused"),
        ("symlink-output", "output-unavailable"),
        ("alias", "contract-refused"),
    ],
)
def test_cli_file_boundary_fails_without_output(
    tmp_path: Path,
    mutation: str,
    failure: str,
) -> None:
    input_path = tmp_path / "input.json"
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    output_path = output_root / "verified.json"
    owner_file(input_path, canonical(bundle()))
    if mutation == "mode":
        input_path.chmod(0o640)
    elif mutation == "noncanonical":
        owner_file(input_path, json.dumps(bundle(), indent=2).encode("utf-8"))
    elif mutation == "symlink-output":
        target = output_root / "target"
        owner_file(target, b"preserved\n")
        output_path.symlink_to(target)
    else:
        output_path = input_path

    stderr = io.StringIO()
    status = TELEMETRY.run(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--load-topology",
            str(LOAD_TOPOLOGY_PATH),
            "--observability-topology",
            str(OBSERVABILITY_TOPOLOGY_PATH),
        ],
        stdout=io.StringIO(),
        stderr=stderr,
    )

    assert status == 1
    assert stderr.getvalue() == f"load telemetry failed: {failure}\n"
    if mutation not in ("symlink-output", "alias"):
        assert not output_path.exists()


def test_cli_arguments_are_fixed() -> None:
    stderr = io.StringIO()
    assert TELEMETRY.run([], stdout=io.StringIO(), stderr=stderr) == 2
    assert stderr.getvalue() == "load telemetry failed: invalid-arguments\n"


def test_bundle_hash_is_canonical_and_bound() -> None:
    value = bundle()
    result = TELEMETRY.verify_document(
        value,
        load_topology=LOAD_TOPOLOGY,
        observability_topology=OBSERVABILITY_TOPOLOGY,
    )
    assert result["bundle_sha256"] == (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )


def test_adapter_has_no_network_or_subprocess_runtime_import() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import http",
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
    ):
        assert forbidden not in source
