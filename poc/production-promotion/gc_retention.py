from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
RGW_KMS_RESULT_SOURCE = DIRECTORY / "rgw_kms.py"
ARTIFACT_RESULT_SOURCE = DIRECTORY / "artifacts.py"
GC_RESULT_SOURCE = (
    ROOT / "poc" / "gc-retention" / "filesystem" / "result.py"
)

SCHEMA = "coffer.production-promotion-gc-retention-result/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProductionGCResultError(RuntimeError):
    pass


class ProductionGCInputsBlocked(ProductionGCResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ProductionGCResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ProductionGCResultError(f"unable to load {path}") from error
    return module


RGW_KMS_RESULT = _load_module(
    "coffer_production_gc_rgw_kms",
    RGW_KMS_RESULT_SOURCE,
)
ARTIFACT_RESULT = _load_module(
    "coffer_production_gc_artifact",
    ARTIFACT_RESULT_SOURCE,
)
GC_RESULT = _load_module(
    "coffer_production_gc_filesystem_result",
    GC_RESULT_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ProductionGCResultError(f"unable to hash {path}") from error


def source_hashes() -> dict[str, str]:
    return {
        "artifact_result_verifier_sha256": _sha256(
            ARTIFACT_RESULT_SOURCE
        ),
        "gc_result_verifier_sha256": _sha256(GC_RESULT_SOURCE),
        "production_gc_compiler_sha256": _sha256(
            Path(__file__).resolve()
        ),
        "release_verifier_sha256": _sha256(RGW_KMS_RESULT_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionGCResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ProductionGCResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ProductionGCResultError(f"{label} is invalid")
    return value


def _qualified_prerequisites(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    try:
        release = RGW_KMS_RESULT.require_release_qualified(
            release_readiness
        )
        artifact = ARTIFACT_RESULT.validate_final_result(artifact_result)
    except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
        raise ProductionGCInputsBlocked(str(error)) from error
    except ARTIFACT_RESULT.ArtifactResultError as error:
        raise ProductionGCInputsBlocked(
            "immutable artifacts are not candidate-qualified"
        ) from error
    if artifact["release_readiness_sha256"] != release_digest:
        raise ProductionGCInputsBlocked(
            "artifact release prerequisite binding changed"
        )
    return (
        {
            "artifact_result_sha256": _digest(
                artifact_digest,
                "artifact result",
            ),
            "release_readiness_sha256": _digest(
                release_digest,
                "release readiness",
            ),
        },
        release,
    )


def _qualified_gc(
    value: object,
    *,
    release: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        result = GC_RESULT.validate_final_result(value)
    except GC_RESULT.GCResultError as error:
        raise ProductionGCResultError(
            "filesystem GC specialist result is invalid"
        ) from error
    components = _mapping(
        release["components"],
        "release readiness components",
    )
    distribution = _mapping(
        components["distribution"],
        "release readiness Distribution",
    )
    if result["distribution"] != {
        "image": GC_RESULT.IMAGE,
        "revision": distribution["revision"],
        "version": distribution["version"],
    }:
        raise ProductionGCInputsBlocked(
            "filesystem GC result does not match the qualified "
            "Distribution release"
        )
    return result


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    gc_result: object,
    gc_digest: str,
) -> dict[str, Any]:
    prerequisites, release = _qualified_prerequisites(
        release_readiness=release_readiness,
        release_digest=release_digest,
        artifact_result=artifact_result,
        artifact_digest=artifact_digest,
    )
    qualified = _qualified_gc(gc_result, release=release)
    return {
        "authorization_consumed": qualified["authorization_consumed"],
        "candidate_count": qualified["candidate_count"],
        "candidate_set_hash": qualified["candidate_set_hash"],
        "cleanup_verified": qualified["cleanup_verified"],
        "delete_untagged": qualified["delete_untagged"],
        "distribution": dict(qualified["distribution"]),
        "dry_run_count": qualified["dry_run_count"],
        "input_gc_result_sha256": _digest(
            gc_digest,
            "filesystem GC result",
        ),
        "logical_bytes_reclaimed": qualified[
            "logical_bytes_reclaimed"
        ],
        "physical_backend": qualified["physical_backend"],
        "prerequisites": prerequisites,
        "production_candidate": True,
        "residue": dict(qualified["residue"]),
        "restore_verified": qualified["restore_verified"],
        "schema": SCHEMA,
        "source": source_hashes(),
        "survivor_class_count": qualified["survivor_class_count"],
        "survivor_classes_hash": qualified["survivor_classes_hash"],
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "production GC result"))
    expected = {
        "authorization_consumed",
        "candidate_count",
        "candidate_set_hash",
        "cleanup_verified",
        "delete_untagged",
        "distribution",
        "dry_run_count",
        "input_gc_result_sha256",
        "logical_bytes_reclaimed",
        "physical_backend",
        "prerequisites",
        "production_candidate",
        "residue",
        "restore_verified",
        "schema",
        "source",
        "survivor_class_count",
        "survivor_classes_hash",
    }
    _exact_keys(result, expected, "production GC result")
    prerequisites = _mapping(
        result["prerequisites"],
        "production GC prerequisites",
    )
    _exact_keys(
        prerequisites,
        {"artifact_result_sha256", "release_readiness_sha256"},
        "production GC prerequisites",
    )
    _digest(
        prerequisites["artifact_result_sha256"],
        "production GC artifact prerequisite",
    )
    _digest(
        prerequisites["release_readiness_sha256"],
        "production GC release prerequisite",
    )
    _digest(result["input_gc_result_sha256"], "filesystem GC result")
    _digest(result["candidate_set_hash"], "GC candidate set")
    _digest(result["survivor_classes_hash"], "GC survivor classes")
    residue = _mapping(result["residue"], "production GC residue")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
        or result["authorization_consumed"] is not True
        or result["candidate_count"] != GC_RESULT.EXPECTED_CANDIDATES
        or result["cleanup_verified"] is not True
        or result["delete_untagged"] is not False
        or result["distribution"]
        != {
            "image": GC_RESULT.IMAGE,
            "revision": GC_RESULT.REVISION,
            "version": GC_RESULT.VERSION,
        }
        or result["dry_run_count"] != 2
        or result["logical_bytes_reclaimed"]
        != GC_RESULT.EXPECTED_RECLAIMED_BYTES
        or result["physical_backend"] != "filesystem"
        or result["restore_verified"] is not True
        or result["survivor_class_count"]
        != GC_RESULT.EXPECTED_SURVIVORS
        or residue
        != {
            "containers": 0,
            "networks": 0,
            "runtime_paths": 0,
            "total": 0,
        }
    ):
        raise ProductionGCResultError(
            "production GC result is not qualified"
        )
    return result


def _load_private(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise ProductionGCResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise ProductionGCResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except ProductionGCResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductionGCResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise ProductionGCResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise ProductionGCResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise ProductionGCResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ProductionGCResultError(
            "output directory ownership is unsafe"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError as error:
        raise ProductionGCResultError(
            "unable to write production GC result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _load_prerequisite(
    path: Path,
    label: str,
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except ProductionGCResultError as error:
        raise ProductionGCInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind a qualified filesystem GC/restore result to the exact "
            "candidate-qualified release and immutable-artifact transaction."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--artifact-result", type=Path, required=True)
    parser.add_argument("--gc-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        try:
            RGW_KMS_RESULT.require_release_qualified(release)
        except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
            raise ProductionGCInputsBlocked(str(error)) from error
        artifact, artifact_digest = _load_prerequisite(
            arguments.artifact_result,
            "artifact specialist result",
        )
        gc_result, gc_digest = _load_private(
            arguments.gc_result,
            "filesystem GC specialist result",
        )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            artifact_result=artifact,
            artifact_digest=artifact_digest,
            gc_result=gc_result,
            gc_digest=gc_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProductionGCInputsBlocked as error:
        print(
            f"production GC gate blocked: {error}",
            file=sys.stderr,
        )
        return 3
    except ProductionGCResultError as error:
        print(
            f"production GC result error: {error}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
