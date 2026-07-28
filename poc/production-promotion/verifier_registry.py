from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Callable

DIRECTORY = Path(__file__).resolve().parent
PRODUCTION_REGISTRY_SOURCE = DIRECTORY / "verifier-bundles-v2.json"
VERIFIERS_DIRECTORY = DIRECTORY / "verifiers"
REGISTRY_SCHEMA = "coffer.checkpoint-verifier-registry/v2"
BUNDLE_SCHEMA = "coffer.checkpoint-verifier-bundle/v2"
SUPPORTED_BUNDLES = {
    "coffer.checkpoint-verifier.v2.0.0": (
        VERIFIERS_DIRECTORY / "checkpoint_v2_0"
    ),
}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


class VerifierRegistryError(RuntimeError):
    pass


class UnsupportedVerifierError(VerifierRegistryError):
    pass


def _strict_json(payload: bytes) -> object:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise VerifierRegistryError(
                    "verifier registry JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            payload,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                VerifierRegistryError(
                    f"verifier registry JSON constant {value} is not allowed"
                )
            ),
        )
    except VerifierRegistryError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise VerifierRegistryError(
            "verifier registry JSON is invalid"
        ) from error


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise VerifierRegistryError(
            "verifier registry value is not canonical JSON"
        ) from error


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VerifierRegistryError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise VerifierRegistryError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise VerifierRegistryError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise VerifierRegistryError(f"{label} is invalid")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise VerifierRegistryError(f"{label} is invalid")
    return value


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise VerifierRegistryError(f"{label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise VerifierRegistryError(f"{label} is invalid") from error
    if parsed.isoformat() != value:
        raise VerifierRegistryError(f"{label} is invalid")
    return parsed


def bundle_metadata(bundle_id: str) -> dict[str, Any]:
    bundle_directory = SUPPORTED_BUNDLES.get(bundle_id)
    if bundle_directory is None:
        raise UnsupportedVerifierError(
            "checkpoint verifier bundle is not installed"
        )
    manifest_path = bundle_directory / "bundle-manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise UnsupportedVerifierError(
            "checkpoint verifier manifest is unavailable"
        ) from error
    manifest = _mapping(
        _strict_json(manifest_bytes),
        "checkpoint verifier manifest",
    )
    _exact_keys(
        manifest,
        {
            "bundle_id",
            "dependencies",
            "entry_point",
            "files",
            "python_requires",
            "schema",
        },
        "checkpoint verifier manifest",
    )
    files = _mapping(manifest["files"], "checkpoint verifier files")
    dependencies = _mapping(
        manifest["dependencies"],
        "checkpoint verifier dependencies",
    )
    if (
        manifest["schema"] != BUNDLE_SCHEMA
        or manifest["bundle_id"] != bundle_id
        or manifest["entry_point"]
        != "checkpoint_v2_0.verifier:verify_checkpoint_record"
        or manifest["python_requires"] != ">=3.11"
        or set(files) != {"__init__.py", "verifier.py"}
        or dependencies != {"cryptography": "49.0.0"}
    ):
        raise UnsupportedVerifierError(
            "checkpoint verifier manifest contract changed"
        )
    for relative_name, expected_digest in files.items():
        if (
            Path(relative_name).name != relative_name
            or relative_name.startswith(".")
        ):
            raise UnsupportedVerifierError(
                "checkpoint verifier file name is unsafe"
            )
        path = bundle_directory / relative_name
        try:
            details = path.lstat()
            payload = path.read_bytes()
        except OSError as error:
            raise UnsupportedVerifierError(
                "checkpoint verifier file is unavailable"
            ) from error
        if not path.is_file() or path.is_symlink() or details.st_nlink != 1:
            raise UnsupportedVerifierError(
                "checkpoint verifier file identity is unsafe"
            )
        if _sha256_bytes(payload) != _digest(
            expected_digest,
            f"checkpoint verifier file {relative_name}",
        ):
            raise UnsupportedVerifierError(
                "checkpoint verifier file digest changed"
            )
    try:
        installed_cryptography = importlib.metadata.version("cryptography")
    except importlib.metadata.PackageNotFoundError as error:
        raise UnsupportedVerifierError(
            "checkpoint verifier cryptography dependency is unavailable"
        ) from error
    if installed_cryptography != dependencies["cryptography"]:
        raise UnsupportedVerifierError(
            "checkpoint verifier cryptography dependency changed"
        )
    canonical_manifest = _canonical_bytes(manifest)
    manifest_sha256 = _sha256_bytes(canonical_manifest)
    bundle_sha256 = _sha256_bytes(
        b"coffer.checkpoint-verifier-bundle/v2\x00" + canonical_manifest
    )
    return {
        "bundle_id": bundle_id,
        "bundle_sha256": bundle_sha256,
        "directory": bundle_directory,
        "entry_point": manifest["entry_point"],
        "manifest": dict(manifest),
        "manifest_sha256": manifest_sha256,
    }


def _load_registry(path: Path) -> dict[str, Any]:
    try:
        registry = _mapping(
            _strict_json(path.read_bytes()),
            "checkpoint verifier registry",
        )
    except OSError as error:
        raise VerifierRegistryError(
            "checkpoint verifier registry is unavailable"
        ) from error
    _exact_keys(
        registry,
        {"entries", "schema"},
        "checkpoint verifier registry",
    )
    if registry["schema"] != REGISTRY_SCHEMA:
        raise VerifierRegistryError(
            "checkpoint verifier registry schema is invalid"
        )
    entries = _array(registry["entries"], "checkpoint verifier entries")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(entries):
        entry = _mapping(raw, f"checkpoint verifier entry {index}")
        _exact_keys(
            entry,
            {
                "accepted_policy_raw_sha256",
                "bundle_id",
                "bundle_sha256",
                "checkpoint_authority_key_ids",
                "entry_point",
                "manifest_sha256",
                "status",
                "support_ends_on",
            },
            f"checkpoint verifier entry {index}",
        )
        bundle_id = _identifier(
            entry["bundle_id"],
            f"checkpoint verifier entry {index} bundle ID",
        )
        authority_ids = _array(
            entry["checkpoint_authority_key_ids"],
            f"checkpoint verifier entry {index} authority IDs",
        )
        if (
            bundle_id in seen
            or entry["status"] != "active"
            or authority_ids != sorted(set(authority_ids))
            or not authority_ids
        ):
            raise VerifierRegistryError(
                f"checkpoint verifier entry {index} is invalid"
            )
        seen.add(bundle_id)
        parsed.append(
            {
                "accepted_policy_raw_sha256": _digest(
                    entry["accepted_policy_raw_sha256"],
                    f"checkpoint verifier entry {index} policy",
                ),
                "bundle_id": bundle_id,
                "bundle_sha256": _digest(
                    entry["bundle_sha256"],
                    f"checkpoint verifier entry {index} bundle",
                ),
                "checkpoint_authority_key_ids": [
                    _identifier(
                        key_id,
                        f"checkpoint verifier entry {index} authority",
                    )
                    for key_id in authority_ids
                ],
                "entry_point": entry["entry_point"],
                "manifest_sha256": _digest(
                    entry["manifest_sha256"],
                    f"checkpoint verifier entry {index} manifest",
                ),
                "status": "active",
                "support_ends_on": _date(
                    entry["support_ends_on"],
                    f"checkpoint verifier entry {index} support end",
                ).isoformat(),
            }
        )
        if parsed[-1]["entry_point"] != (
            "checkpoint_v2_0.verifier:verify_checkpoint_record"
        ):
            raise VerifierRegistryError(
                f"checkpoint verifier entry {index} entry point is invalid"
            )
    if parsed != sorted(parsed, key=lambda item: item["bundle_id"]):
        raise VerifierRegistryError(
            "checkpoint verifier entries are not sorted"
        )
    return {"entries": parsed, "schema": REGISTRY_SCHEMA}


def resolve_verifier(
    *,
    bundle_id: str,
    bundle_sha256: str,
    registry_path: Path = PRODUCTION_REGISTRY_SOURCE,
) -> tuple[dict[str, Any], Callable[..., dict[str, Any]]]:
    registry = _load_registry(registry_path)
    matches = [
        entry for entry in registry["entries"] if entry["bundle_id"] == bundle_id
    ]
    if len(matches) != 1:
        raise UnsupportedVerifierError(
            "checkpoint verifier is not admitted by the registry"
        )
    entry = matches[0]
    metadata = bundle_metadata(bundle_id)
    if (
        _digest(bundle_sha256, "requested checkpoint verifier bundle")
        != entry["bundle_sha256"]
        or metadata["bundle_sha256"] != entry["bundle_sha256"]
        or metadata["manifest_sha256"] != entry["manifest_sha256"]
        or metadata["entry_point"] != entry["entry_point"]
    ):
        raise UnsupportedVerifierError(
            "checkpoint verifier registry binding changed"
        )
    module_path = metadata["directory"] / "verifier.py"
    module_name = (
        "coffer_frozen_checkpoint_verifier_"
        + hashlib.sha256(bundle_id.encode()).hexdigest()[:16]
    )
    module = sys.modules.get(module_name)
    if module is None:
        specification = importlib.util.spec_from_file_location(
            module_name,
            module_path,
        )
        if specification is None or specification.loader is None:
            raise UnsupportedVerifierError(
                "checkpoint verifier entry point is unavailable"
            )
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        try:
            specification.loader.exec_module(module)
        except Exception as error:
            raise UnsupportedVerifierError(
                "checkpoint verifier bundle could not be loaded"
            ) from error
    verifier = getattr(module, "verify_checkpoint_record", None)
    if not callable(verifier):
        raise UnsupportedVerifierError(
            "checkpoint verifier entry point is invalid"
        )
    return entry, verifier
