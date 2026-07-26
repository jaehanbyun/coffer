from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

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
