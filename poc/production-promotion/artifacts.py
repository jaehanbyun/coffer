from __future__ import annotations

import argparse
import hashlib
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
READINESS_SOURCE = DIRECTORY / "readiness.py"
CORE_VERIFIER = ROOT / "poc" / "production-images" / "verify_evidence.py"
UI_VERIFIER = ROOT / "poc" / "ui-images" / "qualification.py"

SCHEMA = "coffer.production-promotion-artifacts/v1"
RELEASE_SCHEMA = "coffer.production-promotion-release-readiness/v1"
CORE_SCHEMA = "coffer.production-image-qualification.v1"
UI_SCHEMA = "coffer.ui-image-qualification/v1"
ARCHITECTURES = ("amd64", "arm64")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


class ArtifactResultError(RuntimeError):
    pass


class ArtifactInputsBlocked(ArtifactResultError):
    pass


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise ArtifactResultError(f"unable to hash {path}") from error


def source_hashes() -> dict[str, str]:
    return {
        "artifact_compiler_sha256": _sha256(Path(__file__).resolve()),
        "core_verifier_sha256": _sha256(CORE_VERIFIER),
        "release_readiness_verifier_sha256": _sha256(READINESS_SOURCE),
        "ui_verifier_sha256": _sha256(UI_VERIFIER),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactResultError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArtifactResultError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ArtifactResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ArtifactResultError(f"{label} is invalid")
    return value


def require_release_qualified(value: object) -> dict[str, Any]:
    release = dict(_mapping(value, "release readiness"))
    if (
        release.get("schema") != RELEASE_SCHEMA
        or release.get("status") != "candidate-qualified"
        or release.get("release_inputs_qualified") is not True
        or release.get("production_candidate") is not False
        or release.get("blockers") != []
    ):
        raise ArtifactInputsBlocked(
            "release inputs are not candidate-qualified"
        )
    components = _mapping(
        release.get("components"),
        "release readiness components",
    )
    if set(components) != {"distribution", "ceph", "oslo_messaging"}:
        raise ArtifactInputsBlocked(
            "release input components are incomplete"
        )
    for name, raw in components.items():
        component = _mapping(raw, f"release readiness {name}")
        if (
            component.get("status") != "candidate-qualified"
            or component.get("reasons") != []
            or not isinstance(component.get("version"), str)
            or not component["version"]
            or not isinstance(component.get("revision"), str)
            or REVISION.fullmatch(component["revision"]) is None
        ):
            raise ArtifactInputsBlocked(
                f"release input {name} is not candidate-qualified"
            )
    expected_sources = {
        "upstream_classifier_sha256": _sha256(
            ROOT / "poc" / "production-images" / "check_upstream_readiness.py"
        ),
        "ui_classifier_sha256": _sha256(
            ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.py"
        ),
        "ui_contract_sha256": _sha256(
            ROOT / "poc" / "ui-images" / "oslo_messaging_release_gate.json"
        ),
    }
    if release.get("source") != expected_sources:
        raise ArtifactInputsBlocked("release readiness source binding changed")
    return release


def _zero_critical_high(value: object, label: str) -> None:
    counts = _mapping(value, label)
    if counts.get("critical") != 0 or counts.get("high") != 0:
        raise ArtifactResultError(f"{label} retains Critical/High findings")


def _core_images(value: object, architecture: str) -> dict[str, str]:
    images = _array(value, f"{architecture} core images")
    if len(images) != 2:
        raise ArtifactResultError(
            f"{architecture} core image inventory is incomplete"
        )
    result: dict[str, str] = {}
    for raw in images:
        image = _mapping(raw, f"{architecture} core image")
        user = image.get("user")
        image_id = image.get("id")
        labels = _mapping(
            image.get("labels"),
            f"{architecture} core image labels",
        )
        if (
            user not in {"coffer", "registry"}
            or user in result
            or image.get("architecture") != architecture
            or image.get("os") != "linux"
            or not isinstance(image_id, str)
            or HEX_SHA256.fullmatch(image_id) is None
            or REVISION.fullmatch(
                str(labels.get("org.opencontainers.image.revision", ""))
            )
            is None
        ):
            raise ArtifactResultError(
                f"{architecture} core image contract is invalid"
            )
        result[str(user)] = f"sha256:{image_id}"
    if set(result) != {"coffer", "registry"}:
        raise ArtifactResultError(
            f"{architecture} core image users are incomplete"
        )
    return result


def _validate_core(
    value: object,
    images: object,
    *,
    architecture: str,
) -> tuple[dict[str, str], str]:
    result = _mapping(value, f"{architecture} core qualification")
    _exact_keys(
        result,
        {
            "blockers",
            "govulncheck",
            "image_contract",
            "production_candidate",
            "release_provenance",
            "runtime_contract",
            "sbom",
            "schema",
            "scout",
            "secrets",
            "trivy",
        },
        f"{architecture} core qualification",
    )
    contract = _mapping(
        result["image_contract"],
        f"{architecture} core image contract",
    )
    revisions = contract.get("revisions")
    if (
        result["schema"] != CORE_SCHEMA
        or result["production_candidate"] is not True
        or result["blockers"] != []
        or result["runtime_contract"] is not True
        or result["release_provenance"] is not True
        or contract.get("valid") is not True
        or contract.get("architectures") != [architecture]
        or contract.get("operating_systems") != ["linux"]
        or contract.get("users") != ["coffer", "registry"]
        or not isinstance(revisions, list)
        or len(revisions) != 1
        or not isinstance(revisions[0], str)
        or REVISION.fullmatch(revisions[0]) is None
    ):
        raise ArtifactResultError(
            f"{architecture} core qualification is not accepted"
        )
    for scanner in ("scout", "trivy"):
        scanner_result = _mapping(
            result[scanner],
            f"{architecture} {scanner}",
        )
        if set(scanner_result) != {"coffer", "registry"}:
            raise ArtifactResultError(
                f"{architecture} {scanner} surfaces are incomplete"
            )
        for surface in ("coffer", "registry"):
            _zero_critical_high(
                scanner_result[surface],
                f"{architecture} {scanner} {surface}",
            )
    secrets = _mapping(result["secrets"], f"{architecture} secrets")
    sbom = _mapping(result["sbom"], f"{architecture} SBOM")
    if (
        secrets != {"coffer": 0, "registry": 0}
        or set(sbom) != {"coffer", "registry"}
        or any(
            not isinstance(_mapping(item, "SBOM").get("packages"), int)
            or _mapping(item, "SBOM")["packages"] < 1
            for item in sbom.values()
        )
    ):
        raise ArtifactResultError(
            f"{architecture} core SBOM/secret evidence is invalid"
        )
    govulncheck = _mapping(
        result["govulncheck"],
        f"{architecture} govulncheck",
    )
    if govulncheck != {
        "release_binary_symbols": 0,
        "source_reachable": 0,
    }:
        raise ArtifactResultError(
            f"{architecture} Distribution remains vulnerable"
        )
    return _core_images(images, architecture), revisions[0]


def _ui_image_ids(value: object, architecture: str) -> dict[str, str]:
    images = _mapping(value, f"{architecture} UI images")
    if set(images) != {"horizon", "skyline"}:
        raise ArtifactResultError(
            f"{architecture} UI image surfaces are incomplete"
        )
    result: dict[str, str] = {}
    for surface in ("horizon", "skyline"):
        pair = _mapping(images[surface], f"{architecture} {surface} images")
        if set(pair) != {"parent", "custom"}:
            raise ArtifactResultError(
                f"{architecture} {surface} image pair is incomplete"
            )
        custom = _mapping(
            pair["custom"],
            f"{architecture} {surface} custom image",
        )
        result[surface] = _digest(
            custom.get("id"),
            f"{architecture} {surface} custom image",
        )
    return result


def _validate_ui(
    value: object,
    *,
    architecture: str,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    result = _mapping(value, f"{architecture} UI qualification")
    _exact_keys(
        result,
        {
            "architecture",
            "artifacts",
            "blockers",
            "images",
            "platform",
            "production_candidate",
            "scanners",
            "schema",
            "sources",
            "status",
            "surfaces",
        },
        f"{architecture} UI qualification",
    )
    if (
        result["schema"] != UI_SCHEMA
        or result["architecture"] != architecture
        or result["platform"] != f"linux/{architecture}"
        or result["status"] != "qualified"
        or result["production_candidate"] is not True
        or result["blockers"] != []
    ):
        raise ArtifactResultError(
            f"{architecture} UI qualification is not accepted"
        )
    sources = dict(_mapping(result["sources"], f"{architecture} UI sources"))
    if (
        set(sources) != {"horizon", "kolla", "skyline"}
        or any(
            not isinstance(revision, str)
            or REVISION.fullmatch(revision) is None
            for revision in sources.values()
        )
    ):
        raise ArtifactResultError(
            f"{architecture} UI source revisions are invalid"
        )
    artifacts = _mapping(result["artifacts"], f"{architecture} UI artifacts")
    artifact_hashes: dict[str, str] = {}
    for surface in ("horizon", "skyline"):
        artifact = _mapping(
            artifacts.get(surface),
            f"{architecture} {surface} artifact",
        )
        artifact_hashes[surface] = _digest(
            f"sha256:{artifact.get('sha256')}",
            f"{architecture} {surface} artifact",
        )
    surfaces = _mapping(result["surfaces"], f"{architecture} UI surfaces")
    if set(surfaces) != {"horizon", "skyline"}:
        raise ArtifactResultError(
            f"{architecture} UI surface results are incomplete"
        )
    for surface, raw in surfaces.items():
        surface_result = _mapping(
            raw,
            f"{architecture} {surface} result",
        )
        delta = _mapping(
            surface_result.get("delta"),
            f"{architecture} {surface} delta",
        )
        for scanner in ("scout", "trivy"):
            if _mapping(delta.get(scanner), "UI delta") != {
                "introduced_critical_high": 0,
                "missing_parent_critical_high": 0,
            }:
                raise ArtifactResultError(
                    f"{architecture} {surface} finding delta is invalid"
                )
        image_results = _mapping(
            surface_result.get("images"),
            f"{architecture} {surface} image results",
        )
        for kind in ("parent", "custom"):
            image_result = _mapping(
                image_results.get(kind),
                f"{architecture} {surface} {kind}",
            )
            if image_result.get("secrets") != 0:
                raise ArtifactResultError(
                    f"{architecture} {surface} {kind} has secrets"
                )
            for scanner in ("scout", "trivy"):
                _zero_critical_high(
                    image_result.get(scanner),
                    f"{architecture} {surface} {kind} {scanner}",
                )
    return _ui_image_ids(result["images"], architecture), sources, artifact_hashes


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    core_results: Mapping[str, object],
    core_images: Mapping[str, object],
    core_digests: Mapping[str, str],
    core_image_digests: Mapping[str, str],
    ui_results: Mapping[str, object],
    ui_digests: Mapping[str, str],
) -> dict[str, Any]:
    require_release_qualified(release_readiness)
    expected = set(ARCHITECTURES)
    for label, value in (
        ("core results", core_results),
        ("core images", core_images),
        ("core digests", core_digests),
        ("core image digests", core_image_digests),
        ("UI results", ui_results),
        ("UI digests", ui_digests),
    ):
        if set(value) != expected:
            raise ArtifactResultError(f"{label} architectures are incomplete")

    architectures: list[dict[str, Any]] = []
    ui_sources: dict[str, dict[str, str]] = {}
    ui_artifacts: dict[str, dict[str, str]] = {}
    core_revisions: dict[str, str] = {}
    for architecture in ARCHITECTURES:
        core_ids, core_revision = _validate_core(
            core_results[architecture],
            core_images[architecture],
            architecture=architecture,
        )
        ui_ids, sources, artifacts = _validate_ui(
            ui_results[architecture],
            architecture=architecture,
        )
        core_revisions[architecture] = core_revision
        ui_sources[architecture] = sources
        ui_artifacts[architecture] = artifacts
        architectures.append(
            {
                "architecture": architecture,
                "core_images": core_ids,
                "core_images_sha256": _digest(
                    core_image_digests[architecture],
                    f"{architecture} core image evidence",
                ),
                "core_qualification_sha256": _digest(
                    core_digests[architecture],
                    f"{architecture} core qualification",
                ),
                "ui_images": ui_ids,
                "ui_qualification_sha256": _digest(
                    ui_digests[architecture],
                    f"{architecture} UI qualification",
                ),
            }
        )
    if (
        len(set(core_revisions.values())) != 1
        or ui_sources["amd64"] != ui_sources["arm64"]
        or ui_artifacts["amd64"] != ui_artifacts["arm64"]
        or core_revisions["amd64"] != ui_sources["amd64"]["kolla"]
    ):
        raise ArtifactResultError(
            "cross-architecture source/artifact identity changed"
        )
    return {
        "architectures": architectures,
        "cross_architecture": {
            "core_revision": core_revisions["amd64"],
            "ui_artifacts": ui_artifacts["amd64"],
            "ui_sources": ui_sources["amd64"],
        },
        "production_candidate": True,
        "release_readiness_sha256": _digest(
            release_digest,
            "release readiness",
        ),
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "artifact result"))
    _exact_keys(
        result,
        {
            "architectures",
            "cross_architecture",
            "production_candidate",
            "release_readiness_sha256",
            "schema",
            "source",
        },
        "artifact result",
    )
    architectures = _array(result["architectures"], "artifact architectures")
    parsed_architectures = [
        _mapping(item, "artifact architecture")
        for item in architectures
    ]
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
        or [item.get("architecture") for item in parsed_architectures]
        != list(ARCHITECTURES)
    ):
        raise ArtifactResultError("artifact result is not qualified")
    _digest(result["release_readiness_sha256"], "release readiness")
    for item in parsed_architectures:
        _exact_keys(
            item,
            {
                "architecture",
                "core_images",
                "core_images_sha256",
                "core_qualification_sha256",
                "ui_images",
                "ui_qualification_sha256",
            },
            "artifact architecture",
        )
        for name in (
            "core_images_sha256",
            "core_qualification_sha256",
            "ui_qualification_sha256",
        ):
            _digest(item[name], f"artifact architecture {name}")
        core = _mapping(item["core_images"], "artifact core images")
        ui = _mapping(item["ui_images"], "artifact UI images")
        if set(core) != {"coffer", "registry"} or set(ui) != {
            "horizon",
            "skyline",
        }:
            raise ArtifactResultError("artifact image surfaces are incomplete")
        for image_id in (*core.values(), *ui.values()):
            _digest(image_id, "artifact image ID")
    cross = _mapping(result["cross_architecture"], "cross architecture")
    if (
        set(cross) != {"core_revision", "ui_artifacts", "ui_sources"}
        or not isinstance(cross["core_revision"], str)
        or REVISION.fullmatch(cross["core_revision"]) is None
    ):
        raise ArtifactResultError("cross-architecture identity is invalid")
    ui_artifacts = _mapping(
        cross["ui_artifacts"],
        "cross architecture UI artifacts",
    )
    ui_sources = _mapping(
        cross["ui_sources"],
        "cross architecture UI sources",
    )
    if (
        set(ui_artifacts) != {"horizon", "skyline"}
        or set(ui_sources) != {"horizon", "kolla", "skyline"}
        or any(
            not isinstance(value, str)
            or REVISION.fullmatch(value) is None
            for value in ui_sources.values()
        )
        or ui_sources["kolla"] != cross["core_revision"]
    ):
        raise ArtifactResultError(
            "cross-architecture source/artifact identity is invalid"
        )
    for value in ui_artifacts.values():
        _digest(value, "cross architecture UI artifact")
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
            raise ArtifactResultError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise ArtifactResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except ArtifactResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise ArtifactResultError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise ArtifactResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise ArtifactResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ArtifactResultError("output directory ownership is unsafe")
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
        raise ArtifactResultError("unable to write artifact result") from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile immutable multi-architecture artifacts only after "
            "official release readiness qualifies."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    for architecture in ARCHITECTURES:
        parser.add_argument(
            f"--{architecture}-core-directory",
            type=Path,
            required=True,
        )
        parser.add_argument(
            f"--{architecture}-ui-result",
            type=Path,
            required=True,
        )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        require_release_qualified(release)

        core_results: dict[str, object] = {}
        core_images: dict[str, object] = {}
        core_digests: dict[str, str] = {}
        core_image_digests: dict[str, str] = {}
        ui_results: dict[str, object] = {}
        ui_digests: dict[str, str] = {}
        for architecture in ARCHITECTURES:
            core_directory = getattr(
                arguments,
                f"{architecture}_core_directory",
            )
            core_results[architecture], core_digests[architecture] = (
                _load_private(
                    core_directory / "qualification.json",
                    f"{architecture} core qualification",
                )
            )
            core_images[architecture], core_image_digests[architecture] = (
                _load_private(
                    core_directory / "images.json",
                    f"{architecture} core images",
                )
            )
            ui_results[architecture], ui_digests[architecture] = _load_private(
                getattr(arguments, f"{architecture}_ui_result"),
                f"{architecture} UI qualification",
            )
        result = compile_result(
            release_readiness=release,
            release_digest=release_digest,
            core_results=core_results,
            core_images=core_images,
            core_digests=core_digests,
            core_image_digests=core_image_digests,
            ui_results=ui_results,
            ui_digests=ui_digests,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ArtifactInputsBlocked as error:
        print(f"production artifact gate blocked: {error}", file=sys.stderr)
        return 3
    except ArtifactResultError as error:
        print(f"production artifact result error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
