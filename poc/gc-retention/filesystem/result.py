from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[2]
TOPOLOGY = DIRECTORY.parent / "topology.json"

CANDIDATE_SCHEMA = "coffer.gc-filesystem-result-candidate/v1"
SCHEMA = "coffer.gc-filesystem-result/v1"
COLLECTOR_SCHEMA = "coffer.gc-collector-output/v1"
AUTHORIZATION_SCHEMA = "coffer.gc-filesystem-authorization/v1"
CONSUMPTION_SCHEMA = "coffer.gc-filesystem-consumption/v1"
SURVIVOR_SCHEMA = "coffer.gc-filesystem-survivors/v1"
RECLAIM_SCHEMA = "coffer.gc-filesystem-reclaim/v1"
TOPOLOGY_SCHEMA = "coffer.gc-retention-topology/v1"

VERSION = "v3.1.1"
REVISION = "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
IMAGE = (
    "docker.io/library/registry:3.1.1@"
    "sha256:1be55279f18a2fe1a74edf2664cac61c1bea305b7b4642dab412e7affdcb3e33"
)
EXPECTED_CANDIDATES = 5
EXPECTED_SURVIVORS = 9
EXPECTED_RECLAIMED_BYTES = 613

SOURCE_PATHS = {
    "collector_output_sha256": DIRECTORY.parent / "collector_output.py",
    "compose_sha256": DIRECTORY / "compose.yaml",
    "filesystem_adapter_sha256": DIRECTORY / "filesystem_adapter.py",
    "prepare_fixture_sha256": DIRECTORY / "prepare_fixture.py",
    "registry_config_sha256": DIRECTORY / "registry-config.yml",
    "result_compiler_sha256": Path(__file__).resolve(),
    "topology_sha256": TOPOLOGY,
    "verify_fixture_sha256": DIRECTORY / "verify_fixture.py",
    "verify_harness_sha256": DIRECTORY / "verify.sh",
}


class GCResultError(RuntimeError):
    pass


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise GCResultError(f"unable to hash {path}") from error


def source_hashes() -> dict[str, str]:
    return {
        name: _sha256(path)
        for name, path in sorted(SOURCE_PATHS.items())
    }


def _hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GCResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise GCResultError(f"{label} fields are invalid")


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GCResultError(f"{label} is invalid")
    return value


def _load_private(path: Path, label: str) -> dict[str, Any]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise GCResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 4 * 1024 * 1024:
            raise GCResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except GCResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GCResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise GCResultError(f"{label} must be a JSON object")
    return value


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise GCResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise GCResultError("output path already exists")
    try:
        parent = path.parent
        details = parent.lstat()
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise GCResultError("output directory ownership is unsafe")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{path.name}.",
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except GCResultError:
        raise
    except OSError as error:
        raise GCResultError("unable to write output") from error
    finally:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)


def _validate_collector(
    value: object,
    label: str,
) -> Mapping[str, Any]:
    item = _mapping(value, label)
    _exact_keys(
        item,
        {
            "candidate_set_hash",
            "candidate_total",
            "distribution_revision",
            "distribution_version",
            "eligible_blob_count",
            "eligible_link_count",
            "eligible_manifest_count",
            "marked_blob_count",
            "normalized_output_hash",
            "observed_mark_line_count",
            "repository_count",
            "schema",
        },
        label,
    )
    if (
        item["schema"] != COLLECTOR_SCHEMA
        or item["distribution_version"] != VERSION
        or item["distribution_revision"] != REVISION
        or item["candidate_total"] != EXPECTED_CANDIDATES
        or item["eligible_manifest_count"] != 0
        or _positive_integer(item["repository_count"], f"{label}.repository_count")
        < 1
    ):
        raise GCResultError(f"{label} is not the accepted collection result")
    for name in ("candidate_set_hash", "normalized_output_hash"):
        if (
            not isinstance(item[name], str)
            or len(item[name]) != 71
            or not item[name].startswith("sha256:")
        ):
            raise GCResultError(f"{label}.{name} is invalid")
    return item


def _validate_survivors(
    value: object,
    label: str,
    *,
    mode: str,
    expected_classes: list[str],
) -> Mapping[str, Any]:
    item = _mapping(value, label)
    _exact_keys(
        item,
        {
            "deleted_manifest_unreadable",
            "mode",
            "schema",
            "shared_blob_repositories",
            "survivor_classes",
        },
        label,
    )
    if (
        item["schema"] != SURVIVOR_SCHEMA
        or item["mode"] != mode
        or item["deleted_manifest_unreadable"] is not True
        or item["shared_blob_repositories"] != 2
        or item["survivor_classes"] != expected_classes
        or len(expected_classes) != EXPECTED_SURVIVORS
    ):
        raise GCResultError(f"{label} is incomplete")
    return item


def compile_candidate(
    *,
    first: object,
    second: object,
    collection: object,
    authorization: object,
    consumption: object,
    survivors: object,
    restored_survivors: object,
    reclaim: object,
    topology: object,
) -> dict[str, Any]:
    topology_value = _mapping(topology, "topology")
    if topology_value.get("schema") != TOPOLOGY_SCHEMA:
        raise GCResultError("topology schema is unsupported")
    collector_contract = _mapping(
        topology_value.get("collector"),
        "topology.collector",
    )
    raw_expected_classes = topology_value.get("survivor_classes")
    if (
        collector_contract.get("distribution_version") != VERSION
        or collector_contract.get("distribution_revision") != REVISION
        or collector_contract.get("allow_delete_untagged") is not False
        or collector_contract.get("dry_run_count") != 2
        or not isinstance(raw_expected_classes, list)
        or len(raw_expected_classes) != EXPECTED_SURVIVORS
        or len(set(raw_expected_classes)) != EXPECTED_SURVIVORS
        or any(not isinstance(item, str) for item in raw_expected_classes)
    ):
        raise GCResultError("topology collection contract changed")
    expected_classes = sorted(raw_expected_classes)

    first_value = _validate_collector(first, "first dry run")
    second_value = _validate_collector(second, "second dry run")
    collection_value = _validate_collector(collection, "collection")
    if first_value != second_value or first_value != collection_value:
        raise GCResultError("collector candidate evidence changed")

    authorization_value = _mapping(authorization, "authorization")
    _exact_keys(
        authorization_value,
        {
            "authorization_id",
            "binding",
            "binding_hash",
            "consumed",
            "consumed_at",
            "created_at",
            "expires_at",
            "schema",
        },
        "authorization",
    )
    binding = {
        "candidate_set_hash": first_value["candidate_set_hash"],
        "distribution_revision": REVISION,
        "distribution_version": VERSION,
        "normalized_output_hash": first_value["normalized_output_hash"],
    }
    if (
        authorization_value["schema"] != AUTHORIZATION_SCHEMA
        or authorization_value["binding"] != binding
        or authorization_value["binding_hash"] != _hash(binding)
        or authorization_value["consumed"] is not True
    ):
        raise GCResultError("collection authorization is invalid")

    consumption_value = _mapping(consumption, "consumption")
    _exact_keys(
        consumption_value,
        {
            "authorization_id_hash",
            "binding_hash",
            "consumed_at",
            "schema",
        },
        "consumption",
    )
    if (
        consumption_value["schema"] != CONSUMPTION_SCHEMA
        or consumption_value["authorization_id_hash"]
        != _hash(authorization_value["authorization_id"])
        or consumption_value["binding_hash"]
        != authorization_value["binding_hash"]
        or consumption_value["consumed_at"]
        != authorization_value["consumed_at"]
    ):
        raise GCResultError("collection consumption is invalid")

    survivor_value = _validate_survivors(
        survivors,
        "collected survivors",
        mode="collected",
        expected_classes=expected_classes,
    )
    restored_value = _validate_survivors(
        restored_survivors,
        "restored survivors",
        mode="restored",
        expected_classes=expected_classes,
    )
    if {
        key: value
        for key, value in survivor_value.items()
        if key != "mode"
    } != {
        key: value
        for key, value in restored_value.items()
        if key != "mode"
    }:
        raise GCResultError("restored survivor evidence changed")

    reclaim_value = _mapping(reclaim, "reclaim")
    _exact_keys(
        reclaim_value,
        {
            "logical_bytes_after",
            "logical_bytes_before",
            "logical_bytes_reclaimed",
            "physical_backend",
            "schema",
            "tree_files_after",
            "tree_files_before",
            "tree_files_reclaimed",
        },
        "reclaim",
    )
    if (
        reclaim_value["schema"] != RECLAIM_SCHEMA
        or reclaim_value["physical_backend"] != "filesystem"
        or reclaim_value["logical_bytes_reclaimed"] != EXPECTED_RECLAIMED_BYTES
        or reclaim_value["logical_bytes_before"]
        - reclaim_value["logical_bytes_after"]
        != EXPECTED_RECLAIMED_BYTES
        or _positive_integer(
            reclaim_value["tree_files_reclaimed"],
            "reclaim.tree_files_reclaimed",
        )
        < 1
    ):
        raise GCResultError("reclaim evidence is invalid")

    return {
        "authorization_consumed": True,
        "candidate_count": EXPECTED_CANDIDATES,
        "candidate_set_hash": first_value["candidate_set_hash"],
        "cleanup_verified": False,
        "delete_untagged": False,
        "distribution": {
            "image": IMAGE,
            "revision": REVISION,
            "version": VERSION,
        },
        "dry_run_count": 2,
        "logical_bytes_reclaimed": EXPECTED_RECLAIMED_BYTES,
        "physical_backend": "filesystem",
        "restore_verified": True,
        "schema": CANDIDATE_SCHEMA,
        "source": source_hashes(),
        "survivor_class_count": EXPECTED_SURVIVORS,
        "survivor_classes_hash": _hash(expected_classes),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    item = dict(_mapping(value, "GC result"))
    _exact_keys(
        item,
        {
            "authorization_consumed",
            "candidate_count",
            "candidate_set_hash",
            "cleanup_verified",
            "delete_untagged",
            "distribution",
            "dry_run_count",
            "logical_bytes_reclaimed",
            "physical_backend",
            "residue",
            "restore_verified",
            "schema",
            "source",
            "survivor_class_count",
            "survivor_classes_hash",
        },
        "GC result",
    )
    distribution = _mapping(item["distribution"], "GC result.distribution")
    residue = _mapping(item["residue"], "GC result.residue")
    if (
        item["schema"] != SCHEMA
        or item["authorization_consumed"] is not True
        or item["candidate_count"] != EXPECTED_CANDIDATES
        or item["cleanup_verified"] is not True
        or item["delete_untagged"] is not False
        or item["dry_run_count"] != 2
        or item["logical_bytes_reclaimed"] != EXPECTED_RECLAIMED_BYTES
        or item["physical_backend"] != "filesystem"
        or item["restore_verified"] is not True
        or item["survivor_class_count"] != EXPECTED_SURVIVORS
        or distribution
        != {"image": IMAGE, "revision": REVISION, "version": VERSION}
        or residue
        != {
            "containers": 0,
            "networks": 0,
            "runtime_paths": 0,
            "total": 0,
        }
        or item["source"] != source_hashes()
    ):
        raise GCResultError("GC result is not qualified")
    for name in ("candidate_set_hash", "survivor_classes_hash"):
        if (
            not isinstance(item[name], str)
            or len(item[name]) != 71
            or not item[name].startswith("sha256:")
        ):
            raise GCResultError(f"GC result {name} is invalid")
    return item


def finalize_candidate(value: object) -> dict[str, Any]:
    candidate = dict(_mapping(value, "GC result candidate"))
    if (
        candidate.get("schema") != CANDIDATE_SCHEMA
        or candidate.get("cleanup_verified") is not False
        or candidate.get("source") != source_hashes()
    ):
        raise GCResultError("GC result candidate is invalid")
    final = dict(candidate)
    final["schema"] = SCHEMA
    final["cleanup_verified"] = True
    final["residue"] = {
        "containers": 0,
        "networks": 0,
        "runtime_paths": 0,
        "total": 0,
    }
    return validate_final_result(final)


def _load_topology() -> dict[str, Any]:
    try:
        value = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GCResultError("topology is invalid") from error
    if not isinstance(value, dict):
        raise GCResultError("topology is invalid")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile exact disposable filesystem GC evidence."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage")
    for name in (
        "first",
        "second",
        "collection",
        "authorization",
        "consumption",
        "survivors",
        "restored-survivors",
        "reclaim",
    ):
        stage.add_argument(f"--{name}", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--candidate", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "stage":
            candidate = compile_candidate(
                first=_load_private(arguments.first, "first dry run"),
                second=_load_private(arguments.second, "second dry run"),
                collection=_load_private(arguments.collection, "collection"),
                authorization=_load_private(arguments.authorization, "authorization"),
                consumption=_load_private(arguments.consumption, "consumption"),
                survivors=_load_private(arguments.survivors, "survivors"),
                restored_survivors=_load_private(
                    arguments.restored_survivors,
                    "restored survivors",
                ),
                reclaim=_load_private(arguments.reclaim, "reclaim"),
                topology=_load_topology(),
            )
            _write_private(arguments.output, candidate)
        else:
            candidate = _load_private(arguments.candidate, "GC result candidate")
            _write_private(arguments.output, finalize_candidate(candidate))
            arguments.candidate.unlink()
        return 0
    except GCResultError as error:
        print(f"GC result error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
