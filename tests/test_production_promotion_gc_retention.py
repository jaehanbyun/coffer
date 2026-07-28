from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "gc_retention.py"
MAINTENANCE_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_maintenance_identity.py"
)
GC_TEST_SOURCE = ROOT / "tests" / "test_gc_filesystem_result.py"


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


production_gc = _load(
    "coffer_test_production_promotion_gc_retention",
    SOURCE,
)
maintenance_test = _load(
    "coffer_production_gc_maintenance_test_helpers",
    MAINTENANCE_TEST_SOURCE,
)
gc_test = _load(
    "coffer_production_gc_filesystem_test_helpers",
    GC_TEST_SOURCE,
)

RELEASE_DIGEST = f"sha256:{'1' * 64}"
ARTIFACT_DIGEST = f"sha256:{'2' * 64}"
GC_DIGEST = f"sha256:{'3' * 64}"


def release(qualified: bool = True) -> dict[str, object]:
    result = maintenance_test.release(qualified)
    result["components"]["distribution"].update(
        {
            "revision": production_gc.GC_RESULT.REVISION,
            "version": production_gc.GC_RESULT.VERSION,
        }
    )
    return result


def gc_result() -> dict[str, object]:
    candidate = gc_test.result.compile_candidate(**gc_test.inputs())
    return gc_test.result.finalize_candidate(candidate)


def compile_inputs() -> dict[str, object]:
    return {
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_result": maintenance_test.artifact_result(RELEASE_DIGEST),
        "gc_digest": GC_DIGEST,
        "gc_result": gc_result(),
        "release_digest": RELEASE_DIGEST,
        "release_readiness": release(),
    }


def _write_private(path: Path, value: object) -> bytes:
    payload = (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(payload)
    path.chmod(0o600)
    return payload


def test_compiles_exact_release_bound_gc_result() -> None:
    result = production_gc.compile_result(**compile_inputs())

    assert result["schema"] == production_gc.SCHEMA
    assert result["production_candidate"] is True
    assert result["distribution"]["version"] == "v3.1.1"
    assert result["prerequisites"] == {
        "artifact_result_sha256": ARTIFACT_DIGEST,
        "release_readiness_sha256": RELEASE_DIGEST,
    }
    assert production_gc.validate_final_result(result) == result


def test_blocked_or_different_release_cannot_reuse_gc_result() -> None:
    blocked = compile_inputs()
    blocked["release_readiness"] = release(False)
    with pytest.raises(
        production_gc.ProductionGCInputsBlocked,
        match="not candidate-qualified",
    ):
        production_gc.compile_result(**blocked)

    future = compile_inputs()
    future["release_readiness"]["components"]["distribution"].update(
        {"revision": "f" * 40, "version": "v3.2.0"}
    )
    with pytest.raises(
        production_gc.ProductionGCInputsBlocked,
        match="does not match",
    ):
        production_gc.compile_result(**future)


def test_artifact_and_raw_gc_tamper_fail_closed() -> None:
    changed_artifact = compile_inputs()
    changed_artifact["artifact_result"]["source"][
        "core_verifier_sha256"
    ] = f"sha256:{'0' * 64}"
    with pytest.raises(
        production_gc.ProductionGCInputsBlocked,
        match="artifacts",
    ):
        production_gc.compile_result(**changed_artifact)

    changed_gc = compile_inputs()
    changed_gc["gc_result"]["residue"]["containers"] = 1
    with pytest.raises(
        production_gc.ProductionGCResultError,
        match="filesystem GC",
    ):
        production_gc.compile_result(**changed_gc)


def test_cli_blocks_before_missing_artifact_or_gc_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(release_path, release(False))

    result = production_gc.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--gc-result",
            str(directory / "missing-gc.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_cli_writes_owner_only_result(tmp_path: Path) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    artifact_path = directory / "artifact.json"
    gc_path = directory / "gc.json"
    output = directory / "result.json"

    release_payload = _write_private(release_path, release())
    release_digest = production_gc._sha256_bytes(release_payload)
    _write_private(
        artifact_path,
        maintenance_test.artifact_result(release_digest),
    )
    _write_private(gc_path, gc_result())

    result = production_gc.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(artifact_path),
            "--gc-result",
            str(gc_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert production_gc.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True


def test_final_result_source_prerequisite_and_residue_tamper_fail() -> None:
    result = production_gc.compile_result(**compile_inputs())

    changed_source = deepcopy(result)
    changed_source["source"]["gc_result_verifier_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        production_gc.ProductionGCResultError,
        match="not qualified",
    ):
        production_gc.validate_final_result(changed_source)

    changed_prerequisite = deepcopy(result)
    changed_prerequisite["prerequisites"]["release_readiness_sha256"] = (
        "invalid"
    )
    with pytest.raises(
        production_gc.ProductionGCResultError,
        match="invalid",
    ):
        production_gc.validate_final_result(changed_prerequisite)

    changed_residue = deepcopy(result)
    changed_residue["residue"]["containers"] = 1
    changed_residue["residue"]["total"] = 1
    with pytest.raises(
        production_gc.ProductionGCResultError,
        match="not qualified",
    ):
        production_gc.validate_final_result(changed_residue)
