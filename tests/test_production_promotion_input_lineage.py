from __future__ import annotations

import base64
import importlib.util
import json
import stat
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "production-promotion"
SOURCE = HARNESS / "input_lineage.py"
FIXTURES = HARNESS / "fixtures" / "v2"
POLICY_SOURCE = HARNESS / "trust-policy-v2.json"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_input_lineage",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
lineage = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lineage
SPEC.loader.exec_module(lineage)
trust = lineage.TRUST

TODAY = date(2026, 7, 28)
EXPIRES = "2026-08-04"


@dataclass
class Keys:
    qualification: Ed25519PrivateKey
    input_evidence: Ed25519PrivateKey
    lifecycle: Ed25519PrivateKey
    migration_checkpoint: Ed25519PrivateKey
    release: Ed25519PrivateKey
    rollback_authorization: Ed25519PrivateKey
    patch_owner: Ed25519PrivateKey
    builder_a: Ed25519PrivateKey
    builder_b: Ed25519PrivateKey
    vex: Ed25519PrivateKey
    reviewer: Ed25519PrivateKey
    scope: Ed25519PrivateKey
    scope_evidence: Ed25519PrivateKey
    storage_provider: Ed25519PrivateKey
    writer_fence: Ed25519PrivateKey


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def authority(
    key_id: str,
    private_key: Ed25519PrivateKey,
    role: str,
    *,
    input_classes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "components": list(lineage.COMPONENTS),
        "input_classes": (
            list(lineage.INPUT_CLASSES) if input_classes is None else input_classes
        ),
        "key_id": key_id,
        "not_after": "2027-01-31",
        "not_before": "2026-07-01",
        "operator_id": f"operator-{key_id}",
        "public_key": public_key(private_key),
        "revoked_on": None,
        "roles": [role],
        "scopes": [],
        "trust_domain": f"domain-{key_id}",
    }


def keys() -> Keys:
    return Keys(
        qualification=Ed25519PrivateKey.generate(),
        input_evidence=Ed25519PrivateKey.generate(),
        lifecycle=Ed25519PrivateKey.generate(),
        migration_checkpoint=Ed25519PrivateKey.generate(),
        release=Ed25519PrivateKey.generate(),
        rollback_authorization=Ed25519PrivateKey.generate(),
        patch_owner=Ed25519PrivateKey.generate(),
        builder_a=Ed25519PrivateKey.generate(),
        builder_b=Ed25519PrivateKey.generate(),
        vex=Ed25519PrivateKey.generate(),
        reviewer=Ed25519PrivateKey.generate(),
        scope=Ed25519PrivateKey.generate(),
        scope_evidence=Ed25519PrivateKey.generate(),
        storage_provider=Ed25519PrivateKey.generate(),
        writer_fence=Ed25519PrivateKey.generate(),
    )


def synthetic_policy(
    signing_keys: Keys,
    *,
    environment: str = "synthetic",
) -> dict[str, Any]:
    policy = json.loads(POLICY_SOURCE.read_text())
    policy["environment"] = environment
    policy["authorities"] = [
        authority(
            "fixture-builder-a",
            signing_keys.builder_a,
            "builder",
        ),
        authority(
            "fixture-builder-b",
            signing_keys.builder_b,
            "builder",
        ),
        authority(
            "fixture-qualification",
            signing_keys.qualification,
            "input-qualification",
        ),
        authority(
            "fixture-input-evidence",
            signing_keys.input_evidence,
            "input-evidence",
        ),
        authority(
            "fixture-lifecycle-observer",
            signing_keys.lifecycle,
            "lifecycle-observer",
        ),
        authority(
            "fixture-migration-checkpoint",
            signing_keys.migration_checkpoint,
            "migration-checkpoint",
        ),
        authority(
            "fixture-release-verifier",
            signing_keys.release,
            "release-verification",
        ),
        authority(
            "fixture-rollback-authorization",
            signing_keys.rollback_authorization,
            "rollback-authorization",
        ),
        authority(
            "fixture-patch-owner",
            signing_keys.patch_owner,
            "patch-owner",
            input_classes=["coffer-minimal-patch"],
        ),
        authority(
            "fixture-reviewer",
            signing_keys.reviewer,
            "security-review",
            input_classes=["coffer-minimal-patch"],
        ),
        {
            **authority(
                "fixture-scope",
                signing_keys.scope,
                "scope-qualification",
            ),
            "scopes": list(trust.SCOPES),
        },
        authority(
            "fixture-storage-provider",
            signing_keys.storage_provider,
            "storage-provider",
        ),
        authority("fixture-vex", signing_keys.vex, "vex"),
        authority(
            "fixture-writer-fence",
            signing_keys.writer_fence,
            "writer-fence",
        ),
    ]
    policy["release_verification_adapters"] = {
        "fixture-release-adapter": {
            "authority_key_id": "fixture-release-verifier",
            "components": list(lineage.COMPONENTS),
            "input_classes": list(lineage.INPUT_CLASSES),
            "name": "fixture-release-verifier",
            "output_schema": lineage.RELEASE_VERIFICATION_PREDICATE_SCHEMA,
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "6" * 40,
            "source_sha256": f"sha256:{'9' * 64}",
            "trust_root_sha256": f"sha256:{'a' * 64}",
            "valid_from": "2026-07-01",
            "valid_until": "2027-01-31",
        }
    }
    policy["input_evidence_adapters"] = {
        "fixture-input-evidence-adapter": {
            "authority_key_id": "fixture-input-evidence",
            "built_artifact_sha256": f"sha256:{'b' * 64}",
            "components": list(lineage.COMPONENTS),
            "input_classes": list(lineage.INPUT_CLASSES),
            "output_schema": lineage.INPUT_EVIDENCE_PREDICATE_SCHEMA,
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "7" * 40,
            "source_sha256": f"sha256:{'c' * 64}",
            "valid_from": "2026-07-01",
            "valid_until": "2027-01-31",
        }
    }
    policy["lifecycle_observation_adapters"] = {
        "fixture-lifecycle-observer": {
            "authority_key_id": "fixture-lifecycle-observer",
            "built_artifact_sha256": f"sha256:{'1' * 64}",
            "components": list(lineage.COMPONENTS),
            "input_classes": list(lineage.INPUT_CLASSES),
            "output_schema": (
                "coffer.production-lifecycle-observation-predicate/v2"
            ),
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "9" * 40,
            "source_sha256": f"sha256:{'2' * 64}",
            "valid_from": "2026-07-01",
            "valid_until": "2027-01-31",
        }
    }
    policy["writer_fence_adapters"] = {
        "fixture-shared-cas-fence": {
            "authority_key_id": "fixture-writer-fence",
            "built_artifact_sha256": f"sha256:{'d' * 64}",
            "lease_namespace": "fixture-coffer-rollbacks",
            "output_schema": (
                "coffer.production-writer-fence-predicate/v2"
            ),
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "8" * 40,
            "source_sha256": f"sha256:{'e' * 64}",
            "state_backend": "shared-cas-lease",
            "valid_from": "2026-07-01",
            "valid_until": "2027-01-31",
        }
    }
    official = fixture("official-upstream.json")
    coffer = fixture("coffer-minimal-patch.json")
    vendor = fixture("vendor-backport.json")
    distribution = policy["components"]["distribution"]
    distribution["release_signing_identities"] = ["fixture-upstream"]
    distribution["official_releases"] = {
        official["upstream"]["tag"]: {
            "revision": official["upstream"]["revision"],
            "source_sha256": official["upstream"]["source_sha256"],
            "support_ends_on": official["upstream"]["support_ends_on"],
        }
    }
    distribution["accepted_patch_bases"] = {
        coffer["upstream"]["tag"]: {
            "revision": coffer["upstream"]["revision"],
            "source_sha256": coffer["upstream"]["source_sha256"],
            "support_ends_on": coffer["upstream"]["support_ends_on"],
        }
    }
    distribution["latest_supported_patch_base"] = coffer["upstream"]["tag"]
    policy["coffer"]["release_signing_identities"] = ["fixture-coffer"]
    policy["coffer"]["builder_operator_ids"] = [
        "operator-fixture-builder-a"
    ]
    policy["coffer"]["patch_releases"] = {
        coffer["release"]["version"]: {
            "admitted_on": coffer["coffer_maintenance"]["released_on"],
            "component": coffer["component"],
            "owner_authority_key_id": "fixture-patch-owner",
            "release_revision": coffer["release"]["revision"],
            "release_source_sha256": coffer["release"]["source_sha256"],
            "release_tag": coffer["release"]["tag"],
            "replacement": None,
            "retire_on": coffer["support"]["declared_ends_on"],
            "support_ends_on": coffer["support"]["declared_ends_on"],
            "upstream_revision": coffer["upstream"]["revision"],
            "upstream_source_sha256": coffer["upstream"]["source_sha256"],
            "upstream_tag": coffer["upstream"]["tag"],
        }
    }
    policy["vendors"] = [
        {
            "advisory_origins": ["https://vendor.example/advisories"],
            "components": ["ceph"],
            "provider_id": "example-vendor",
            "release_signing_identities": ["fixture-vendor"],
            "releases": {
                vendor["release"]["version"]: {
                    "component": "ceph",
                    "repository": vendor["provider"]["repository"],
                    "revision": vendor["release"]["revision"],
                    "source_sha256": vendor["release"]["source_sha256"],
                    "support_ends_on": vendor["provider"]["support_ends_on"],
                    "upstream_revision": vendor["upstream"]["revision"],
                    "upstream_source_sha256": vendor["upstream"]["source_sha256"],
                    "upstream_tag": vendor["upstream"]["tag"],
                    "tag": vendor["release"]["tag"],
                }
            },
            "repositories": [vendor["provider"]["repository"]],
        }
    ]
    return policy


def configure_replacement(
    policy: dict[str, Any],
    *,
    qualified_on: str,
    retire_on: str,
) -> None:
    coffer = fixture("coffer-minimal-patch.json")
    distribution = policy["components"]["distribution"]
    old_base = deepcopy(
        distribution["accepted_patch_bases"][coffer["upstream"]["tag"]]
    )
    old_base["revision"] = "e" * 40
    old_base["source_sha256"] = f"sha256:{'f' * 64}"
    distribution["accepted_patch_bases"]["v3.2.0"] = old_base
    distribution["official_releases"]["v3.2.0"] = deepcopy(old_base)
    distribution["latest_supported_patch_base"] = "v3.2.0"
    patch = policy["coffer"]["patch_releases"][coffer["release"]["version"]]
    patch["replacement"] = {
        "input_class": "official-upstream",
        "provider_id": None,
        "qualified_on": qualified_on,
        "release_tag": "v3.2.0",
        "result_sha256": f"sha256:{'f' * 64}",
        "upstream_tag": "v3.2.0",
    }
    patch["retire_on"] = retire_on


def configure_vendor_replacement(
    policy: dict[str, Any],
    *,
    qualified_on: str,
    retire_on: str,
) -> None:
    coffer = fixture("coffer-minimal-patch.json")
    vendor = policy["vendors"][0]
    vendor["components"] = sorted(
        set(vendor["components"]) | {"distribution"}
    )
    repository = "https://vendor.example/distribution"
    vendor["repositories"] = sorted(
        set(vendor["repositories"]) | {repository}
    )
    vendor["releases"]["v3.1.1-vendor.1"] = {
        "component": "distribution",
        "repository": repository,
        "revision": "3" * 40,
        "source_sha256": f"sha256:{'4' * 64}",
        "support_ends_on": "2027-12-31",
        "tag": "v3.1.1-vendor.1",
        "upstream_revision": coffer["upstream"]["revision"],
        "upstream_source_sha256": coffer["upstream"]["source_sha256"],
        "upstream_tag": coffer["upstream"]["tag"],
    }
    patch = policy["coffer"]["patch_releases"][
        coffer["release"]["version"]
    ]
    patch["replacement"] = {
        "input_class": "approved-vendor-backport",
        "provider_id": vendor["provider_id"],
        "qualified_on": qualified_on,
        "release_tag": "v3.1.1-vendor.1",
        "result_sha256": f"sha256:{'5' * 64}",
        "upstream_tag": coffer["upstream"]["tag"],
    }
    patch["retire_on"] = retire_on


def sign(
    predicate: dict[str, Any],
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    role: str,
    predicate_type: str,
    subjects: dict[str, str],
) -> dict[str, Any]:
    attestation: dict[str, Any] = {
        "algorithm": "ed25519",
        "expires_on": EXPIRES,
        "issued_on": TODAY.isoformat(),
        "key_id": key_id,
        "predicate": predicate,
        "predicate_type": predicate_type,
        "role": role,
        "schema": trust.ATTESTATION_SCHEMA,
        "subjects": dict(sorted(subjects.items())),
    }
    attestation["signature"] = base64.b64encode(
        private_key.sign(trust.canonical_bytes(attestation))
    ).decode()
    return attestation


def resign(
    attestation: dict[str, Any],
    private_key: Ed25519PrivateKey,
) -> None:
    attestation["signature"] = base64.b64encode(
        private_key.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in attestation.items()
                    if key != "signature"
                }
            )
        )
    ).decode()


def write_json(path: Path, value: object, *, private: bool = False) -> None:
    path.write_bytes(trust.canonical_bytes(value) + b"\n")
    if private:
        path.chmod(0o600)


def policy_file(
    tmp_path: Path,
    policy: dict[str, Any],
) -> tuple[Path, dict[str, Any], str]:
    path = tmp_path / "policy.json"
    write_json(path, policy)
    parsed, digest = trust.load_policy(
        path,
        today=TODAY,
        allow_synthetic=True,
    )
    return path, parsed, digest


def loaded(tmp_path: Path, name: str, value: object) -> Any:
    path = tmp_path / name
    write_json(path, value, private=True)
    return trust.load_private_json(path, name)


def release_verification(
    manifest: dict[str, Any],
    input_class: str,
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    if input_class == "official-upstream":
        identity = "fixture-upstream"
    elif input_class == "approved-vendor-backport":
        identity = "fixture-vendor"
    else:
        identity = "fixture-coffer"
    release = manifest["release"]
    parsed_lineage = lineage.validate_manifest(
        manifest,
        policy=policy,
        today=TODAY,
    )
    signed_subjects = {
        "provenance-statement": provenance["statement_sha256"],
        "release-source": release["source_sha256"],
        **lineage._subject_map(parsed_lineage),
    }
    predicate = {
        "adapter_id": "fixture-release-adapter",
        "draft": False,
        "prerelease": False,
        "repository": release["repository"],
        "revision": release["revision"],
        "schema": lineage.RELEASE_VERIFICATION_PREDICATE_SCHEMA,
        "signature_bundle_sha256": f"sha256:{'8' * 64}",
        "signing_identity": identity,
        "signed_subjects": dict(sorted(signed_subjects.items())),
        "source_sha256": release["source_sha256"],
        "tag": release["tag"],
    }
    adapter = policy["release_verification_adapters"]["fixture-release-adapter"]
    return sign(
        predicate,
        private_key=signing_keys.release,
        key_id="fixture-release-verifier",
        role="release-verification",
        predicate_type=policy["predicate_types"]["release_verification"],
        subjects={
            "release-subjects": trust.canonical_sha256(signed_subjects),
            "signature-bundle": predicate["signature_bundle_sha256"],
            "verification-adapter": trust.canonical_sha256(adapter),
        },
    )


def builder_attestations(
    manifest: dict[str, Any],
    parsed_lineage: dict[str, Any],
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    policy_digest: str,
) -> list[dict[str, Any]]:
    lineage_digest = trust.canonical_sha256(manifest)
    materials = lineage._materials(parsed_lineage)
    materials_digest = trust.canonical_sha256(materials)
    quorum = 1 if manifest["input_class"] == "official-upstream" else 2
    key_specs = [
        ("fixture-builder-a", signing_keys.builder_a),
        ("fixture-builder-b", signing_keys.builder_b),
    ][:quorum]
    result: list[dict[str, Any]] = []
    for architecture in manifest["artifacts"]["architectures"]:
        outputs = {
            "artifact_sha256": architecture["artifact_sha256"],
            "image_sha256": architecture["image_sha256"],
            "sbom_sha256": architecture["sbom_sha256"],
        }
        subjects = {
            "artifact": architecture["artifact_sha256"],
            "image": architecture["image_sha256"],
            "lineage": lineage_digest,
            "materials": materials_digest,
            "sbom": architecture["sbom_sha256"],
        }
        predicate = {
            "architecture": architecture["name"],
            "lineage_sha256": lineage_digest,
            "materials": materials,
            "outputs": outputs,
            "policy_sha256": policy_digest,
            "schema": lineage.BUILDER_PREDICATE_SCHEMA,
        }
        for key_id, private_key in key_specs:
            result.append(
                sign(
                    predicate,
                    private_key=private_key,
                    key_id=key_id,
                    role="builder",
                    predicate_type=policy["predicate_types"]["builder"],
                    subjects=subjects,
                )
            )
    return result


def scanner_inventory(
    parsed_lineage: dict[str, Any],
    *,
    finding: dict[str, str] | None = None,
    findings: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if finding is not None and findings is not None:
        raise ValueError("use either finding or findings")
    requested_findings = findings if findings is not None else (
        [finding] if finding is not None else []
    )
    products = lineage._product_map(parsed_lineage)
    result: list[dict[str, Any]] = []
    expanded: list[dict[str, Any]] = []
    for scanner in lineage.SCANNERS:
        database = f"sha256:{'b' * 64}" if scanner == "scout" else f"sha256:{'c' * 64}"
        for subject_name, subject_digest in products.items():
            subject_findings: list[dict[str, str]] = []
            for requested in requested_findings:
                if (
                    requested["scanner"] != scanner
                    or requested["subject_name"] != subject_name
                ):
                    continue
                item = {
                    "id": requested["id"],
                    "purl": requested["purl"],
                    "severity": requested["severity"],
                    "subject_sha256": subject_digest,
                }
                subject_findings.append(item)
                expanded.append(
                    {
                        "database_sha256": database,
                        "id": requested["id"],
                        "purl": requested["purl"],
                        "scanner": scanner,
                        "severity": requested["severity"],
                        "subject_name": subject_name,
                        "subject_sha256": subject_digest,
                    }
                )
            subject_findings.sort(
                key=lambda item: (item["id"], item["purl"], item["severity"])
            )
            result.append(
                {
                    "critical_high_complete": True,
                    "database_sha256": database,
                    "findings": subject_findings,
                    "observed_on": TODAY.isoformat(),
                    "report_sha256": (
                        trust.canonical_sha256(
                            {
                                "findings": subject_findings,
                                "scanner": scanner,
                                "subject": subject_digest,
                            }
                        )
                    ),
                    "scanner": scanner,
                    "subject_name": subject_name,
                    "subject_sha256": subject_digest,
                    "version": "fixture-1.0.0",
                }
            )
    return result, expanded


def input_evidence_attestation(
    manifest: dict[str, Any],
    parsed_lineage: dict[str, Any],
    inventory: list[dict[str, Any]],
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    policy_digest: str,
    failed_check: str | None = None,
) -> dict[str, Any]:
    lineage_digest = trust.canonical_sha256(manifest)
    evidence = {
        name: trust.canonical_sha256(
            {"component": manifest["component"], "evidence": name}
        )
        for name in lineage.EVIDENCE_KEYS
    }
    predicate = {
        "adapter_id": "fixture-input-evidence-adapter",
        "checks": {
            name: name != failed_check
            for name in lineage.CHECKS[manifest["component"]]
        },
        "evidence": evidence,
        "lineage_sha256": lineage_digest,
        "observed_on": TODAY.isoformat(),
        "policy_sha256": policy_digest,
        "residue": {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        },
        "scanner_inventory": inventory,
        "schema": lineage.INPUT_EVIDENCE_PREDICATE_SCHEMA,
        "valid_until": EXPIRES,
    }
    adapter = policy["input_evidence_adapters"]["fixture-input-evidence-adapter"]
    return sign(
        predicate,
        private_key=signing_keys.input_evidence,
        key_id="fixture-input-evidence",
        role="input-evidence",
        predicate_type=policy["predicate_types"]["input_evidence"],
        subjects={
            "adapter": trust.canonical_sha256(adapter),
            "lineage": lineage_digest,
            **lineage._subject_map(parsed_lineage),
            **{f"evidence:{name}": digest for name, digest in sorted(evidence.items())},
            "scanner-inventory": trust.canonical_sha256(inventory),
        },
    )


def lifecycle_attestation(
    manifest: dict[str, Any],
    parsed_lineage: dict[str, Any],
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    policy_digest: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage_digest = trust.canonical_sha256(manifest)
    adapter_id = "fixture-lifecycle-observer"
    adapter = policy["lifecycle_observation_adapters"][adapter_id]
    replacement = (
        None
        if parsed_lineage["coffer_patch_policy"] is None
        else parsed_lineage["coffer_patch_policy"]["replacement"]
    )
    predicate = {
        "adapter_id": adapter_id,
        "advisory_active": True,
        "lineage_sha256": lineage_digest,
        "new_reachable_critical_high": [],
        "observed_on": TODAY.isoformat(),
        "policy_sha256": policy_digest,
        "provider_support_ends_on": (
            parsed_lineage["provider"]["support_ends_on"].isoformat()
            if parsed_lineage["provider"] is not None
            else parsed_lineage["upstream"]["support_ends_on"].isoformat()
        ),
        "replacement": replacement,
        "schema": lineage.LIFECYCLE_OBSERVATION_PREDICATE_SCHEMA,
        "signer_active": True,
        "submission": parsed_lineage["upstream_submission"],
        "valid_until": EXPIRES,
    }
    if overrides is not None:
        predicate.update(overrides)
    return sign(
        predicate,
        private_key=signing_keys.lifecycle,
        key_id="fixture-lifecycle-observer",
        role="lifecycle-observer",
        predicate_type=policy["predicate_types"]["lifecycle_observation"],
        subjects={
            "adapter": trust.canonical_sha256(adapter),
            "lineage": lineage_digest,
            "replacement": trust.canonical_sha256(replacement),
            "submission-baseline": trust.canonical_sha256(
                parsed_lineage["upstream_submission"]
            ),
            "submission-observation": trust.canonical_sha256(
                predicate["submission"]
            ),
        },
    )


def vex_attestations(
    findings: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    policy_digest: str,
    status: str = "not_affected",
) -> list[dict[str, Any]]:
    lineage_digest = trust.canonical_sha256(manifest)
    result: list[dict[str, Any]] = []
    for finding in findings:
        if status == "not_affected":
            not_affected: dict[str, Any] | None = {
                "binary_reachability_sha256": f"sha256:{'d' * 64}",
                "justification": "vulnerable_code_not_in_execute_path",
                "source_reachability_sha256": f"sha256:{'e' * 64}",
            }
            fixed = None
            under_investigation = None
        elif status == "fixed":
            not_affected = None
            fixed = {
                "fixed_artifact_sha256": finding["subject_sha256"],
                "post_fix_verification_sha256": f"sha256:{'d' * 64}",
                "remediation_revision": "f" * 40,
            }
            under_investigation = None
        else:
            not_affected = None
            fixed = None
            under_investigation = {
                "analysis_sha256": f"sha256:{'d' * 64}",
                "due_on": "2026-08-04",
                "owner": "fixture-vulnerability-owner",
            }
        predicate = {
            "cve": finding["id"],
            "expires_on": "2027-01-31",
            "fixed": fixed,
            "issued_on": TODAY.isoformat(),
            "lineage_sha256": lineage_digest,
            "not_affected": not_affected,
            "openvex_context": "https://openvex.dev/ns/v0.2.0",
            "policy_sha256": policy_digest,
            "product_sha256": finding["subject_sha256"],
            "purl": finding["purl"],
            "scanner": finding["scanner"],
            "scanner_database_sha256": finding["database_sha256"],
            "schema": lineage.VEX_PREDICATE_SCHEMA,
            "status": status,
            "under_investigation": under_investigation,
        }
        subjects = {
            "finding": trust.canonical_sha256(finding),
            "lineage": lineage_digest,
            "product": finding["subject_sha256"],
        }
        result.append(
            sign(
                predicate,
                private_key=signing_keys.vex,
                key_id="fixture-vex",
                role="vex",
                predicate_type=policy["predicate_types"]["vex"],
                subjects=subjects,
            )
        )
    return result


def patch_review(
    manifest: dict[str, Any],
    *,
    signing_keys: Keys,
    policy_digest: str,
) -> dict[str, Any] | None:
    if manifest["input_class"] != "coffer-minimal-patch":
        return None
    lineage_digest = trust.canonical_sha256(manifest)
    patch_series = trust.canonical_sha256(
        [
            {
                "blocker_id": patch["blocker_id"],
                "id": patch["id"],
                "sha256": patch["sha256"],
            }
            for patch in manifest["patches"]
        ]
    )
    maintenance = manifest["coffer_maintenance"]
    predicate = {
        "lineage_sha256": lineage_digest,
        "owner_key_id": maintenance["owner_key_id"],
        "patches": [
            {
                "blocker_id": patch["blocker_id"],
                "changed_paths_sha256": patch["changed_paths_sha256"],
                "id": patch["id"],
                "sha256": patch["sha256"],
            }
            for patch in manifest["patches"]
        ],
        "policy_sha256": policy_digest,
        "reviewed_on": TODAY.isoformat(),
        "schema": lineage.PATCH_REVIEW_PREDICATE_SCHEMA,
        "scope_checks": maintenance["scope_checks"],
    }
    return sign(
        predicate,
        private_key=signing_keys.reviewer,
        key_id="fixture-reviewer",
        role="security-review",
        predicate_type=("https://coffer.invalid/attestations/patch-review/v2"),
        subjects={
            "changed-tree": maintenance["changed_tree_sha256"],
            "lineage": lineage_digest,
            "patch-series": patch_series,
        },
    )


def qualification_attestation(
    manifest: dict[str, Any],
    *,
    signing_keys: Keys,
    policy: dict[str, Any],
    policy_digest: str,
    finding: dict[str, str] | None = None,
    findings: list[dict[str, str]] | None = None,
    failed_check: str | None = None,
    vex_status: str = "not_affected",
    vex_limit: int | None = None,
    lifecycle_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_lineage = lineage.validate_manifest(
        manifest,
        policy=policy,
        today=TODAY,
    )
    lineage_digest = trust.canonical_sha256(manifest)
    inventory, expanded_findings = scanner_inventory(
        parsed_lineage,
        finding=finding,
        findings=findings,
    )
    provenance = {
        "materials": lineage._materials(parsed_lineage),
        "predicate_type": "https://slsa.dev/provenance/v1",
        "statement_sha256": f"sha256:{'7' * 64}",
        "subjects": lineage._product_map(parsed_lineage),
    }
    predicate = {
        "builders": builder_attestations(
            manifest,
            parsed_lineage,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
        ),
        "component": manifest["component"],
        "evidence_attestation": input_evidence_attestation(
            manifest,
            parsed_lineage,
            inventory,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
            failed_check=failed_check,
        ),
        "lifecycle_attestation": lifecycle_attestation(
            manifest,
            parsed_lineage,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
            overrides=lifecycle_overrides,
        ),
        "lineage_sha256": lineage_digest,
        "patch_review": patch_review(
            manifest,
            signing_keys=signing_keys,
            policy_digest=policy_digest,
        ),
        "policy_sha256": policy_digest,
        "provenance": provenance,
        "release": release_verification(
            manifest,
            manifest["input_class"],
            signing_keys=signing_keys,
            policy=policy,
            provenance=provenance,
        ),
        "schema": lineage.QUALIFICATION_PREDICATE_SCHEMA,
        "vex": vex_attestations(
            expanded_findings,
            manifest,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
            status=vex_status,
        )[:vex_limit],
    }
    return sign(
        predicate,
        private_key=signing_keys.qualification,
        key_id="fixture-qualification",
        role="input-qualification",
        predicate_type=policy["predicate_types"]["input_qualification"],
        subjects={
            "lineage": lineage_digest,
            **lineage._subject_map(parsed_lineage),
        },
    )


def compile_fixture(
    tmp_path: Path,
    name: str,
    *,
    environment: str = "synthetic",
    finding: dict[str, str] | None = None,
    findings: list[dict[str, str]] | None = None,
    failed_check: str | None = None,
    vex_status: str = "not_affected",
    vex_limit: int | None = None,
    lifecycle_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path, dict[str, Any], Keys]:
    signing_keys = keys()
    policy_value = synthetic_policy(
        signing_keys,
        environment=environment,
    )
    policy_path, parsed_policy, policy_digest = policy_file(
        tmp_path,
        policy_value,
    )
    manifest = fixture(name)
    manifest["fixture_only"] = environment == "synthetic"
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=parsed_policy,
        policy_digest=policy_digest,
        finding=finding,
        findings=findings,
        failed_check=failed_check,
        vex_status=vex_status,
        vex_limit=vex_limit,
        lifecycle_overrides=lifecycle_overrides,
    )
    result = lineage.compile_test_result(
        manifest=loaded(tmp_path, "manifest.json", manifest),
        qualification=loaded(
            tmp_path,
            "qualification.json",
            qualification,
        ),
        policy_path=policy_path,
        today=TODAY,
        allow_synthetic_policy=environment == "synthetic",
    )
    return result, policy_path, manifest, signing_keys


@pytest.mark.parametrize(
    ("name", "expected_class", "expected_component", "patch_count"),
    (
        (
            "official-upstream.json",
            "official-upstream",
            "distribution",
            0,
        ),
        (
            "vendor-backport.json",
            "approved-vendor-backport",
            "ceph",
            1,
        ),
        (
            "coffer-minimal-patch.json",
            "coffer-minimal-patch",
            "distribution",
            1,
        ),
    ),
)
def test_signed_synthetic_fixtures_cover_all_lineage_classes_but_never_produce(
    tmp_path: Path,
    name: str,
    expected_class: str,
    expected_component: str,
    patch_count: int,
) -> None:
    result, policy_path, _, _ = compile_fixture(tmp_path, name)

    assert result["derived"]["status"] == "synthetic-qualified"
    assert result["derived"]["production_input"] is False
    assert result["derived"]["input_class"] == expected_class
    assert result["derived"]["component"] == expected_component
    assert result["derived"]["patch_count"] == patch_count
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )
        == result
    )
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_final_result(result)


def test_ephemeral_production_policy_proves_real_path_without_onboarding_key(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
    )

    assert result["derived"]["status"] == "qualified"
    assert result["derived"]["production_input"] is True
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
        )
        == result
    )
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_final_result(result)


def test_checked_in_production_policy_rejects_fixture_and_has_no_trust_root(
    tmp_path: Path,
) -> None:
    manifest = fixture("official-upstream.json")
    empty = loaded(tmp_path, "empty.json", {})

    with pytest.raises(
        lineage.InputLineageError,
        match="fixture lineage",
    ):
        lineage.compile_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=empty,
        )


def test_unsigned_all_true_caller_document_is_not_an_attestation(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_path, _, _ = policy_file(
        tmp_path,
        synthetic_policy(signing_keys),
    )
    manifest = fixture("official-upstream.json")
    caller_document = {
        "adapter": "qualification-pipeline",
        "checks": {"runtime": True},
        "non_synthetic": True,
    }

    with pytest.raises(lineage.InputLineageError):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "caller.json",
                caller_document,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_signature_and_embedded_bundle_tampering_are_rejected(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
    )
    tampered = deepcopy(result)
    tampered["bundle"]["qualification"]["predicate"]["release"]["predicate"][
        "repository"
    ] = "https://attacker.example/repository"
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )

    tampered = deepcopy(result)
    tampered["derived"]["status"] = "qualified"
    tampered["derived"]["production_input"] = True
    with pytest.raises(
        lineage.InputLineageError,
        match="was not derived",
    ):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_outer_qualification_cannot_reauthorize_changed_input_evidence(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
    )
    tampered = deepcopy(result)
    qualification = tampered["bundle"]["qualification"]
    qualification["predicate"]["evidence_attestation"]["predicate"]["evidence"][
        "runtime_sha256"
    ] = f"sha256:{'0' * 64}"
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()

    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_signed_negative_input_evidence_derives_blocked_status(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        failed_check="runtime",
    )

    assert result["derived"]["production_input"] is False
    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["reason_codes"] == ["input-check-failed:runtime"]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_outer_qualification_cannot_erase_signed_findings_or_vex(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
    )
    tampered = deepcopy(result)
    qualification = tampered["bundle"]["qualification"]
    qualification["predicate"]["vex"] = []
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()

    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


@pytest.mark.parametrize(
    "adapter_name",
    (
        "release_verification_adapters",
        "input_evidence_adapters",
        "lifecycle_observation_adapters",
    ),
)
def test_adapter_output_schema_is_exact(
    tmp_path: Path,
    adapter_name: str,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    adapter = next(iter(policy_value[adapter_name].values()))
    adapter["output_schema"] = "coffer.incompatible-output/v999"
    policy_path, parsed_policy, policy_digest = policy_file(
        tmp_path,
        policy_value,
    )
    manifest = fixture("official-upstream.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=parsed_policy,
        policy_digest=policy_digest,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match=(
            "adapter is not approved|verification is invalid|"
            "adapter is not allowlisted"
        ),
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_input_evidence_cannot_predate_adapter_approval(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_value["input_evidence_adapters"]["fixture-input-evidence-adapter"][
        "valid_from"
    ] = TODAY.isoformat()
    policy_path, parsed_policy, policy_digest = policy_file(
        tmp_path,
        policy_value,
    )
    manifest = fixture("official-upstream.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=parsed_policy,
        policy_digest=policy_digest,
    )
    evidence = qualification["predicate"]["evidence_attestation"]
    evidence["issued_on"] = "2026-07-27"
    evidence["predicate"]["observed_on"] = "2026-07-27"
    for item in evidence["predicate"]["scanner_inventory"]:
        item["observed_on"] = "2026-07-27"
    evidence["signature"] = base64.b64encode(
        signing_keys.input_evidence.sign(
            trust.canonical_bytes(
                {key: value for key, value in evidence.items() if key != "signature"}
            )
        )
    ).decode()
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()

    with pytest.raises(lineage.InputLineageError):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_lifecycle_attestation_cannot_predate_observation_or_outlive_adapter(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_value["lifecycle_observation_adapters"][
        "fixture-lifecycle-observer"
    ]["valid_until"] = "2026-08-03"
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("official-upstream.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
        lifecycle_overrides={"valid_until": "2026-08-03"},
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="not independently trusted",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )

    policy_value = synthetic_policy(signing_keys)
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )
    lifecycle_attestation_value = qualification["predicate"][
        "lifecycle_attestation"
    ]
    lifecycle_attestation_value["issued_on"] = "2026-07-27"
    lifecycle_attestation_value["expires_on"] = "2026-08-03"
    lifecycle_attestation_value["predicate"]["valid_until"] = "2026-08-03"
    lifecycle_attestation_value["signature"] = base64.b64encode(
        signing_keys.lifecycle.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in lifecycle_attestation_value.items()
                    if key != "signature"
                }
            )
        )
    ).decode()
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()
    with pytest.raises(
        lineage.InputLineageError,
        match="not independently trusted",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "predated-manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "predated-qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_opendev_review_submission_is_reachable_and_exact(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    _, policy, _ = policy_file(tmp_path, policy_value)
    review_url = (
        "https://review.opendev.org/c/openstack/oslo.messaging/+/12345"
    )
    raw_patch = deepcopy(fixture("coffer-minimal-patch.json")["patches"][0])
    raw_patch.update(
        {
            "blocker_id": "oslo-messaging-cve-2026-44393",
            "id": "oslo-messaging-cve-2026-44393",
            "kind": "security",
            "upstream_url": review_url,
        }
    )
    patches = lineage._patches(
        [raw_patch],
        component="oslo_messaging",
        upstream_repository=(
            "https://opendev.org/openstack/oslo.messaging"
        ),
        policy=policy,
    )
    submission = lineage._submission(
        {
            "items": [
                {
                    "patch_id": raw_patch["id"],
                    "revision": raw_patch["upstream_revision"],
                    "status": "open",
                    "url": review_url,
                }
            ],
            "required": True,
        },
        patches=patches,
        input_class="coffer-minimal-patch",
        upstream_repository=(
            "https://opendev.org/openstack/oslo.messaging"
        ),
    )

    assert submission["items"][0]["url"] == review_url


def test_builder_quorum_and_materials_are_cryptographically_bound(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "vendor-backport.json",
    )
    tampered = deepcopy(result)
    builders = tampered["bundle"]["qualification"]["predicate"]["builders"]
    builders.pop()
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )

    tampered = deepcopy(result)
    tampered["bundle"]["qualification"]["predicate"]["builders"][0]["predicate"][
        "materials"
    ]["toolchain_sha256"] = f"sha256:{'f' * 64}"
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_downstream_build_requires_a_designated_coffer_builder(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_value["coffer"]["builder_operator_ids"] = [
        "operator-designated-but-not-in-build"
    ]
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("vendor-backport.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="Coffer-operated independent rebuild is missing",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_complete_scanner_matrix_and_provided_vex_remain_signed(
    tmp_path: Path,
) -> None:
    finding = {
        "id": "CVE-2026-12345",
        "purl": "pkg:golang/example/module@1.0.0",
        "scanner": "trivy",
        "severity": "high",
        "subject_name": "amd64-image",
    }
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        finding=finding,
    )
    assert result["derived"]["vex_count"] == 1

    tampered = deepcopy(result)
    tampered["bundle"]["qualification"]["predicate"]["evidence_attestation"][
        "predicate"
    ]["scanner_inventory"].pop()
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )

    tampered = deepcopy(result)
    tampered["bundle"]["qualification"]["predicate"]["vex"] = []
    with pytest.raises(lineage.InputLineageError):
        lineage.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_scanner_finding_without_vex_is_an_explicit_blocker(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
        vex_limit=0,
    )

    assert result["derived"]["vex_count"] == 0
    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["production_input"] is False
    assert result["derived"]["reason_codes"] == [
        "unresolved-finding:CVE-2026-12345:amd64-image"
    ]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_partial_vex_subset_preserves_each_unmatched_finding_as_blocked(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        findings=[
            {
                "id": "CVE-2026-12345",
                "purl": "pkg:golang/example/module@1.0.0",
                "scanner": "trivy",
                "severity": "high",
                "subject_name": "amd64-image",
            },
            {
                "id": "CVE-2026-22345",
                "purl": "pkg:golang/example/other@1.0.0",
                "scanner": "trivy",
                "severity": "critical",
                "subject_name": "amd64-image",
            },
        ],
        vex_limit=1,
    )

    assert result["derived"]["vex_count"] == 1
    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["reason_codes"] == [
        "unresolved-finding:CVE-2026-22345:amd64-image"
    ]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


@pytest.mark.parametrize("status", ("fixed", "not_affected"))
def test_exact_fixed_and_not_affected_openvex_paths(
    tmp_path: Path,
    status: str,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "scout",
            "severity": "critical",
            "subject_name": "arm64-artifact",
        },
        vex_status=status,
    )
    vex = result["bundle"]["qualification"]["predicate"]["vex"][0]
    assert vex["predicate"]["status"] == status
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )
        == result
    )


def test_under_investigation_openvex_is_preserved_as_blocked(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
        vex_status="under_investigation",
    )

    assert result["derived"]["production_input"] is False
    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["reason_codes"] == [
        "unresolved-finding:CVE-2026-12345:amd64-image"
    ]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_expired_signed_vex_is_preserved_as_current_blocker(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
    )
    qualification = result["bundle"]["qualification"]
    vex = qualification["predicate"]["vex"][0]
    vex["predicate"]["issued_on"] = "2026-07-20"
    vex["predicate"]["expires_on"] = "2026-07-27"
    resign(vex, signing_keys.vex)
    resign(qualification, signing_keys.qualification)
    policy, policy_digest = trust.load_policy(
        policy_path,
        today=TODAY,
    )
    rebuilt = lineage._derive(
        manifest_value=result["bundle"]["lineage"],
        qualification_value=qualification,
        policy=policy,
        policy_sha256=policy_digest,
        today=TODAY,
    )

    assert rebuilt["derived"]["status"] == "blocked"
    assert rebuilt["derived"]["reason_codes"] == [
        "expired-vex:CVE-2026-12345:amd64-image"
    ]


def test_expired_outer_vex_attestation_is_preserved_as_current_blocker(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
    )
    qualification = result["bundle"]["qualification"]
    vex = qualification["predicate"]["vex"][0]
    vex["issued_on"] = "2026-07-20"
    vex["expires_on"] = "2026-07-27"
    vex["predicate"]["issued_on"] = "2026-07-20"
    resign(vex, signing_keys.vex)
    resign(qualification, signing_keys.qualification)
    policy, policy_digest = trust.load_policy(
        policy_path,
        today=TODAY,
    )
    rebuilt = lineage._derive(
        manifest_value=result["bundle"]["lineage"],
        qualification_value=qualification,
        policy=policy,
        policy_sha256=policy_digest,
        today=TODAY,
    )

    assert rebuilt["derived"]["status"] == "blocked"
    assert rebuilt["derived"]["reason_codes"] == [
        "expired-vex:CVE-2026-12345:amd64-image"
    ]


def test_overdue_investigation_is_preserved_as_current_blocker(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
        vex_status="under_investigation",
    )
    qualification = result["bundle"]["qualification"]
    vex = qualification["predicate"]["vex"][0]
    vex["predicate"]["under_investigation"]["due_on"] = "2026-07-27"
    resign(vex, signing_keys.vex)
    resign(qualification, signing_keys.qualification)
    policy, policy_digest = trust.load_policy(
        policy_path,
        today=TODAY,
    )
    rebuilt = lineage._derive(
        manifest_value=result["bundle"]["lineage"],
        qualification_value=qualification,
        policy=policy,
        policy_sha256=policy_digest,
        today=TODAY,
    )

    assert rebuilt["derived"]["status"] == "blocked"
    assert rebuilt["derived"]["reason_codes"] == [
        "overdue-investigation:CVE-2026-12345:amd64-image",
        "unresolved-finding:CVE-2026-12345:amd64-image",
    ]


def test_vex_attestation_cannot_predate_its_predicate(
    tmp_path: Path,
) -> None:
    result, policy_path, _, signing_keys = compile_fixture(
        tmp_path,
        "official-upstream.json",
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
    )
    qualification = result["bundle"]["qualification"]
    vex = qualification["predicate"]["vex"][0]
    vex["issued_on"] = "2026-07-27"
    vex["expires_on"] = "2026-08-03"
    resign(vex, signing_keys.vex)
    resign(qualification, signing_keys.qualification)

    with pytest.raises(
        lineage.InputLineageError,
        match="signed OpenVEX predicate is invalid",
    ):
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_vex_reviewer_is_independent_from_input_evidence_operator(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    evidence_authority = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-input-evidence"
    )
    vex_authority = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-vex"
    )
    vex_authority["operator_id"] = evidence_authority["operator_id"]
    vex_authority["trust_domain"] = evidence_authority["trust_domain"]
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("official-upstream.json")
    finding = {
        "id": "CVE-2026-12345",
        "purl": "pkg:golang/example/module@1.0.0",
        "scanner": "trivy",
        "severity": "high",
        "subject_name": "amd64-image",
    }
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
        finding=finding,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="OpenVEX predicate is invalid",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_lifecycle_observer_is_independent_from_patch_owner(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    owner = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-patch-owner"
    )
    observer = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-lifecycle-observer"
    )
    observer["operator_id"] = owner["operator_id"]
    observer["trust_domain"] = owner["trust_domain"]
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="lifecycle observation is not independently trusted",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_patch_reviewer_is_independent_from_named_patch_owner(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    owner = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-patch-owner"
    )
    reviewer = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-reviewer"
    )
    reviewer["operator_id"] = owner["operator_id"]
    reviewer["trust_domain"] = owner["trust_domain"]
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="independent patch review is invalid",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_patch_review_attestation_cannot_predate_review(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )
    review = qualification["predicate"]["patch_review"]
    review["issued_on"] = "2026-07-27"
    review["expires_on"] = "2026-08-03"
    review["signature"] = base64.b64encode(
        signing_keys.reviewer.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in review.items()
                    if key != "signature"
                }
            )
        )
    ).decode()
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()

    with pytest.raises(
        lineage.InputLineageError,
        match="independent patch review is invalid",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_lifecycle_observer_preserves_later_rejection_as_blocked(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys, environment="production")
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    manifest["fixture_only"] = False
    current_submission = deepcopy(manifest["upstream_submission"])
    current_submission["items"][0]["status"] = "rejected"
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
        lifecycle_overrides={"submission": current_submission},
    )

    result = lineage.compile_test_result(
        manifest=loaded(tmp_path, "manifest.json", manifest),
        qualification=loaded(
            tmp_path,
            "qualification.json",
            qualification,
        ),
        policy_path=policy_path,
        today=TODAY,
        allow_synthetic_policy=False,
    )
    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["reason_codes"] == [
        "upstream-submission-rejected:distribution-malformed-reference"
    ]


def test_lifecycle_observer_and_patch_reviewer_are_pairwise_independent(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    observer = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-lifecycle-observer"
    )
    reviewer = next(
        item
        for item in policy_value["authorities"]
        if item["key_id"] == "fixture-reviewer"
    )
    reviewer["operator_id"] = observer["operator_id"]
    reviewer["trust_domain"] = observer["trust_domain"]
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )

    with pytest.raises(
        lineage.InputLineageError,
        match="observer and patch reviewer are not independent",
    ):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "manifest.json", manifest),
            qualification=loaded(
                tmp_path,
                "qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    (
        (
            {"signer_active": False},
            "retirement-signer-revoked",
        ),
        (
            {"advisory_active": False},
            "retirement-advisory-withdrawn",
        ),
        (
            {
                "new_reachable_critical_high": [
                    {
                        "evidence_sha256": f"sha256:{'f' * 64}",
                        "id": "CVE-2026-99999",
                    }
                ]
            },
            "retirement-new-reachable:CVE-2026-99999",
        ),
    ),
)
def test_signed_lifecycle_negative_is_preserved_as_blocked(
    tmp_path: Path,
    overrides: dict[str, Any],
    reason_code: str,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        lifecycle_overrides=overrides,
    )

    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["production_input"] is False
    assert result["derived"]["reason_codes"] == [reason_code]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_observed_shorter_provider_support_is_current_blocked_evidence(
    tmp_path: Path,
) -> None:
    result, policy_path, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
        lifecycle_overrides={
            "provider_support_ends_on": "2026-12-31"
        },
    )

    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["production_input"] is False
    assert result["derived"]["effective_support_ends_on"] == "2026-12-31"
    assert result["derived"]["reason_codes"] == [
        "provider-support-shortened"
    ]
    assert (
        lineage.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_manifest_support_eol_and_repository_port_are_policy_controlled(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    _, policy, _ = policy_file(tmp_path, policy_value)

    changed_eol = fixture("official-upstream.json")
    changed_eol["support"]["coffer_release_ends_on"] = "2026-12-31"
    changed_eol["support"]["declared_ends_on"] = "2026-12-31"
    with pytest.raises(lineage.InputLineageError, match="support window"):
        lineage.validate_manifest(changed_eol, policy=policy, today=TODAY)

    nonstandard_port = fixture("official-upstream.json")
    nonstandard_port["upstream"][
        "repository"
    ] = "https://github.com:8443/distribution/distribution"
    nonstandard_port["release"]["repository"] = nonstandard_port["upstream"][
        "repository"
    ]
    with pytest.raises(lineage.InputLineageError, match="repository is invalid"):
        lineage.validate_manifest(
            nonstandard_port,
            policy=policy,
            today=TODAY,
        )


def test_vendor_and_coffer_policy_catalogs_are_exact(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_path, parsed, policy_digest = policy_file(tmp_path, policy_value)
    vendor = fixture("vendor-backport.json")
    vendor["provider"]["repository"] = "https://attacker.example/ceph"
    with pytest.raises(
        lineage.InputLineageError,
        match="allowlisted",
    ):
        lineage.validate_manifest(vendor, policy=parsed, today=TODAY)

    for traversal in (
        "https://vendor.example/advisories/../untrusted",
        "https://vendor.example/advisories/%2e%2e/untrusted",
        "https://vendor.example/advisories/%2F..%2Funtrusted",
        "https://vendor.example/advisories/foo\\..\\..\\untrusted",
    ):
        vendor = fixture("vendor-backport.json")
        vendor["provider"]["advisory_url"] = traversal
        with pytest.raises(
            lineage.InputLineageError,
            match="invalid|allowlisted",
        ):
            lineage.validate_manifest(vendor, policy=parsed, today=TODAY)

    coffer = fixture("coffer-minimal-patch.json")
    coffer["patches"][0]["blocker_id"] = "unknown-blocker"
    with pytest.raises(
        lineage.InputLineageError,
        match="patch policy",
    ):
        lineage.validate_manifest(coffer, policy=parsed, today=TODAY)

    coffer = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        coffer,
        signing_keys=signing_keys,
        policy=parsed,
        policy_digest=policy_digest,
    )
    qualification["predicate"]["patch_review"] = None
    qualification["signature"] = base64.b64encode(
        signing_keys.qualification.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in qualification.items()
                    if key != "signature"
                }
            )
        )
    ).decode()
    with pytest.raises(lineage.InputLineageError):
        lineage.compile_test_result(
            manifest=loaded(tmp_path, "coffer.json", coffer),
            qualification=loaded(
                tmp_path,
                "coffer-qualification.json",
                qualification,
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


@pytest.mark.parametrize(
    "name",
    ("vendor-backport.json", "coffer-minimal-patch.json"),
)
def test_downstream_release_signature_binds_patched_products_and_provenance(
    tmp_path: Path,
    name: str,
) -> None:
    result, _, manifest, _ = compile_fixture(tmp_path, name)
    release = result["bundle"]["qualification"]["predicate"]["release"]["predicate"]

    assert release["revision"] == manifest["release"]["revision"]
    assert release["source_sha256"] == manifest["release"]["source_sha256"]
    assert release["source_sha256"] != manifest["upstream"]["source_sha256"]
    assert {
        "amd64-artifact",
        "amd64-image",
        "amd64-sbom",
        "arm64-artifact",
        "arm64-image",
        "arm64-sbom",
        "provenance-statement",
        "release-source",
        "source-bundle",
    } <= set(release["signed_subjects"])


def test_patch_submission_and_latest_base_are_exact(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_path, policy, _ = policy_file(tmp_path, policy_value)

    misleading = fixture("coffer-minimal-patch.json")
    misleading["upstream"]["version"] = "arbitrary-base-label"
    with pytest.raises(lineage.InputLineageError, match="upstream release"):
        lineage.validate_manifest(misleading, policy=policy, today=TODAY)

    commit_only = fixture("coffer-minimal-patch.json")
    commit_url = (
        "https://github.com/distribution/distribution/commit/"
        + commit_only["patches"][0]["upstream_revision"]
    )
    commit_only["patches"][0]["upstream_url"] = commit_url
    commit_only["upstream_submission"]["items"][0]["url"] = commit_url
    with pytest.raises(lineage.InputLineageError, match="exact upstream change"):
        lineage.validate_manifest(commit_only, policy=policy, today=TODAY)

    rejected = fixture("coffer-minimal-patch.json")
    rejected["upstream_submission"]["items"][0]["status"] = "rejected"
    with pytest.raises(lineage.InputLineageError, match="not active"):
        lineage.validate_manifest(rejected, policy=policy, today=TODAY)

    newer = deepcopy(policy_value["components"]["distribution"][
        "accepted_patch_bases"
    ][fixture("coffer-minimal-patch.json")["upstream"]["tag"]])
    policy_value["components"]["distribution"]["accepted_patch_bases"][
        "v3.2.0"
    ] = newer
    policy_value["components"]["distribution"][
        "latest_supported_patch_base"
    ] = "v3.2.0"
    latest_policy_path = tmp_path / "latest-policy.json"
    write_json(latest_policy_path, policy_value, private=True)
    with pytest.raises(
        trust.TrustPolicyError,
        match="Coffer patch release",
    ):
        trust.load_policy(
            latest_policy_path,
            today=TODAY,
            allow_synthetic=True,
        )

    assert policy_path.exists()


def test_policy_replacement_shortens_effective_support_without_immediate_rejection(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    configure_replacement(
        policy_value,
        qualified_on="2026-07-28",
        retire_on="2026-10-26",
    )
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    manifest = fixture("coffer-minimal-patch.json")
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
    )
    result = lineage.compile_test_result(
        manifest=loaded(tmp_path, "replacement-manifest.json", manifest),
        qualification=loaded(
            tmp_path,
            "replacement-qualification.json",
            qualification,
        ),
        policy_path=policy_path,
        today=TODAY,
        allow_synthetic_policy=True,
    )

    assert result["derived"]["effective_support_ends_on"] == "2026-10-26"
    assert result["derived"]["status"] == "synthetic-qualified"
    assert (
        result["bundle"]["qualification"]["predicate"][
            "lifecycle_attestation"
        ]["predicate"]["replacement"]
        == policy["coffer"]["patch_releases"][
            manifest["release"]["version"]
        ]["replacement"]
    )

    unlisted = deepcopy(manifest)
    unlisted["release"]["tag"] = "v3.1.1-coffer.2"
    unlisted["release"]["version"] = "v3.1.1-coffer.2"
    unlisted["release"]["revision"] = "1" * 40
    unlisted["release"]["source_sha256"] = f"sha256:{'0' * 64}"
    unlisted["artifacts"]["source_bundle_sha256"] = (
        unlisted["release"]["source_sha256"]
    )
    with pytest.raises(
        lineage.InputLineageError,
        match="Coffer patch lineage policy",
    ):
        lineage.validate_manifest(unlisted, policy=policy, today=TODAY)


def test_replacement_catalog_preserves_first_deadline_across_later_latest_base(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    configure_replacement(
        policy_value,
        qualified_on="2026-07-28",
        retire_on="2026-10-26",
    )
    next_base = deepcopy(
        policy_value["components"]["distribution"][
            "accepted_patch_bases"
        ]["v3.2.0"]
    )
    next_base["revision"] = "6" * 40
    next_base["source_sha256"] = f"sha256:{'7' * 64}"
    policy_value["components"]["distribution"][
        "accepted_patch_bases"
    ]["v3.3.0"] = next_base
    policy_value["components"]["distribution"][
        "latest_supported_patch_base"
    ] = "v3.3.0"

    _, policy, _ = policy_file(tmp_path, policy_value)
    replacement = policy["coffer"]["patch_releases"][
        "v3.1.1-coffer.1"
    ]["replacement"]
    assert replacement["upstream_tag"] == "v3.2.0"
    assert (
        policy["coffer"]["patch_releases"]["v3.1.1-coffer.1"][
            "retire_on"
        ]
        == "2026-10-26"
    )


def test_late_replacement_retirement_is_clipped_to_existing_support(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    policy_value["coffer"]["patch_releases"]["v3.1.1-coffer.1"][
        "support_ends_on"
    ] = "2026-08-15"
    configure_replacement(
        policy_value,
        qualified_on="2026-07-28",
        retire_on="2026-08-15",
    )

    _, policy, _ = policy_file(tmp_path, policy_value)
    assert (
        policy["coffer"]["patch_releases"]["v3.1.1-coffer.1"][
            "retire_on"
        ]
        == "2026-08-15"
    )


def test_vendor_replacement_can_share_upstream_base_but_binds_exact_release(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys)
    configure_vendor_replacement(
        policy_value,
        qualified_on="2026-07-28",
        retire_on="2026-10-26",
    )

    _, policy, _ = policy_file(tmp_path, policy_value)
    replacement = policy["coffer"]["patch_releases"][
        "v3.1.1-coffer.1"
    ]["replacement"]
    assert replacement == {
        "input_class": "approved-vendor-backport",
        "provider_id": "example-vendor",
        "qualified_on": "2026-07-28",
        "release_revision": "3" * 40,
        "release_source_sha256": f"sha256:{'4' * 64}",
        "release_tag": "v3.1.1-vendor.1",
        "result_sha256": f"sha256:{'5' * 64}",
        "upstream_revision": "a" * 40,
        "upstream_source_sha256": f"sha256:{'b' * 64}",
        "upstream_tag": "v3.1.1",
    }


def test_expired_replacement_grace_is_signed_blocked_evidence(
    tmp_path: Path,
) -> None:
    signing_keys = keys()
    policy_value = synthetic_policy(signing_keys, environment="production")
    manifest = fixture("coffer-minimal-patch.json")
    manifest["fixture_only"] = False
    manifest["coffer_maintenance"]["released_on"] = "2026-01-01"
    manifest["support"]["starts_on"] = "2026-01-01"
    manifest["support"]["declared_ends_on"] = "2027-01-01"
    policy_value["coffer"]["patch_releases"][
        manifest["release"]["version"]
    ]["admitted_on"] = "2026-01-01"
    policy_value["coffer"]["patch_releases"][
        manifest["release"]["version"]
    ]["support_ends_on"] = "2027-01-01"
    configure_replacement(
        policy_value,
        qualified_on="2026-04-28",
        retire_on="2026-07-27",
    )
    policy_path, policy, policy_digest = policy_file(tmp_path, policy_value)
    qualification = qualification_attestation(
        manifest,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
        finding={
            "id": "CVE-2026-12345",
            "purl": "pkg:golang/example/module@1.0.0",
            "scanner": "trivy",
            "severity": "high",
            "subject_name": "amd64-image",
        },
    )
    result = lineage.compile_test_result(
        manifest=loaded(tmp_path, "expired-manifest.json", manifest),
        qualification=loaded(
            tmp_path,
            "expired-qualification.json",
            qualification,
        ),
        policy_path=policy_path,
        today=TODAY,
        allow_synthetic_policy=False,
    )

    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["production_input"] is False
    assert result["derived"]["vex_count"] == 1
    assert result["derived"]["effective_support_ends_on"] == "2026-07-27"
    assert result["derived"]["reason_codes"] == [
        "replacement-grace-expired"
    ]


def test_calendar_twelve_month_limit_handles_leap_day() -> None:
    assert lineage._add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)


def test_compile_api_refuses_caller_supplied_objects_and_digests() -> None:
    with pytest.raises(
        lineage.InputLineageError,
        match="loaded document",
    ):
        lineage.compile_result(
            manifest={},
            qualification={},
        )
    with pytest.raises(TypeError):
        lineage.validate_final_result({}, today=TODAY)
    with pytest.raises(TypeError):
        lineage.validate_final_result({}, policy_path=Path("/tmp/attacker-policy.json"))


def test_cli_cannot_substitute_synthetic_policy_or_publish_fixture(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    manifest = fixture("official-upstream.json")
    manifest_path = tmp_path / "manifest.json"
    qualification_path = tmp_path / "qualification.json"
    output = tmp_path / "result.json"
    write_json(manifest_path, manifest, private=True)
    write_json(qualification_path, {}, private=True)

    assert (
        lineage.main(
            [
                "--manifest",
                str(manifest_path),
                "--qualification",
                str(qualification_path),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()


def test_owner_only_result_from_ephemeral_production_bundle(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    result, _, _, _ = compile_fixture(
        tmp_path,
        "official-upstream.json",
        environment="production",
    )
    output = tmp_path / "result.json"

    trust.write_owner_only(output, result)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text()) == result


def test_input_result_serialized_budget_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lineage, "INPUT_RESULT_MAX_BYTES", 1)
    with pytest.raises(
        lineage.InputLineageError,
        match="fixed budget",
    ):
        compile_fixture(tmp_path, "official-upstream.json")
