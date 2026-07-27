from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "ui-images"
TARGET_MANIFEST = HARNESS / "python_targets.json"
MATRIX_MANIFEST = HARNESS / "python_matrices.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("python_target", HARNESS / "python_target.py")
MATRIX_MODULE = load("python_matrix", HARNESS / "python_matrix.py")
load("collect_python_runtime", HARNESS / "collect_python_runtime.py")
RUNTIME_MODULE = load(
    "coffer_ui_python_matrix_runtime",
    HARNESS / "collect_python_matrix_runtime.py",
)
load(
    "collect_python_trial",
    HARNESS / "collect_python_trial.py",
)
COLLECTOR_MODULE = load(
    "collect_python_matrix_trial",
    HARNESS / "collect_python_matrix_trial.py",
)
load("python_trial", HARNESS / "python_trial.py")
CLASSIFIER_MODULE = load(
    "coffer_ui_python_matrix_trial",
    HARNESS / "python_matrix_trial.py",
)


def write_documents(
    tmp_path: Path,
    matrix_document: dict[str, object],
    target_document: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    targets = tmp_path / "python_targets.json"
    targets.write_text(
        json.dumps(
            target_document
            if target_document is not None
            else json.loads(TARGET_MANIFEST.read_text())
        )
    )
    matrix_document["target_manifest_sha256"] = hashlib.sha256(
        targets.read_bytes()
    ).hexdigest()
    matrices = tmp_path / "python_matrices.json"
    matrices.write_text(json.dumps(matrix_document))
    return matrices, targets


def test_checked_in_matrix_is_exact_and_surface_scoped() -> None:
    matrix = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    )

    assert matrix.trial_label == "coffer-ui-python-cumulative-v1"
    assert (
        matrix.target_manifest_sha256
        == hashlib.sha256(TARGET_MANIFEST.read_bytes()).hexdigest()
    )
    assert matrix.target_keys == (
        "click",
        "cryptography-pyopenssl",
        "django",
        "httplib2",
        "lxml",
        "mako",
        "msgpack",
        "pillow",
        "pyjwt",
        "ujson",
        "urllib3",
    )

    horizon = matrix.for_surface("horizon")
    skyline = matrix.for_surface("skyline")
    assert len(horizon.targets) == 11
    assert len(horizon.components) == 12
    assert len(horizon.finding_ids_for("trivy")) == 30
    assert len(horizon.finding_ids_for("scout")) == 31
    assert len(skyline.targets) == 9
    assert len(skyline.components) == 10
    assert len(skyline.finding_ids_for("trivy")) == 15
    assert len(skyline.finding_ids_for("scout")) == 16
    assert "django" not in skyline.target_keys
    assert "pillow" not in skyline.target_keys
    assert horizon.probes[0] == ("click", "click-cli")
    assert ("cryptography-pyopenssl", "pyca-pair") in horizon.probes
    assert len(matrix.components) == 12

    with pytest.raises(
        MATRIX_MODULE.MatrixError,
        match="surface is unsupported",
    ):
        matrix.for_surface("unknown")
    with pytest.raises(
        MATRIX_MODULE.MatrixError,
        match="scanner is unsupported",
    ):
        horizon.finding_ids_for("unknown")


def test_matrix_probe_runs_every_selected_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    ).for_surface("skyline")
    calls: list[tuple[str, bool]] = []

    def probe(target, *, enforce_security: bool):
        calls.append((target.key, enforce_security))
        return target.expected_probe_result

    monkeypatch.setattr(MATRIX_MODULE, "probe_target", probe)
    results = MATRIX_MODULE.probe_surface(surface, enforce_security=False)

    assert tuple(item[0] for item in results) == surface.target_keys
    assert calls == [(key, False) for key in surface.target_keys]


def test_matrix_runtime_collects_exact_surface_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surface = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    ).for_surface("skyline")
    distributions = [
        SimpleNamespace(
            metadata={"Name": component.display_name},
            version=component.to_version,
        )
        for component in surface.components
    ]
    monkeypatch.setattr(
        RUNTIME_MODULE.metadata,
        "distributions",
        lambda: distributions,
    )
    monkeypatch.setattr(
        RUNTIME_MODULE.metadata,
        "version",
        lambda name: next(
            component.to_version
            for component in surface.components
            if component.display_name == name
        ),
    )
    monkeypatch.setattr(
        RUNTIME_MODULE,
        "component_files",
        lambda component: {
            f"{component.package_prefix}fixture.py": component.wheel_sha256
        },
    )
    monkeypatch.setattr(
        RUNTIME_MODULE,
        "probe_surface",
        lambda selected, enforce_security: tuple(
            (target.key, target.probe, target.expected_probe_result)
            for target in selected.targets
        ),
    )
    monkeypatch.setattr(
        RUNTIME_MODULE,
        "pip_check",
        lambda: {
            "clean": True,
            "message": "No broken requirements found.",
        },
    )
    monkeypatch.setattr(RUNTIME_MODULE.platform, "machine", lambda: "aarch64")

    result = RUNTIME_MODULE.collect(surface, probe_mode="candidate")

    assert result["schema"] == "coffer.ui-python-matrix-runtime/v1"
    assert result["architecture"] == "arm64"
    assert result["surface"] == "skyline"
    assert len(result["components"]) == 10
    assert len(result["probes"]) == 9
    assert all(item["mode"] == "candidate" for item in result["probes"])
    assert result["packages"]["cryptography"] == ["49.0.0"]
    assert result["pip_check"]["clean"] is True


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("schema", "schema"),
        ("hash", "hash"),
        ("missing-surface", "value"),
        ("unknown-target", "not exact"),
        ("duplicate-target", "target keys"),
        ("unsorted-targets", "target keys"),
        ("missing-target", "not exact"),
        ("surface-incompatible", "not exact"),
        ("extra-field", "entry"),
        ("invalid-label", "value"),
    ],
)
def test_matrix_rejects_invalid_contract(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    document = json.loads(MATRIX_MANIFEST.read_text())
    entry = document["matrices"]["accepted"]
    surfaces = entry["surfaces"]
    if mutation == "schema":
        document["schema"] = "unsupported"
    elif mutation == "hash":
        document["target_manifest_sha256"] = "0" * 64
    elif mutation == "missing-surface":
        surfaces.pop("skyline")
    elif mutation == "unknown-target":
        surfaces["horizon"].append("unknown")
        surfaces["horizon"].sort()
    elif mutation == "duplicate-target":
        surfaces["horizon"].append("click")
        surfaces["horizon"].sort()
    elif mutation == "unsorted-targets":
        surfaces["horizon"].reverse()
    elif mutation == "missing-target":
        surfaces["horizon"].remove("click")
    elif mutation == "surface-incompatible":
        surfaces["skyline"].append("django")
        surfaces["skyline"].sort()
    elif mutation == "extra-field":
        entry["mutable"] = True
    elif mutation == "invalid-label":
        entry["trial_label"] = "latest"

    if mutation == "hash":
        path = tmp_path / "python_matrices.json"
        path.write_text(json.dumps(document))
        matrix_path, target_path = path, TARGET_MANIFEST
    else:
        matrix_path, target_path = write_documents(tmp_path, document)

    with pytest.raises(MATRIX_MODULE.MatrixError, match=message):
        MATRIX_MODULE.load_matrices(matrix_path, target_path)


def test_matrix_rejects_component_overlap(tmp_path: Path) -> None:
    target_document = json.loads(TARGET_MANIFEST.read_text())
    crypto = target_document["targets"]["cryptography-pyopenssl"]
    duplicate = {key: value for key, value in crypto.items() if key != "companions"}
    duplicate["normalized_name"] = "cryptography"
    duplicate["trial_label"] = "coffer-ui-python-cryptography-copy-v1"
    target_document["targets"]["cryptography"] = duplicate

    document = json.loads(MATRIX_MANIFEST.read_text())
    for surface in ("horizon", "skyline"):
        document["matrices"]["accepted"]["surfaces"][surface].insert(
            1,
            "cryptography",
        )
    matrix_path, target_path = write_documents(
        tmp_path,
        document,
        target_document,
    )

    with pytest.raises(MATRIX_MODULE.MatrixError, match="components overlap"):
        MATRIX_MODULE.load_matrices(matrix_path, target_path)


def test_matrix_refuses_linked_or_unknown_inputs(tmp_path: Path) -> None:
    linked = tmp_path / "python_matrices.json"
    linked.symlink_to(MATRIX_MANIFEST)
    with pytest.raises(MATRIX_MODULE.MatrixError, match="missing or linked"):
        MATRIX_MODULE.load_matrices(linked, TARGET_MANIFEST)
    with pytest.raises(MATRIX_MODULE.MatrixError, match="unsupported"):
        MATRIX_MODULE.load_matrix(
            MATRIX_MANIFEST,
            TARGET_MANIFEST,
            "unknown",
        )


def test_matrix_containerfile_is_offline_and_bounded() -> None:
    containerfile = (HARNESS / "python_matrix.Containerfile").read_text()

    assert "--no-compile" in containerfile
    assert "--no-deps" in containerfile
    assert "--no-index" in containerfile
    assert "--force-reinstall" in containerfile
    assert "/tmp/target-wheels/*.whl" in containerfile
    assert "--probe-mode candidate" in containerfile
    assert "python_matrices.json" in containerfile
    assert "python_targets.json" in containerfile
    assert "rm -rf" in containerfile

    runner = (HARNESS / "trial_python_overlay.sh").read_text()
    makefile = (HARNESS / "Makefile").read_text()
    assert "MATRIX_MODE=false" in runner
    assert 'MATRIX_MANIFEST="${HARNESS}/python_matrices.json"' in runner
    assert 'WORK="${ROOT}/work/ui-python-overlay-trial-${TARGET_KEY}"' in runner
    assert "python-matrix-${target_surface}" in runner
    assert "--matrix-manifest" in runner
    assert "collect_python_matrix_trial.py" in runner
    assert "python_matrix_trial.py" in runner
    assert ".decision.python_matrix_trial_accepted == true" in runner
    assert "./trial_python_overlay.sh --matrix accepted" in makefile


def test_matrix_collector_binds_surface_projections() -> None:
    matrix = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    )

    horizon = COLLECTOR_MODULE.surface_projection(matrix, "horizon")
    skyline = COLLECTOR_MODULE.surface_projection(matrix, "skyline")

    assert len(horizon["target_keys"]) == 11
    assert len(horizon["components"]) == 12
    assert len(horizon["finding_ids_by_scanner"]["trivy"]) == 30
    assert len(skyline["target_keys"]) == 9
    assert len(skyline["components"]) == 10
    assert len(skyline["finding_ids_by_scanner"]["scout"]) == 16
    assert horizon["probes"][1] == {
        "target": "cryptography-pyopenssl",
        "name": "pyca-pair",
    }


def test_matrix_wheel_map_rejects_missing_input(tmp_path: Path) -> None:
    matrix = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    )
    with pytest.raises(
        COLLECTOR_MODULE.CollectionError,
        match="wheel set is invalid",
    ):
        COLLECTOR_MODULE.wheel_map((tmp_path / "missing.whl",), matrix)


def write_trivy(
    path: Path,
    identifiers: list[str],
    surface,
) -> None:
    def component_for(identifier: str):
        return next(
            (
                component
                for component in surface.components
                if identifier in component.finding_ids_for("trivy")
            ),
            None,
        )

    path.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "CreatedAt": "fixture",
                "Results": [
                    {
                        "Class": "lang-pkgs",
                        "Type": "python-pkg",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": identifier,
                                "PkgName": (
                                    component_for(identifier).display_name
                                    if component_for(identifier) is not None
                                    else "remaining"
                                ),
                                "InstalledVersion": (
                                    component_for(identifier).from_version
                                    if component_for(identifier) is not None
                                    else "1"
                                ),
                                "FixedVersion": (
                                    component_for(identifier).to_version
                                    if component_for(identifier) is not None
                                    else ""
                                ),
                                "Severity": "HIGH",
                            }
                            for identifier in identifiers
                        ],
                    }
                ],
            }
        )
    )


def write_scout(
    path: Path,
    identifiers: list[str],
    surface,
) -> None:
    def component_for(identifier: str):
        return next(
            (
                component
                for component in surface.components
                if identifier in component.finding_ids_for("scout")
            ),
            None,
        )

    path.write_text(
        json.dumps(
            {
                "version": "2.1.0",
                "runs": [
                    {
                        "tool": {
                            "driver": {
                                "name": "docker scout",
                                "version": "fixture",
                                "rules": [
                                    {
                                        "id": identifier,
                                        "properties": {
                                            "cvssV3_severity": "HIGH",
                                            "purls": [
                                                (
                                                    "pkg:pypi/"
                                                    f"{component_for(identifier).normalized_name}"
                                                    "@"
                                                    f"{component_for(identifier).from_version}"
                                                    if component_for(identifier)
                                                    is not None
                                                    else "pkg:pypi/remaining@1"
                                                )
                                            ],
                                            "affected_version": "1",
                                            "fixed_version": (
                                                component_for(identifier).to_version
                                                if component_for(identifier) is not None
                                                else "not fixed"
                                            ),
                                        },
                                    }
                                    for identifier in identifiers
                                ],
                            }
                        }
                    }
                ],
            }
        )
    )


@pytest.mark.parametrize("scanner", ["trivy", "scout"])
def test_matrix_scanner_result_requires_exact_aggregate_delta(
    tmp_path: Path,
    scanner: str,
) -> None:
    surface = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    ).for_surface("skyline")
    expected = list(surface.finding_ids_for(scanner))
    remaining = "CVE-2099-9999"
    suffix = "trivy.json" if scanner == "trivy" else "scout.sarif.json"
    writer = write_trivy if scanner == "trivy" else write_scout
    writer(tmp_path / f"skyline-before.{suffix}", [*expected, remaining], surface)
    writer(tmp_path / f"skyline-after.{suffix}", [remaining], surface)

    result = CLASSIFIER_MODULE.scanner_result(tmp_path, surface, scanner)

    assert result["removed_finding_ids"] == expected
    assert result["removed_critical_high"] == len(expected)
    assert result["introduced_critical_high"] == 0


def test_matrix_scanner_result_rejects_missing_delta(tmp_path: Path) -> None:
    surface = MATRIX_MODULE.load_matrix(
        MATRIX_MANIFEST,
        TARGET_MANIFEST,
        "accepted",
    ).for_surface("skyline")
    expected = list(surface.finding_ids_for("trivy"))
    write_trivy(
        tmp_path / "skyline-before.trivy.json",
        expected,
        surface,
    )
    write_trivy(
        tmp_path / "skyline-after.trivy.json",
        [expected[-1]],
        surface,
    )

    with pytest.raises(
        CLASSIFIER_MODULE.common.EvidenceError,
        match="finding delta is invalid",
    ):
        CLASSIFIER_MODULE.scanner_result(tmp_path, surface, "trivy")


def test_matrix_package_inventory_requires_matrix_schema() -> None:
    document = {
        "schema": "coffer.ui-python-matrix-runtime/v1",
        "packages": {
            "click": ["8.3.3"],
            "cryptography": ["49.0.0"],
        },
    }

    assert CLASSIFIER_MODULE._python_packages(document, "fixture") == {
        "click": ["8.3.3"],
        "cryptography": ["49.0.0"],
    }
    document["schema"] = "coffer.ui-python-overlay-runtime/v3"
    with pytest.raises(
        CLASSIFIER_MODULE.common.EvidenceError,
        match="matrix Python runtime schema",
    ):
        CLASSIFIER_MODULE._python_packages(document, "fixture")
