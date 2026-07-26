from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPILER_PATH = (
    ROOT
    / "poc"
    / "load-soak"
    / "collector"
    / "phase_evidence.py"
)


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


COMPILER = load_module(
    "coffer_load_phase_evidence_tests",
    COMPILER_PATH,
)
LOAD_TOPOLOGY = COMPILER.load_contract.load_topology(
    ROOT / "poc" / "load-soak" / "topology.json"
)
OBSERVABILITY_TOPOLOGY = COMPILER.observability_contract.load_topology(
    ROOT / "poc" / "observability" / "topology.json"
)
CONTROLLERS = ["controller1", "controller2", "controller3"]
STORAGE = ["storage1", "storage2", "storage3"]
WINDOW_SHA256 = f"sha256:{'7' * 64}"
COLLECTOR_SOURCE_SHA256 = f"sha256:{'8' * 64}"
SOURCE_ARTIFACT_SHA256 = f"sha256:{'9' * 64}"


def canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def payload_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def owner_file(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def target_request() -> dict:
    all_hosts = CONTROLLERS + STORAGE
    renderer = COMPILER.render_target
    return {
        "adapter_source_sha256": renderer.adapter_source_sha256(),
        "inventory": {
            "controllers": list(CONTROLLERS),
            "reconcile_hosts": CONTROLLERS[:2],
            "rgw_daemons": {
                "rgw.coffer.storage1.a": "storage1",
                "rgw.coffer.storage2.b": "storage2",
                "rgw.coffer.storage3.c": "storage3",
            },
            "rgw_ingress_hosts": STORAGE[:2],
            "storage_hosts": list(STORAGE),
        },
        "load_topology_sha256": COMPILER.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "observability_topology_sha256": COMPILER.native_target._hash(
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
        "schema": renderer.REQUEST_SCHEMA,
        "target_class": COMPILER.native_target.TARGET_CLASS,
    }


def target_document() -> dict:
    return COMPILER.render_target.render_request(target_request())


def default_payloads() -> dict[str, dict]:
    return {
        "prometheus": {"secret_leaks": 0},
        "haproxy": {"unexpected_errors": 0},
        "galera": {
            "max_transaction_attempts": 2,
            "unexpected_errors": 0,
        },
        "rgw": {
            "kms_errors": 0,
            "multipart_uploads": 0,
            "unexpected_errors": 0,
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
            "workers_up": 2,
        },
    }


def summary_document(
    surface: str,
    payload: dict,
    *,
    phase: str,
    window_sha256: str = WINDOW_SHA256,
) -> dict:
    summary = {
        "collector_source_sha256": COLLECTOR_SOURCE_SHA256,
        "payload": payload,
        "phase": phase,
        "schema": COMPILER.SUMMARY_SCHEMA,
        "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
        "source_class": COMPILER.SOURCE_CLASSES[surface],
        "surface": surface,
        "window_sha256": window_sha256,
    }
    summary["summary_sha256"] = COMPILER._hash(summary)
    return summary


def request_document(
    target: dict,
    target_payload: bytes,
    *,
    phase: str = "before",
) -> dict:
    payloads = default_payloads()
    return {
        "compiler_source_sha256": COMPILER.compiler_source_sha256(),
        "load_topology_sha256": COMPILER.native_target._hash(
            LOAD_TOPOLOGY
        ),
        "phase": phase,
        "schema": COMPILER.REQUEST_SCHEMA,
        "summaries": {
            surface: summary_document(
                surface,
                payloads[surface],
                phase=phase,
            )
            for surface in COMPILER.SURFACES
        },
        "target_file_sha256": payload_hash(target_payload),
        "target_sha256": target["target_sha256"],
        "window_sha256": WINDOW_SHA256,
    }


def compile_values(phase: str = "before") -> tuple[dict, dict, bytes]:
    target = target_document()
    target_payload = canonical(target)
    request = request_document(target, target_payload, phase=phase)
    return request, target, target_payload


@pytest.mark.parametrize("phase", COMPILER.native_target.PHASES)
def test_compiler_emits_exact_phase_bound_documents(phase: str) -> None:
    request, target, target_payload = compile_values(phase)
    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )

    assert bundle["schema"] == COMPILER.BUNDLE_SCHEMA
    assert bundle["phase"] == phase
    assert bundle["target_sha256"] == target["target_sha256"]
    assert bundle["target_file_sha256"] == payload_hash(target_payload)
    assert bundle["window_sha256"] == WINDOW_SHA256
    assert set(bundle["documents"]) == set(COMPILER.SURFACES)
    for surface, retained in bundle["documents"].items():
        document = retained["document"]
        assert document == {
            "payload": request["summaries"][surface]["payload"],
            "phase": phase,
            "schema": COMPILER.native_target.EVIDENCE_SCHEMA,
            "surface": surface,
        }
        assert retained["document_sha256"] == COMPILER._hash(document)
        assert retained["source_summary_sha256"] == request[
            "summaries"
        ][surface]["summary_sha256"]
        COMPILER.native_target._bounded_auxiliary(document)
    unsigned = {
        key: value
        for key, value in bundle.items()
        if key != "bundle_sha256"
    }
    assert bundle["bundle_sha256"] == COMPILER._hash(unsigned)
    COMPILER.load_contract.validate_retained_evidence(bundle)
    COMPILER.observability_contract.validate_retained_payload(bundle)


def test_file_compiler_is_atomic_owner_only_and_idempotent(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    request, target, target_payload = compile_values()
    request_path = tmp_path / "request.json"
    target_path = tmp_path / "target.json"
    output_path = tmp_path / "evidence.json"
    owner_file(request_path, canonical(request))
    owner_file(target_path, target_payload)

    first = COMPILER.compile_file(request_path, target_path, output_path)
    first_payload = output_path.read_bytes()
    first_mtime = output_path.stat().st_mtime_ns
    second = COMPILER.compile_file(request_path, target_path, output_path)

    assert first == second
    assert first_payload == canonical(first)
    assert output_path.read_bytes() == first_payload
    assert output_path.stat().st_mtime_ns == first_mtime
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


def test_compiled_documents_match_native_evidence_reader() -> None:
    request, target, target_payload = compile_values("during")
    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )

    class EvidenceClient:
        def __init__(self, document: dict):
            self.document = document

        def fetch_json(self, *_args, **_kwargs) -> dict:
            return self.document

    for surface, retained in bundle["documents"].items():
        document = retained["document"]
        accepted = COMPILER.native_target._evidence(
            EvidenceClient(document),
            {"url": "https://unused.stage6.test:9443/evidence"},
            ca_file=Path("/unused"),
            phase="during",
            surface=surface,
            timeout_seconds=1,
        )
        assert accepted == document["payload"]


@pytest.mark.parametrize(
    "mutation",
    (
        "bundle-extra",
        "bundle-hash",
        "compiler-contract",
        "topology",
        "phase",
        "document-missing",
        "document-extra",
        "document-payload",
        "document-hash",
        "summary-hash",
    ),
)
def test_bundle_validator_refuses_retained_evidence_tamper(
    mutation: str,
) -> None:
    request, target, target_payload = compile_values()
    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )
    if mutation == "bundle-extra":
        bundle["raw_logs"] = []
    elif mutation == "bundle-hash":
        bundle["bundle_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "compiler-contract":
        bundle["compiler_contract_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "topology":
        bundle["topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "phase":
        bundle["phase"] = "during"
    elif mutation == "document-missing":
        del bundle["documents"]["haproxy"]
    else:
        retained = bundle["documents"]["prometheus"]
        if mutation == "document-extra":
            retained["document"]["raw_url"] = "https://secret.example"
        elif mutation == "document-payload":
            retained["document"]["payload"]["secret_leaks"] = 1
        elif mutation == "document-hash":
            retained["document_sha256"] = f"sha256:{'0' * 64}"
        else:
            retained["source_summary_sha256"] = "invalid"

    with pytest.raises(COMPILER.PhaseEvidenceError):
        COMPILER.validate_bundle(bundle)


@pytest.mark.parametrize(
    "mutation",
    (
        "request-schema",
        "request-extra",
        "compiler-source",
        "topology-hash",
        "phase",
        "window-hash",
        "target-file-hash",
        "target-hash",
        "summary-missing",
        "summary-schema",
        "summary-phase",
        "summary-window",
        "summary-surface",
        "summary-class",
        "summary-hash",
        "summary-extra",
    ),
)
def test_compiler_refuses_request_and_summary_binding_drift(
    mutation: str,
) -> None:
    request, target, target_payload = compile_values()
    if mutation == "request-schema":
        request["schema"] = "unknown"
    elif mutation == "request-extra":
        request["raw_logs"] = []
    elif mutation == "compiler-source":
        request["compiler_source_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "topology-hash":
        request["load_topology_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "phase":
        request["phase"] = "steady"
    elif mutation == "window-hash":
        request["window_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "target-file-hash":
        request["target_file_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "target-hash":
        request["target_sha256"] = f"sha256:{'0' * 64}"
    elif mutation == "summary-missing":
        del request["summaries"]["haproxy"]
    else:
        summary = request["summaries"]["prometheus"]
        if mutation == "summary-schema":
            summary["schema"] = "unknown"
        elif mutation == "summary-phase":
            summary["phase"] = "during"
        elif mutation == "summary-window":
            summary["window_sha256"] = f"sha256:{'0' * 64}"
        elif mutation == "summary-surface":
            summary["surface"] = "haproxy"
        elif mutation == "summary-class":
            summary["source_class"] = "raw-log"
        elif mutation == "summary-hash":
            summary["summary_sha256"] = f"sha256:{'0' * 64}"
        else:
            summary["raw_url"] = "https://secret.example"

    with pytest.raises(COMPILER.PhaseEvidenceError):
        COMPILER.compile_bundle(
            request,
            target,
            target_file_sha256=payload_hash(target_payload),
        )


@pytest.mark.parametrize(
    ("surface", "field", "value"),
    (
        ("prometheus", "secret_leaks", -1),
        ("prometheus", "secret_leaks", True),
        ("haproxy", "unexpected_errors", 1_000_001),
        ("galera", "max_transaction_attempts", 0),
        ("galera", "max_transaction_attempts", 65),
        ("rgw", "multipart_uploads", -1),
        ("rgw", "kms_errors", "one"),
        ("quota", "headroom_percent", math.nan),
        ("quota", "headroom_percent", 101),
        ("quota", "invariant", 1),
        ("quota", "max_transaction_attempts", 65),
        ("reconciliation", "workers_total", 3),
        ("reconciliation", "workers_up", 3),
        ("reconciliation", "claims_exact", 1),
        ("reconciliation", "last_success_age_seconds", 86_401),
    ),
)
def test_compiler_refuses_unbounded_or_mistyped_aggregates(
    surface: str,
    field: str,
    value: object,
) -> None:
    request, target, target_payload = compile_values()
    summary = request["summaries"][surface]
    summary["payload"][field] = value
    unsigned = {
        key: nested
        for key, nested in summary.items()
        if key != "summary_sha256"
    }
    summary["summary_sha256"] = COMPILER._hash(unsigned)

    with pytest.raises(COMPILER.PhaseEvidenceError):
        COMPILER.compile_bundle(
            request,
            target,
            target_file_sha256=payload_hash(target_payload),
        )


def test_compiler_preserves_bounded_failure_evidence_for_verifier() -> None:
    request, target, target_payload = compile_values("during")
    payloads = {
        "prometheus": {"secret_leaks": 2},
        "haproxy": {"unexpected_errors": 3},
        "galera": {
            "max_transaction_attempts": 4,
            "unexpected_errors": 5,
        },
        "rgw": {
            "kms_errors": 6,
            "multipart_uploads": 7,
            "unexpected_errors": 8,
        },
        "quota": {
            "headroom_percent": 20,
            "invariant": False,
            "limit_usage_percent": 80,
            "max_transaction_attempts": 4,
            "stale_claims": 9,
            "unexpected_errors": 10,
        },
        "reconciliation": {
            "claims_exact": False,
            "fencing_violations": 11,
            "fresh": False,
            "last_success_age_seconds": 120,
            "stale_claims": 12,
            "workers_total": 2,
            "workers_up": 0,
        },
    }
    request["summaries"] = {
        surface: summary_document(
            surface,
            payload,
            phase="during",
        )
        for surface, payload in payloads.items()
    }

    bundle = COMPILER.compile_bundle(
        request,
        target,
        target_file_sha256=payload_hash(target_payload),
    )

    for surface, payload in payloads.items():
        assert bundle["documents"][surface]["document"]["payload"] == payload


@pytest.mark.parametrize(
    "unsafe",
    (
        "request-mode",
        "target-mode",
        "request-noncanonical",
        "target-symlink",
        "input-alias",
        "output-request-alias",
        "output-target-alias",
        "output-mode",
        "parent-mode",
    ),
)
def test_cli_refuses_unsafe_file_boundaries_without_echo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    unsafe: str,
) -> None:
    tmp_path.chmod(0o700)
    request, target, target_payload = compile_values()
    request_path = tmp_path / "request.json"
    target_path = tmp_path / "target.json"
    output_path = tmp_path / "evidence.json"
    owner_file(request_path, canonical(request))
    owner_file(target_path, target_payload)
    if unsafe == "request-mode":
        request_path.chmod(0o640)
    elif unsafe == "target-mode":
        target_path.chmod(0o640)
    elif unsafe == "request-noncanonical":
        owner_file(
            request_path,
            json.dumps(request, indent=2).encode("utf-8"),
        )
    elif unsafe == "target-symlink":
        real_target = tmp_path / "real-target.json"
        target_path.rename(real_target)
        target_path.symlink_to(real_target)
    elif unsafe == "input-alias":
        target_path.unlink()
        target_path.hardlink_to(request_path)
    elif unsafe == "output-request-alias":
        output_path = request_path
    elif unsafe == "output-target-alias":
        output_path = target_path
    elif unsafe == "output-mode":
        output_path.write_bytes(b"existing")
        output_path.chmod(0o640)
    else:
        tmp_path.chmod(0o750)

    assert (
        COMPILER.main(
            [str(request_path), str(target_path), str(output_path)]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "phase-evidence-refused\n"
    if (
        output_path not in {request_path, target_path}
        and unsafe != "output-mode"
    ):
        assert not output_path.exists()


def test_cli_outputs_only_phase_and_hashes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tmp_path.chmod(0o700)
    request, target, target_payload = compile_values()
    request_path = tmp_path / "request.json"
    target_path = tmp_path / "target.json"
    output_path = tmp_path / "evidence.json"
    owner_file(request_path, canonical(request))
    owner_file(target_path, target_payload)

    assert (
        COMPILER.main(
            [str(request_path), str(target_path), str(output_path)]
        )
        == 0
    )
    captured = capsys.readouterr()
    bundle = json.loads(output_path.read_bytes())
    result = json.loads(captured.out)
    assert result == {
        "bundle_sha256": bundle["bundle_sha256"],
        "phase": "before",
        "schema": COMPILER.RESULT_SCHEMA,
    }
    assert captured.out == canonical(result).decode("utf-8")
    assert captured.err == ""
    assert "https://" not in captured.out
    assert "controller" not in captured.out


def test_source_hash_is_machine_readable_and_no_runtime_adapter_exists(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert COMPILER.main(["source-hash"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result == {
        "compiler_source_sha256": COMPILER.compiler_source_sha256(),
        "schema": COMPILER.SOURCE_RESULT_SCHEMA,
    }
    assert captured.out == canonical(result).decode("utf-8")
    source = COMPILER_PATH.read_text(encoding="utf-8")
    assert "\nimport socket" not in source
    assert "\nfrom socket" not in source
    assert "subprocess" not in source
    assert "http.client" not in source
    assert "urllib.request" not in source
    assert "urlopen" not in source
