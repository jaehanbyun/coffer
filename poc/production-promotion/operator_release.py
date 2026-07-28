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
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
KOLLA_MULTINODE_RESULT_SOURCE = DIRECTORY / "kolla_multinode.py"
ADR_DIRECTORY = ROOT / "docs" / "adrs"
RELEASE_NOTES_SOURCE = ROOT / "docs" / "release-notes" / "v0.1.0.md"
DOCUMENTATION_DIRECTORIES = (
    ROOT / "docs" / "architecture",
    ROOT / "docs" / "runbooks",
)
REVIEW_FILE_HASHES = {
    "handoff_sha256": ROOT / ".codex" / "state" / "HANDOFF.md",
    "operator_role_readme_sha256": (
        ROOT / "poc" / "kolla-ansible-role" / "README.md"
    ),
    "plan_sha256": (
        ROOT / "docs" / "exec-plans" / "0019-stage6-production-promotion.md"
    ),
    "project_readme_sha256": ROOT / "README.md",
    "pyproject_sha256": ROOT / "pyproject.toml",
    "release_notes_sha256": RELEASE_NOTES_SOURCE,
    "uv_lock_sha256": ROOT / "uv.lock",
}
REVIEW_TREES = {
    "adrs_tree_sha256": ADR_DIRECTORY,
    "ansible_tree_sha256": ROOT / "ansible",
    "architecture_tree_sha256": ROOT / "docs" / "architecture",
    "container_tree_sha256": ROOT / "docker",
    "configuration_tree_sha256": ROOT / "etc",
    "promotion_tree_sha256": DIRECTORY,
    "runbooks_tree_sha256": ROOT / "docs" / "runbooks",
    "source_tree_sha256": ROOT / "src",
    "tests_tree_sha256": ROOT / "tests",
}

SCHEMA = "coffer.production-promotion-operator-release-result/v1"
EVIDENCE_SCHEMA = "coffer.production-promotion-operator-release-evidence/v1"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.-]+)?$")
ADR_STATUS = re.compile(r"^- Status: (.+)$", re.MULTILINE)
RELEASE_NOTES_STATUS = re.compile(
    r"^- Promotion status: (.+)$",
    re.MULTILINE,
)
FINAL_ADR_STATUSES = frozenset({"accepted", "rejected", "superseded"})
DOCUMENTATION_CHECKS = (
    "api_cli_ui",
    "backup_restore",
    "configuration",
    "disaster_recovery",
    "existing_data",
    "gc",
    "installation",
    "known_limitations",
    "maintenance_identity_rotation",
    "observability",
    "rollback",
    "security",
    "slo_failure_budget",
    "uninstall_teardown",
    "upgrade",
)
SUPPLY_CHAIN_CHECKS = (
    "build_reproducibility",
    "image_signatures_verified",
    "immutable_image_references",
    "immutable_release_assets",
    "lock_verified",
    "native_architectures",
    "no_private_fork",
    "official_upstream_only",
    "provenance_verified",
    "sbom_verified",
    "source_archive_digest_verified",
    "tag_signature_verified",
    "vulnerability_attestations_verified",
)
REPOSITORY_CHECKS = (
    "compilation_passed",
    "diff_check_passed",
    "documentation_checks_passed",
    "full_regression_passed",
    "kolla_lifecycle_passed",
    "no_untracked_release_inputs",
    "promotion_harness_passed",
    "secret_scan_passed",
)
RELEASE_REVIEW_CHECKS = (
    "go_no_go_approved",
    "known_limitations_documented",
    "no_waivers",
    "production_boundary_accurate",
    "release_notes_complete",
    "rollback_owner_assigned",
    "rollback_runbook_verified",
    "support_matrix_approved",
    "upgrade_compatibility_approved",
)
EVIDENCE_HASH_NAMES = (
    "adr_review_sha256",
    "documentation_sha256",
    "release_review_sha256",
    "repository_verification_sha256",
    "supply_chain_sha256",
)
RESIDUE_KEYS = (
    "credential_files",
    "credentials",
    "release_staging_files",
    "reviewer_temporary_files",
    "runtime_resources",
    "secret_files",
)
SOURCE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".j2",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
}


class OperatorReleaseResultError(RuntimeError):
    pass


class OperatorReleaseInputsBlocked(OperatorReleaseResultError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise OperatorReleaseResultError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise OperatorReleaseResultError(f"unable to load {path}") from error
    return module


KOLLA_MULTINODE_RESULT = _load_module(
    "coffer_operator_release_kolla_multinode",
    KOLLA_MULTINODE_RESULT_SOURCE,
)
RGW_KMS_RESULT = KOLLA_MULTINODE_RESULT.RGW_KMS_RESULT


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise OperatorReleaseResultError(f"unable to hash {path}") from error


def _hash(value: object) -> str:
    return _sha256_bytes(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    )


def _review_sources(root: Path) -> list[Path]:
    try:
        return sorted(
            path
            for path in root.rglob("*")
            if (
                path.is_file()
                and not path.is_symlink()
                and "__pycache__" not in path.parts
                and ".pytest_cache" not in path.parts
                and path.suffix in SOURCE_SUFFIXES
            )
        )
    except OSError as error:
        raise OperatorReleaseResultError(
            f"unable to inspect source tree: {root}"
        ) from error


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    sources = _review_sources(root)
    if not sources:
        raise OperatorReleaseResultError(f"source tree is empty: {root}")
    try:
        for path in sources:
            relative = path.relative_to(root).as_posix().encode()
            payload = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
    except OSError as error:
        raise OperatorReleaseResultError(
            f"unable to hash source tree: {root}"
        ) from error
    return "sha256:" + digest.hexdigest()


def review_source_hashes() -> dict[str, str]:
    hashes = {
        name: _tree_hash(path)
        for name, path in REVIEW_TREES.items()
    }
    hashes.update(
        {
            name: _sha256(path)
            for name, path in REVIEW_FILE_HASHES.items()
        }
    )
    return dict(sorted(hashes.items()))


def source_hashes() -> dict[str, str]:
    return {
        "kolla_multinode_result_verifier_sha256": _sha256(
            KOLLA_MULTINODE_RESULT_SOURCE
        ),
        "operator_release_compiler_sha256": _sha256(
            Path(__file__).resolve()
        ),
        **review_source_hashes(),
    }


def adr_dispositions() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(ADR_DIRECTORY.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise OperatorReleaseResultError(
                f"unable to read ADR: {path.name}"
            ) from error
        match = ADR_STATUS.search(content)
        if match is None:
            raise OperatorReleaseResultError(
                f"ADR status is absent: {path.name}"
            )
        values[path.name] = match.group(1).strip().lower()
    if not values:
        raise OperatorReleaseResultError("ADR set is empty")
    return values


def project_version() -> str:
    try:
        value = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        raise OperatorReleaseResultError(
            "project version is unavailable"
        ) from error
    if not isinstance(value, str) or not value:
        raise OperatorReleaseResultError("project version is invalid")
    return value


def release_notes_status() -> str:
    try:
        content = RELEASE_NOTES_SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise OperatorReleaseResultError(
            "release notes are unavailable"
        ) from error
    match = RELEASE_NOTES_STATUS.search(content)
    if match is None:
        raise OperatorReleaseResultError(
            "release notes promotion status is absent"
        )
    return match.group(1).strip().lower()


def reviewed_document_count() -> int:
    documents = {
        path.resolve()
        for directory in DOCUMENTATION_DIRECTORIES
        for path in _review_sources(directory)
        if path.suffix in {".md", ".rst"}
    }
    documents.update(
        path.resolve()
        for path in REVIEW_FILE_HASHES.values()
        if path.suffix == ".md"
    )
    return len(documents)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorReleaseResultError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise OperatorReleaseResultError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise OperatorReleaseResultError(f"{label} is invalid")
    return value


def _revision(value: object, label: str) -> str:
    if not isinstance(value, str) or REVISION.fullmatch(value) is None:
        raise OperatorReleaseResultError(f"{label} is invalid")
    return value


def _positive_integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OperatorReleaseResultError(f"{label} is invalid")
    return value


def _true_map(
    value: object,
    *,
    expected: Sequence[str],
    label: str,
) -> dict[str, bool]:
    item = _mapping(value, label)
    _exact_keys(item, set(expected), label)
    if any(item[name] is not True for name in expected):
        raise OperatorReleaseResultError(f"{label} is incomplete")
    return {name: True for name in expected}


def _qualified_prerequisites(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
    data_protection_result: object,
    data_protection_digest: str,
    observability_result: object,
    observability_digest: str,
    gc_result: object,
    gc_digest: str,
    load_soak_result: object,
    load_soak_digest: str,
    kolla_multinode_result: object,
    kolla_multinode_digest: str,
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        base, release, artifact = (
            KOLLA_MULTINODE_RESULT._qualified_prerequisites(
                release_readiness=release_readiness,
                release_digest=release_digest,
                artifact_result=artifact_result,
                artifact_digest=artifact_digest,
                rgw_kms_result=rgw_kms_result,
                rgw_kms_digest=rgw_kms_digest,
                maintenance_result=maintenance_result,
                maintenance_digest=maintenance_digest,
                data_protection_result=data_protection_result,
                data_protection_digest=data_protection_digest,
                observability_result=observability_result,
                observability_digest=observability_digest,
                gc_result=gc_result,
                gc_digest=gc_digest,
                load_soak_result=load_soak_result,
                load_soak_digest=load_soak_digest,
            )
        )
        qualified_kolla = KOLLA_MULTINODE_RESULT.validate_final_result(
            kolla_multinode_result
        )
    except KOLLA_MULTINODE_RESULT.KollaMultinodeInputsBlocked as error:
        raise OperatorReleaseInputsBlocked(str(error)) from error
    except KOLLA_MULTINODE_RESULT.KollaMultinodeResultError as error:
        raise OperatorReleaseInputsBlocked(
            "Kolla multinode result is not candidate-qualified"
        ) from error
    if qualified_kolla["prerequisites"] != base:
        raise OperatorReleaseInputsBlocked(
            "Kolla multinode prerequisite binding changed"
        )
    return (
        {
            **base,
            "kolla_multinode_result_sha256": _digest(
                kolla_multinode_digest,
                "Kolla multinode result",
            ),
        },
        release,
        artifact,
        qualified_kolla,
    )


def _validate_execution(
    value: object,
    *,
    artifact: Mapping[str, Any],
    kolla: Mapping[str, Any],
) -> dict[str, Any]:
    item = _mapping(value, "operator release execution")
    expected = {
        "adapter",
        "independent_reviewer_count",
        "no_waivers",
        "non_synthetic",
        "release_revision",
        "review_duration_seconds",
        "reviewer_count",
        "source_tree_clean",
        "tag",
        "version",
    }
    _exact_keys(item, expected, "operator release execution")
    revision = _revision(item["release_revision"], "release revision")
    version = project_version()
    expected_tag = f"v{version}"
    if (
        item["adapter"] != "independent-review"
        or item["non_synthetic"] is not True
        or item["no_waivers"] is not True
        or item["source_tree_clean"] is not True
        or item["version"] != version
        or item["tag"] != expected_tag
        or TAG.fullmatch(item["tag"]) is None
        or revision != artifact["cross_architecture"]["core_revision"]
        or revision != kolla["execution"]["coffer_revision"]
    ):
        raise OperatorReleaseResultError(
            "operator release execution is incomplete"
        )
    reviewer_count = _positive_integer(
        item["reviewer_count"], "operator reviewer count"
    )
    independent_count = _positive_integer(
        item["independent_reviewer_count"],
        "independent reviewer count",
    )
    if reviewer_count < 2 or independent_count >= reviewer_count:
        raise OperatorReleaseResultError(
            "operator release review is not independent"
        )
    return {
        "adapter": "independent-review",
        "independent_reviewer_count": independent_count,
        "release_revision": revision,
        "review_duration_seconds": _positive_integer(
            item["review_duration_seconds"],
            "operator review duration",
        ),
        "reviewer_count": reviewer_count,
        "tag": expected_tag,
        "version": version,
    }


def _validate_adr_review(value: object) -> dict[str, Any]:
    item = _mapping(value, "ADR review")
    _exact_keys(
        item,
        {
            "dispositions",
            "evidence_sha256",
            "reviewed_count",
            "unresolved_count",
        },
        "ADR review",
    )
    current = adr_dispositions()
    dispositions = dict(_mapping(item["dispositions"], "ADR dispositions"))
    if dispositions != current:
        raise OperatorReleaseResultError("ADR review binding changed")
    unresolved = {
        name: status
        for name, status in current.items()
        if status not in FINAL_ADR_STATUSES
    }
    if (
        item["reviewed_count"] != len(current)
        or item["unresolved_count"] != 0
        or unresolved
    ):
        raise OperatorReleaseResultError(
            "ADR review has unresolved decisions"
        )
    return {
        "dispositions_sha256": _hash(current),
        "evidence_sha256": _digest(
            item["evidence_sha256"], "ADR review evidence"
        ),
        "reviewed_count": len(current),
        "unresolved_count": 0,
    }


def _validate_documentation(value: object) -> dict[str, Any]:
    item = _mapping(value, "operator documentation")
    _exact_keys(
        item,
        {
            "checks",
            "evidence_sha256",
            "local_links_valid",
            "markdown_fences_valid",
            "release_notes_sha256",
            "reviewed_document_count",
        },
        "operator documentation",
    )
    checks = _true_map(
        item["checks"],
        expected=DOCUMENTATION_CHECKS,
        label="operator documentation checks",
    )
    count = reviewed_document_count()
    if (
        item["markdown_fences_valid"] is not True
        or item["local_links_valid"] is not True
        or item["reviewed_document_count"] != count
        or release_notes_status() != "production-candidate"
    ):
        raise OperatorReleaseResultError(
            "operator documentation validation is incomplete"
        )
    release_notes_digest = _digest(
        item["release_notes_sha256"], "release notes"
    )
    if release_notes_digest != _sha256(RELEASE_NOTES_SOURCE):
        raise OperatorReleaseResultError(
            "release notes source binding changed"
        )
    return {
        "check_count": len(checks),
        "evidence_sha256": _digest(
            item["evidence_sha256"], "documentation evidence"
        ),
        "release_notes_sha256": release_notes_digest,
        "reviewed_document_count": count,
    }


def _validate_supply_chain(value: object) -> dict[str, Any]:
    item = _mapping(value, "supply-chain review")
    _exact_keys(
        item,
        {
            "checks",
            "critical_findings",
            "evidence_sha256",
            "high_findings",
            "image_signature_bundle_sha256",
            "provenance_bundle_sha256",
            "sbom_bundle_sha256",
            "source_archive_sha256",
            "vulnerability_bundle_sha256",
        },
        "supply-chain review",
    )
    checks = _true_map(
        item["checks"],
        expected=SUPPLY_CHAIN_CHECKS,
        label="supply-chain checks",
    )
    if (
        item["critical_findings"] != 0
        or item["high_findings"] != 0
    ):
        raise OperatorReleaseResultError(
            "supply-chain review has unresolved findings"
        )
    return {
        "check_count": len(checks),
        "critical_findings": 0,
        "evidence_sha256": _digest(
            item["evidence_sha256"], "supply-chain evidence"
        ),
        "high_findings": 0,
        "image_signature_bundle_sha256": _digest(
            item["image_signature_bundle_sha256"],
            "image signature bundle",
        ),
        "provenance_bundle_sha256": _digest(
            item["provenance_bundle_sha256"], "provenance bundle"
        ),
        "sbom_bundle_sha256": _digest(
            item["sbom_bundle_sha256"], "SBOM bundle"
        ),
        "source_archive_sha256": _digest(
            item["source_archive_sha256"], "source archive"
        ),
        "vulnerability_bundle_sha256": _digest(
            item["vulnerability_bundle_sha256"],
            "vulnerability bundle",
        ),
    }


def _validate_repository(value: object) -> dict[str, Any]:
    item = _mapping(value, "repository verification")
    _exact_keys(
        item,
        {
            "checks",
            "evidence_sha256",
            "full_regression_count",
            "kolla_lifecycle_count",
            "promotion_harness_count",
            "secret_scan_count",
        },
        "repository verification",
    )
    checks = _true_map(
        item["checks"],
        expected=REPOSITORY_CHECKS,
        label="repository verification checks",
    )
    return {
        "check_count": len(checks),
        "evidence_sha256": _digest(
            item["evidence_sha256"], "repository evidence"
        ),
        "full_regression_count": _positive_integer(
            item["full_regression_count"], "full regression count"
        ),
        "kolla_lifecycle_count": _positive_integer(
            item["kolla_lifecycle_count"], "Kolla lifecycle count"
        ),
        "promotion_harness_count": _positive_integer(
            item["promotion_harness_count"], "promotion harness count"
        ),
        "secret_scan_count": _positive_integer(
            item["secret_scan_count"], "secret scan count"
        ),
    }


def _validate_release_review(value: object) -> dict[str, Any]:
    item = _mapping(value, "release review")
    _exact_keys(
        item,
        {"checks", "evidence_sha256"},
        "release review",
    )
    checks = _true_map(
        item["checks"],
        expected=RELEASE_REVIEW_CHECKS,
        label="release review checks",
    )
    return {
        "check_count": len(checks),
        "evidence_sha256": _digest(
            item["evidence_sha256"], "release review evidence"
        ),
    }


def _validate_residue(value: object) -> dict[str, int]:
    item = dict(_mapping(value, "operator review residue"))
    expected = {**{name: 0 for name in RESIDUE_KEYS}, "total": 0}
    if item != expected:
        raise OperatorReleaseResultError(
            "operator release review retained residue"
        )
    return expected


def _validate_evidence_hashes(value: object) -> dict[str, str]:
    item = _mapping(value, "operator release evidence hashes")
    _exact_keys(item, set(EVIDENCE_HASH_NAMES), "operator release evidence hashes")
    return {
        name: _digest(item[name], f"operator release evidence {name}")
        for name in EVIDENCE_HASH_NAMES
    }


def _validate_evidence(
    value: object,
    *,
    prerequisites: Mapping[str, str],
    artifact: Mapping[str, Any],
    kolla: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = _mapping(value, "operator release evidence")
    _exact_keys(
        evidence,
        {
            "adr_review",
            "documentation",
            "evidence_sha256",
            "execution",
            "prerequisites",
            "release_review",
            "repository_verification",
            "residue",
            "schema",
            "source",
            "supply_chain",
        },
        "operator release evidence",
    )
    if (
        evidence["schema"] != EVIDENCE_SCHEMA
        or evidence["prerequisites"] != prerequisites
        or evidence["source"] != review_source_hashes()
    ):
        raise OperatorReleaseResultError(
            "operator release evidence binding changed"
        )
    return {
        "adr_review": _validate_adr_review(evidence["adr_review"]),
        "documentation": _validate_documentation(
            evidence["documentation"]
        ),
        "evidence_sha256": _validate_evidence_hashes(
            evidence["evidence_sha256"]
        ),
        "execution": _validate_execution(
            evidence["execution"],
            artifact=artifact,
            kolla=kolla,
        ),
        "release_review": _validate_release_review(
            evidence["release_review"]
        ),
        "repository_verification": _validate_repository(
            evidence["repository_verification"]
        ),
        "residue": _validate_residue(evidence["residue"]),
        "supply_chain": _validate_supply_chain(
            evidence["supply_chain"]
        ),
    }


def compile_result(
    *,
    release_readiness: object,
    release_digest: str,
    artifact_result: object,
    artifact_digest: str,
    rgw_kms_result: object,
    rgw_kms_digest: str,
    maintenance_result: object,
    maintenance_digest: str,
    data_protection_result: object,
    data_protection_digest: str,
    observability_result: object,
    observability_digest: str,
    gc_result: object,
    gc_digest: str,
    load_soak_result: object,
    load_soak_digest: str,
    kolla_multinode_result: object,
    kolla_multinode_digest: str,
    evidence: object,
    evidence_digest: str,
) -> dict[str, Any]:
    prerequisites, _, artifact, kolla = _qualified_prerequisites(
        release_readiness=release_readiness,
        release_digest=release_digest,
        artifact_result=artifact_result,
        artifact_digest=artifact_digest,
        rgw_kms_result=rgw_kms_result,
        rgw_kms_digest=rgw_kms_digest,
        maintenance_result=maintenance_result,
        maintenance_digest=maintenance_digest,
        data_protection_result=data_protection_result,
        data_protection_digest=data_protection_digest,
        observability_result=observability_result,
        observability_digest=observability_digest,
        gc_result=gc_result,
        gc_digest=gc_digest,
        load_soak_result=load_soak_result,
        load_soak_digest=load_soak_digest,
        kolla_multinode_result=kolla_multinode_result,
        kolla_multinode_digest=kolla_multinode_digest,
    )
    validated = _validate_evidence(
        evidence,
        prerequisites=prerequisites,
        artifact=artifact,
        kolla=kolla,
    )
    return {
        **validated,
        "input_evidence_sha256": _digest(
            evidence_digest, "operator release input evidence"
        ),
        "prerequisites": prerequisites,
        "production_candidate": True,
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "operator release result"))
    expected = {
        "adr_review",
        "documentation",
        "evidence_sha256",
        "execution",
        "input_evidence_sha256",
        "prerequisites",
        "production_candidate",
        "release_review",
        "repository_verification",
        "residue",
        "schema",
        "source",
        "supply_chain",
    }
    _exact_keys(result, expected, "operator release result")
    if (
        result["schema"] != SCHEMA
        or result["production_candidate"] is not True
        or result["source"] != source_hashes()
    ):
        raise OperatorReleaseResultError(
            "operator release result is not qualified"
        )
    prerequisites = _mapping(
        result["prerequisites"], "operator release prerequisites"
    )
    expected_prerequisites = {
        "artifact_result_sha256",
        "data_protection_result_sha256",
        "gc_retention_result_sha256",
        "kolla_multinode_result_sha256",
        "load_soak_result_sha256",
        "maintenance_identity_result_sha256",
        "observability_result_sha256",
        "release_readiness_sha256",
        "rgw_kms_result_sha256",
    }
    _exact_keys(
        prerequisites,
        expected_prerequisites,
        "operator release prerequisites",
    )
    for name in expected_prerequisites:
        _digest(prerequisites[name], f"operator prerequisite {name}")
    _digest(
        result["input_evidence_sha256"],
        "operator release input evidence",
    )
    execution = _mapping(result["execution"], "operator execution summary")
    _exact_keys(
        execution,
        {
            "adapter",
            "independent_reviewer_count",
            "release_revision",
            "review_duration_seconds",
            "reviewer_count",
            "tag",
            "version",
        },
        "operator execution summary",
    )
    if (
        execution["adapter"] != "independent-review"
        or execution["version"] != project_version()
        or execution["tag"] != f"v{project_version()}"
        or execution["reviewer_count"] < 2
        or execution["independent_reviewer_count"] < 1
        or execution["independent_reviewer_count"]
        >= execution["reviewer_count"]
    ):
        raise OperatorReleaseResultError(
            "operator execution summary is incomplete"
        )
    _revision(execution["release_revision"], "release revision")
    _positive_integer(
        execution["review_duration_seconds"], "operator review duration"
    )
    adr = _mapping(result["adr_review"], "ADR review summary")
    if (
        set(adr)
        != {
            "dispositions_sha256",
            "evidence_sha256",
            "reviewed_count",
            "unresolved_count",
        }
        or adr["reviewed_count"] < 1
        or adr["unresolved_count"] != 0
    ):
        raise OperatorReleaseResultError("ADR review summary is incomplete")
    _digest(adr["dispositions_sha256"], "ADR dispositions")
    _digest(adr["evidence_sha256"], "ADR evidence")
    documentation = _mapping(
        result["documentation"], "documentation summary"
    )
    if (
        set(documentation)
        != {
            "check_count",
            "evidence_sha256",
            "release_notes_sha256",
            "reviewed_document_count",
        }
        or documentation["check_count"] != len(DOCUMENTATION_CHECKS)
        or documentation["reviewed_document_count"] < 1
    ):
        raise OperatorReleaseResultError(
            "documentation summary is incomplete"
        )
    _digest(documentation["evidence_sha256"], "documentation evidence")
    _digest(documentation["release_notes_sha256"], "release notes")
    repository = _mapping(
        result["repository_verification"],
        "repository verification summary",
    )
    if (
        repository.get("check_count") != len(REPOSITORY_CHECKS)
        or set(repository)
        != {
            "check_count",
            "evidence_sha256",
            "full_regression_count",
            "kolla_lifecycle_count",
            "promotion_harness_count",
            "secret_scan_count",
        }
    ):
        raise OperatorReleaseResultError(
            "repository verification summary is incomplete"
        )
    for name in (
        "full_regression_count",
        "kolla_lifecycle_count",
        "promotion_harness_count",
        "secret_scan_count",
    ):
        _positive_integer(repository[name], name)
    _digest(repository["evidence_sha256"], "repository evidence")
    supply_chain = _mapping(
        result["supply_chain"], "supply-chain summary"
    )
    if (
        supply_chain.get("check_count") != len(SUPPLY_CHAIN_CHECKS)
        or supply_chain.get("critical_findings") != 0
        or supply_chain.get("high_findings") != 0
    ):
        raise OperatorReleaseResultError(
            "supply-chain summary is incomplete"
        )
    expected_supply_fields = {
        "check_count",
        "critical_findings",
        "evidence_sha256",
        "high_findings",
        "image_signature_bundle_sha256",
        "provenance_bundle_sha256",
        "sbom_bundle_sha256",
        "source_archive_sha256",
        "vulnerability_bundle_sha256",
    }
    _exact_keys(supply_chain, expected_supply_fields, "supply-chain summary")
    for name in expected_supply_fields - {
        "check_count",
        "critical_findings",
        "high_findings",
    }:
        _digest(supply_chain[name], f"supply-chain {name}")
    release_review = _mapping(
        result["release_review"], "release review summary"
    )
    if (
        release_review.get("check_count") != len(RELEASE_REVIEW_CHECKS)
        or set(release_review) != {"check_count", "evidence_sha256"}
    ):
        raise OperatorReleaseResultError(
            "release review summary is incomplete"
        )
    _digest(release_review["evidence_sha256"], "release review evidence")
    _validate_evidence_hashes(result["evidence_sha256"])
    _validate_residue(result["residue"])
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
            raise OperatorReleaseResultError(
                f"{label} ownership is unsafe"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > 32 * 1024 * 1024:
            raise OperatorReleaseResultError(f"{label} size is invalid")
        value = json.loads(payload)
    except OperatorReleaseResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OperatorReleaseResultError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise OperatorReleaseResultError(
            f"{label} must be a JSON object"
        )
    return value, _sha256_bytes(payload)


def _load_prerequisite(
    path: Path, label: str
) -> tuple[dict[str, Any], str]:
    try:
        return _load_private(path, label)
    except OperatorReleaseResultError as error:
        raise OperatorReleaseInputsBlocked(
            f"{label} is absent or unsafe"
        ) from error


def _write_private(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise OperatorReleaseResultError("output path must be absolute")
    if path.exists() or path.is_symlink():
        raise OperatorReleaseResultError("output path already exists")
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise OperatorReleaseResultError(
            "output directory ownership is unsafe"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
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
        raise OperatorReleaseResultError(
            "unable to write operator release result"
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the final operator, ADR, documentation, supply-chain, "
            "repository, and release review only after the first nine "
            "production-promotion gates qualify."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--artifact-result", type=Path, required=True)
    parser.add_argument("--rgw-kms-result", type=Path, required=True)
    parser.add_argument("--maintenance-identity-result", type=Path, required=True)
    parser.add_argument("--data-protection-result", type=Path, required=True)
    parser.add_argument("--observability-result", type=Path, required=True)
    parser.add_argument("--gc-retention-result", type=Path, required=True)
    parser.add_argument("--load-soak-result", type=Path, required=True)
    parser.add_argument("--kolla-multinode-result", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness, "release readiness"
        )
        try:
            RGW_KMS_RESULT.require_release_qualified(release)
        except RGW_KMS_RESULT.RgwKmsInputsBlocked as error:
            raise OperatorReleaseInputsBlocked(str(error)) from error
        inputs: dict[str, object] = {
            "release_digest": release_digest,
            "release_readiness": release,
        }
        for argument, label, value_name, digest_name in (
            (
                arguments.artifact_result,
                "artifact specialist result",
                "artifact_result",
                "artifact_digest",
            ),
            (
                arguments.rgw_kms_result,
                "RGW/KMS specialist result",
                "rgw_kms_result",
                "rgw_kms_digest",
            ),
            (
                arguments.maintenance_identity_result,
                "maintenance identity specialist result",
                "maintenance_result",
                "maintenance_digest",
            ),
            (
                arguments.data_protection_result,
                "data-protection specialist result",
                "data_protection_result",
                "data_protection_digest",
            ),
            (
                arguments.observability_result,
                "observability specialist result",
                "observability_result",
                "observability_digest",
            ),
            (
                arguments.gc_retention_result,
                "GC retention specialist result",
                "gc_result",
                "gc_digest",
            ),
            (
                arguments.load_soak_result,
                "load/soak specialist result",
                "load_soak_result",
                "load_soak_digest",
            ),
            (
                arguments.kolla_multinode_result,
                "Kolla multinode specialist result",
                "kolla_multinode_result",
                "kolla_multinode_digest",
            ),
        ):
            loaded, digest = _load_prerequisite(argument, label)
            inputs[value_name] = loaded
            inputs[digest_name] = digest
        prerequisites, _, _, _ = _qualified_prerequisites(**inputs)
        evidence, evidence_digest = _load_private(
            arguments.evidence, "operator release evidence"
        )
        if evidence.get("prerequisites") != prerequisites:
            raise OperatorReleaseResultError(
                "operator release evidence prerequisite binding changed"
            )
        result = compile_result(
            **inputs,
            evidence=evidence,
            evidence_digest=evidence_digest,
        )
        _write_private(arguments.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except OperatorReleaseInputsBlocked as error:
        print(f"operator release gate blocked: {error}", file=sys.stderr)
        return 3
    except OperatorReleaseResultError as error:
        print(f"operator release result error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
