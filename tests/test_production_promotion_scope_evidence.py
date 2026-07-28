from __future__ import annotations

import base64
import importlib.util
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "production-promotion"
SOURCE = HARNESS / "scope_evidence.py"
INPUT_TEST_SOURCE = ROOT / "tests" / "test_production_promotion_input_lineage.py"


def load(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


scope = load("coffer_test_production_scope_evidence", SOURCE)
input_test = load("coffer_scope_input_fixture_helpers", INPUT_TEST_SOURCE)
trust = scope.TRUST
lineage = scope.INPUT_LINEAGE

TODAY = date(2026, 7, 28)
EXPIRES = "2026-08-04"
ADAPTER_ID = "fixture-scope-adapter"
BACKEND_ID = "fixture-ceph-rgw"


def oslo_manifest(environment: str) -> dict[str, Any]:
    manifest = input_test.fixture("official-upstream.json")
    manifest["component"] = "oslo_messaging"
    manifest["fixture_only"] = environment == "synthetic"
    manifest["upstream"] = {
        "repository": "https://opendev.org/openstack/oslo.messaging",
        "revision": "1" * 40,
        "source_sha256": f"sha256:{'7' * 64}",
        "support_ends_on": "2027-12-31",
        "tag": "17.4.0",
        "version": "17.4.0",
    }
    manifest["release"] = {
        "repository": manifest["upstream"]["repository"],
        "revision": manifest["upstream"]["revision"],
        "source_sha256": manifest["upstream"]["source_sha256"],
        "tag": manifest["upstream"]["tag"],
        "version": manifest["upstream"]["version"],
    }
    manifest["artifacts"]["source_bundle_sha256"] = manifest["release"][
        "source_sha256"
    ]
    return manifest


def add_oslo_policy(
    policy: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    component = policy["components"]["oslo_messaging"]
    component["release_signing_identities"] = ["fixture-upstream"]
    component["official_releases"] = {
        manifest["upstream"]["tag"]: {
            "revision": manifest["upstream"]["revision"],
            "source_sha256": manifest["upstream"]["source_sha256"],
            "support_ends_on": manifest["upstream"]["support_ends_on"],
        }
    }


def provider_manifests(
    scope_name: str,
    mode: str,
    *,
    environment: str,
) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    required = scope.provider_requirements(scope_name, mode)
    if "distribution" in required:
        manifests["distribution"] = input_test.fixture("official-upstream.json")
    if "ceph" in required:
        manifests["ceph"] = input_test.fixture("vendor-backport.json")
    if "oslo_messaging" in required:
        manifests["oslo_messaging"] = oslo_manifest(environment)
    for manifest in manifests.values():
        manifest["fixture_only"] = environment == "synthetic"
    return manifests


def backend_policy(
    provider_manifest: dict[str, Any],
    tested_distribution_manifest: dict[str, Any],
    *,
    support_ends_on: str = "2027-01-31",
) -> dict[str, Any]:
    return {
        "authority_key_id": "fixture-storage-provider",
        "backend_type": "s3-compatible",
        "driver_contract_sha256": f"sha256:{'1' * 64}",
        "provider_artifact_sha256": trust.canonical_sha256(
            provider_manifest["artifacts"]
        ),
        "provider_kind": "open-source",
        "provider_lineage_sha256": trust.canonical_sha256(provider_manifest),
        "provider_name": "ceph-rgw",
        "provider_revision": provider_manifest["release"]["revision"],
        "provider_source_sha256": provider_manifest["release"]["source_sha256"],
        "provider_version": provider_manifest["release"]["version"],
        "support_ends_on": support_ends_on,
        "tested_distribution_lineages_sha256": [
            trust.canonical_sha256(tested_distribution_manifest)
        ],
    }


def referrers(mode: str) -> dict[str, Any] | None:
    if mode == "fallback-tag":
        return {
            "advertised": True,
            "limitations": list(scope.FALLBACK_LIMITATIONS),
        }
    if mode == "native":
        return {"advertised": True, "limitations": []}
    if mode == "disabled":
        return {"advertised": False, "limitations": []}
    return None


def add_scope_policy(
    policy: dict[str, Any],
    *,
    scope_name: str,
    signing_keys: Any,
    provider_manifests: dict[str, dict[str, Any]],
    environment: str,
    same_trust_domain: bool = False,
    adapter_valid_from: str = "2026-07-01",
) -> None:
    evidence_authority = input_test.authority(
        "fixture-scope-evidence",
        signing_keys.scope_evidence,
        "scope-evidence",
    )
    evidence_authority["scopes"] = [scope_name]
    if same_trust_domain:
        evidence_authority["trust_domain"] = "domain-fixture-scope"
    policy["authorities"].append(evidence_authority)
    source_tree = scope.scope_source_tree_sha256(scope_name)
    policy["scope_evidence_adapters"] = {
        ADAPTER_ID: {
            "authority_key_id": "fixture-scope-evidence",
            "built_artifact_sha256": f"sha256:{'5' * 64}",
            "output_schema": scope.EVIDENCE_PREDICATE_SCHEMA,
            "repository": "https://github.com/jaehanbyun/coffer",
            "revision": "6" * 40,
            "scope_source_sha256": {scope_name: source_tree},
            "scopes": [scope_name],
            "valid_from": adapter_valid_from,
            "valid_until": "2027-01-31",
            "verifier_source_sha256": f"sha256:{'7' * 64}",
        }
    }
    if scope_name in {"rgw_barbican_kms", "storage_backend"}:
        provider_manifest = provider_manifests.get("ceph")
        if provider_manifest is None:
            provider_manifest = input_test.fixture("vendor-backport.json")
            provider_manifest["fixture_only"] = environment == "synthetic"
        distribution_manifest = provider_manifests.get("distribution")
        if distribution_manifest is None:
            distribution_manifest = input_test.fixture("official-upstream.json")
            distribution_manifest["fixture_only"] = environment == "synthetic"
        policy["storage_backends"] = {
            BACKEND_ID: backend_policy(
                provider_manifest,
                distribution_manifest,
            )
        }


def storage_attestation(
    *,
    signing_keys: Any,
    policy: dict[str, Any],
    policy_digest: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    backend = policy["storage_backends"][BACKEND_ID]
    predicate = {
        "backend_id": BACKEND_ID,
        "backend_sha256": trust.canonical_sha256(backend),
        "observed_on": TODAY.isoformat(),
        "policy_sha256": policy_digest,
        "schema": scope.STORAGE_PROVIDER_PREDICATE_SCHEMA,
        "valid_until": EXPIRES,
    }
    attestation = input_test.sign(
        predicate,
        private_key=signing_keys.storage_provider,
        key_id="fixture-storage-provider",
        role="storage-provider",
        predicate_type=policy["predicate_types"]["storage_provider"],
        subjects={
            "backend-catalog": predicate["backend_sha256"],
            "driver-contract": backend["driver_contract_sha256"],
            "provider-artifact": backend["provider_artifact_sha256"],
            "provider-lineage": backend["provider_lineage_sha256"],
            "provider-source": backend["provider_source_sha256"],
        },
    )
    normalized_backend = {
        "backend_id": BACKEND_ID,
        **backend,
        "provider_attestation_sha256": trust.canonical_sha256(attestation),
    }
    return attestation, normalized_backend


def compile_providers(
    tmp_path: Path,
    manifests: dict[str, dict[str, Any]],
    *,
    policy_path: Path,
    policy: dict[str, Any],
    policy_digest: str,
    signing_keys: Any,
    environment: str,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for component, manifest in manifests.items():
        qualification = input_test.qualification_attestation(
            manifest,
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
        )
        directory = tmp_path / f"input-{component}"
        directory.mkdir()
        manifest_path = directory / "manifest.json"
        qualification_path = directory / "qualification.json"
        input_test.write_json(manifest_path, manifest, private=True)
        input_test.write_json(
            qualification_path,
            qualification,
            private=True,
        )
        results[component] = lineage.compile_test_result(
            manifest=lineage.TRUST.load_private_json(
                manifest_path,
                "manifest.json",
            ),
            qualification=lineage.TRUST.load_private_json(
                qualification_path,
                "qualification.json",
            ),
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=environment == "synthetic",
        )
    return results


def provider_bindings(
    provider_inputs: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        component: {
            "input_class": result["derived"]["input_class"],
            "input_result_sha256": trust.canonical_sha256(result),
            "lineage_sha256": result["derived"]["lineage_sha256"],
            "policy_sha256": result["derived"]["policy_sha256"],
            "valid_until": result["derived"]["valid_until"],
        }
        for component, result in sorted(provider_inputs.items())
    }


def evidence_results(
    scope_name: str,
    mode: str,
    *,
    adapter: dict[str, Any],
    policy_digest: str,
    bindings: dict[str, Any],
    backend: dict[str, Any] | None,
    failed_result: str | None = None,
    observed_on: str = TODAY.isoformat(),
) -> dict[str, Any]:
    source_tree = scope.scope_source_tree_sha256(scope_name)
    subjects = {
        "adapter": trust.canonical_sha256(adapter),
        "policy": policy_digest,
        "provider-bindings": trust.canonical_sha256(bindings),
        "scope-source": source_tree,
    }
    if backend is not None:
        subjects["backend-lineage"] = trust.canonical_sha256(backend)
    names = scope.EVIDENCE_KEYS[scope_name]
    coverage = {name: [] for name in names}
    for index, check in enumerate(scope.CHECKS[(scope_name, mode)]):
        coverage[names[index % len(names)]].append(check)
    return {
        name: {
            "bundle_manifest_sha256": trust.canonical_sha256(
                {"evidence": name, "scope": scope_name}
            ),
            "checks": sorted(coverage[name]),
            "failure_codes": (
                ["explicit-negative-evidence"] if name == failed_result else []
            ),
            "observed_on": observed_on,
            "schema": scope._evidence_result_schema(scope_name, name),
            "source": {
                "adapter_id": ADAPTER_ID,
                "built_artifact_sha256": adapter["built_artifact_sha256"],
                "verifier_source_sha256": adapter["verifier_source_sha256"],
            },
            "status": "failed" if name == failed_result else "passed",
            "subjects": dict(sorted(subjects.items())),
            "valid_until": EXPIRES,
        }
        for name in names
    }


def attestations(
    scope_name: str,
    mode: str,
    providers: dict[str, dict[str, Any]],
    *,
    signing_keys: Any,
    policy: dict[str, Any],
    policy_digest: str,
    environment: str,
    failed_result: str | None = None,
    result_observed_on: str = TODAY.isoformat(),
) -> tuple[dict[str, Any], dict[str, Any]]:
    bindings = provider_bindings(providers)
    adapter = policy["scope_evidence_adapters"][ADAPTER_ID]
    if scope_name in {"rgw_barbican_kms", "storage_backend"}:
        backend_attestation, backend = storage_attestation(
            signing_keys=signing_keys,
            policy=policy,
            policy_digest=policy_digest,
        )
    else:
        backend_attestation, backend = None, None
    results = evidence_results(
        scope_name,
        mode,
        adapter=adapter,
        policy_digest=policy_digest,
        bindings=bindings,
        backend=backend,
        failed_result=failed_result,
        observed_on=result_observed_on,
    )
    source_tree = scope.scope_source_tree_sha256(scope_name)
    evidence_predicate = {
        "adapter_id": ADAPTER_ID,
        "backend_attestation": backend_attestation,
        "evidence_results": results,
        "fixture_only": environment == "synthetic",
        "mode": mode,
        "observed_on": TODAY.isoformat(),
        "policy_sha256": policy_digest,
        "provider_bindings": bindings,
        "referrers": referrers(mode) if scope_name == "referrers" else None,
        "residue": {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        },
        "schema": scope.EVIDENCE_PREDICATE_SCHEMA,
        "scope": scope_name,
        "source_tree_sha256": source_tree,
        "valid_until": EXPIRES,
    }
    evidence = input_test.sign(
        evidence_predicate,
        private_key=signing_keys.scope_evidence,
        key_id="fixture-scope-evidence",
        role="scope-evidence",
        predicate_type=policy["predicate_types"]["scope_evidence"],
        subjects=scope._evidence_subjects(
            adapter=adapter,
            policy_sha256=policy_digest,
            source_tree_sha256=source_tree,
            provider_bindings=bindings,
            backend=backend,
            results=results,
        ),
    )
    evidence_digest = trust.canonical_sha256(evidence)
    qualification_predicate = {
        "adapter_id": ADAPTER_ID,
        "evidence_attestation_sha256": evidence_digest,
        "mode": mode,
        "policy_sha256": policy_digest,
        "provider_bindings": bindings,
        "reviewed_on": TODAY.isoformat(),
        "schema": scope.QUALIFICATION_PREDICATE_SCHEMA,
        "scope": scope_name,
        "valid_until": EXPIRES,
    }
    subjects = {
        "adapter": trust.canonical_sha256(adapter),
        "policy": policy_digest,
        "scope-evidence": evidence_digest,
    }
    subjects.update(
        {
            f"provider:{component}": binding["input_result_sha256"]
            for component, binding in bindings.items()
        }
    )
    if backend is not None:
        subjects["backend-lineage"] = trust.canonical_sha256(backend)
    qualification = input_test.sign(
        qualification_predicate,
        private_key=signing_keys.scope,
        key_id="fixture-scope",
        role="scope-qualification",
        predicate_type=policy["predicate_types"]["scope_qualification"],
        subjects=dict(sorted(subjects.items())),
    )
    return evidence, qualification


def loaded(
    tmp_path: Path,
    name: str,
    value: object,
) -> Any:
    path = tmp_path / name
    input_test.write_json(path, value, private=True)
    return scope.TRUST.load_private_json(path, name)


def compile_scope(
    tmp_path: Path,
    scope_name: str,
    mode: str,
    *,
    environment: str = "synthetic",
    same_trust_domain: bool = False,
    backend_overrides: dict[str, Any] | None = None,
    failed_result: str | None = None,
    adapter_valid_from: str = "2026-07-01",
    result_observed_on: str = TODAY.isoformat(),
) -> tuple[dict[str, Any], Path, Any]:
    signing_keys = input_test.keys()
    policy_value = input_test.synthetic_policy(
        signing_keys,
        environment=environment,
    )
    manifests = provider_manifests(scope_name, mode, environment=environment)
    if "oslo_messaging" in manifests:
        add_oslo_policy(policy_value, manifests["oslo_messaging"])
    add_scope_policy(
        policy_value,
        scope_name=scope_name,
        signing_keys=signing_keys,
        provider_manifests=manifests,
        environment=environment,
        same_trust_domain=same_trust_domain,
        adapter_valid_from=adapter_valid_from,
    )
    if backend_overrides is not None:
        policy_value["storage_backends"][BACKEND_ID].update(backend_overrides)
    policy_path, policy, policy_digest = input_test.policy_file(
        tmp_path,
        policy_value,
    )
    providers = compile_providers(
        tmp_path,
        manifests,
        policy_path=policy_path,
        policy=policy,
        policy_digest=policy_digest,
        signing_keys=signing_keys,
        environment=environment,
    )
    evidence, qualification = attestations(
        scope_name,
        mode,
        providers,
        signing_keys=signing_keys,
        policy=policy,
        policy_digest=policy_digest,
        environment=environment,
        failed_result=failed_result,
        result_observed_on=result_observed_on,
    )
    provider_documents = {
        component: loaded(tmp_path, f"{component}-result.json", result)
        for component, result in providers.items()
    }
    result = scope.compile_test_result(
        evidence_attestation=loaded(
            tmp_path,
            "evidence-attestation.json",
            evidence,
        ),
        qualification_attestation=loaded(
            tmp_path,
            "qualification-attestation.json",
            qualification,
        ),
        provider_inputs=provider_documents,
        policy_path=policy_path,
        today=TODAY,
        allow_synthetic_policy=environment == "synthetic",
    )
    return result, policy_path, signing_keys


@pytest.mark.parametrize(
    ("scope_name", "mode"),
    (
        ("registry_core", "core"),
        ("storage_backend", "s3-compatible"),
        ("rgw_barbican_kms", "rgw-barbican-sse-kms"),
        ("horizon", "horizon"),
        ("skyline", "skyline"),
        ("referrers", "native"),
        ("referrers", "fallback-tag"),
        ("referrers", "disabled"),
    ),
)
def test_signed_synthetic_scope_matrix_is_never_production_ready(
    tmp_path: Path,
    scope_name: str,
    mode: str,
) -> None:
    result, policy_path, _ = compile_scope(tmp_path, scope_name, mode)

    expected = (
        "synthetic-disabled"
        if (scope_name, mode) == ("referrers", "disabled")
        else "synthetic-qualified"
    )
    assert result["derived"]["scope"] == scope_name
    assert result["derived"]["mode"] == mode
    assert result["derived"]["production_ready"] is False
    assert result["derived"]["status"] == expected
    assert (
        scope.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )
        == result
    )
    with pytest.raises(scope.ScopeEvidenceError):
        scope.validate_final_result(result)


@pytest.mark.parametrize(
    ("scope_name", "mode", "expected_status", "ready"),
    (
        ("registry_core", "core", "qualified", True),
        ("storage_backend", "s3-compatible", "qualified", True),
        ("referrers", "disabled", "disabled", False),
    ),
)
def test_ephemeral_production_scope_path_is_derived_and_fixed_policy_rejects_it(
    tmp_path: Path,
    scope_name: str,
    mode: str,
    expected_status: str,
    ready: bool,
) -> None:
    result, policy_path, _ = compile_scope(
        tmp_path,
        scope_name,
        mode,
        environment="production",
    )

    assert result["derived"]["status"] == expected_status
    assert result["derived"]["production_ready"] is ready
    assert (
        scope.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )
    with pytest.raises(scope.ScopeEvidenceError):
        scope.validate_final_result(result)


def test_signed_negative_scope_evidence_derives_blocked_status(
    tmp_path: Path,
) -> None:
    result, policy_path, _ = compile_scope(
        tmp_path,
        "registry_core",
        "core",
        environment="production",
        failed_result="artifacts",
    )

    assert result["derived"]["status"] == "blocked"
    assert result["derived"]["production_ready"] is False
    assert result["derived"]["reason_codes"] == [
        "evidence:artifacts:explicit-negative-evidence"
    ]
    assert (
        scope.validate_test_result(
            result,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=False,
        )
        == result
    )


def test_provider_requirements_are_local_and_storage_is_driver_scoped() -> None:
    assert scope.provider_requirements("registry_core", "core") == ("distribution",)
    assert scope.provider_requirements("storage_backend", "s3-compatible") == ()
    assert scope.provider_requirements("horizon", "horizon") == ("oslo_messaging",)
    assert scope.provider_requirements(
        "rgw_barbican_kms",
        "rgw-barbican-sse-kms",
    ) == ("ceph", "distribution")
    assert scope.provider_requirements("referrers", "disabled") == ()


def test_scope_signature_result_and_provider_tampering_are_rejected(
    tmp_path: Path,
) -> None:
    result, policy_path, _ = compile_scope(tmp_path, "registry_core", "core")
    tampered = deepcopy(result)
    tampered["bundle"]["evidence_attestation"]["predicate"]["evidence_results"]["gc"][
        "bundle_manifest_sha256"
    ] = f"sha256:{'f' * 64}"
    with pytest.raises(scope.ScopeEvidenceError):
        scope.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )

    tampered = deepcopy(result)
    provider = tampered["bundle"]["provider_inputs"]["distribution"]
    provider["derived"]["production_input"] = True
    with pytest.raises(scope.ScopeEvidenceError):
        scope.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_missing_or_duplicate_check_coverage_is_rejected(tmp_path: Path) -> None:
    result, policy_path, signing_keys = compile_scope(
        tmp_path,
        "registry_core",
        "core",
    )
    tampered = deepcopy(result)
    evidence = tampered["bundle"]["evidence_attestation"]
    evidence["predicate"]["evidence_results"]["gc"]["checks"] = []
    evidence["signature"] = base64.b64encode(
        signing_keys.scope_evidence.sign(
            trust.canonical_bytes(
                {key: value for key, value in evidence.items() if key != "signature"}
            )
        )
    ).decode()
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="fixed checks",
    ):
        scope.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_scope_source_manifest_is_tracked_surgical_and_complete() -> None:
    horizon = {
        path.relative_to(ROOT).as_posix()
        for path in scope._tracked_source_files(scope.SOURCE_PATHS["horizon"])
    }
    skyline = {
        path.relative_to(ROOT).as_posix()
        for path in scope._tracked_source_files(scope.SOURCE_PATHS["skyline"])
    }
    core = {
        path.relative_to(ROOT).as_posix()
        for path in scope._tracked_source_files(scope.SOURCE_PATHS["registry_core"])
    }
    storage = {
        path.relative_to(ROOT).as_posix()
        for path in scope._tracked_source_files(scope.SOURCE_PATHS["storage_backend"])
    }
    kms = {
        path.relative_to(ROOT).as_posix()
        for path in scope._tracked_source_files(scope.SOURCE_PATHS["rgw_barbican_kms"])
    }

    assert "ui/horizon/Makefile" in horizon
    assert "ui/horizon/uv.lock" in horizon
    assert any(path.endswith(".html") for path in horizon)
    assert any(path.endswith(".scss") for path in horizon)
    assert "ui/skyline/patches/0001-coffer-registry.patch" in skyline
    assert any(path.endswith(".less") for path in skyline)
    assert "ansible/KOLLA_ANSIBLE_COMMIT" in horizon
    assert "ansible/coffer.yml" in horizon
    assert "ansible/roles/coffer/tasks/main.yml" in skyline
    assert "pyproject.toml" in core
    assert "requirements/production-constraints.txt" in core
    assert {
        "ansible/roles/coffer/tasks/bootstrap_service.yml",
        "ansible/roles/coffer/tasks/check-containers.yml",
        "ansible/roles/coffer/tasks/maintenance-precheck.yml",
        "ansible/roles/coffer/tasks/validate_config.yml",
        "docker/config/coffer-registry.json.j2",
        "src/coffer/db.py",
        "src/coffer/migrations/versions/0007_artifact_projection.py",
        "src/coffer/quota.py",
        "src/coffer/schema.py",
        "src/coffer/tokens.py",
    } <= storage
    assert {
        "ansible/roles/coffer/tasks/config.yml",
        "docker/config/coffer-registry.json.j2",
    } <= kms
    assert "poc/load-soak/collector/rgw_live_adapter.py" in kms
    assert "poc/load-soak/collector/rgw_cleanup.py" in kms
    assert all("/.venv/" not in path and "/build/" not in path for path in horizon)
    assert not any(path.endswith("ui-skyline-proxy.yml") for path in horizon)


@pytest.mark.parametrize(
    ("scope_name", "relative_path"),
    (
        ("storage_backend", "src/coffer/schema.py"),
        ("rgw_barbican_kms", "docker/config/coffer-registry.json.j2"),
    ),
)
def test_runtime_source_drift_invalidates_profile_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope_name: str,
    relative_path: str,
) -> None:
    repository = tmp_path / "repository"
    source = repository / relative_path
    source.parent.mkdir(parents=True)
    source.write_text("baseline\n")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", relative_path], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Coffer Test",
            "-c",
            "user.email=coffer-test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    monkeypatch.setattr(scope, "ROOT", repository)
    monkeypatch.setitem(scope.SOURCE_PATHS, scope_name, (source,))

    baseline = scope.scope_source_tree_sha256(scope_name)
    assert baseline.startswith("sha256:")
    source.write_text("runtime-affecting drift\n")
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="not clean",
    ):
        scope.scope_source_tree_sha256(scope_name)


def test_canonical_dynamic_modules_share_security_document_type() -> None:
    assert scope.TRUST.LoadedDocument is lineage.TRUST.LoadedDocument
    assert scope.TRUST.TrustPolicyError is lineage.TRUST.TrustPolicyError


def test_storage_backend_is_exact_policy_lineage_and_not_free_metadata(
    tmp_path: Path,
) -> None:
    result, policy_path, signing_keys = compile_scope(
        tmp_path,
        "storage_backend",
        "s3-compatible",
    )
    assert result["derived"]["backend"]["provider_name"] == "ceph-rgw"
    assert result["derived"]["provider_bindings"] == {}

    tampered = deepcopy(result)
    backend_attestation = tampered["bundle"]["evidence_attestation"]["predicate"][
        "backend_attestation"
    ]
    backend_attestation["predicate"]["backend_id"] = "unapproved-backend"
    backend_attestation["signature"] = base64.b64encode(
        signing_keys.storage_provider.sign(
            trust.canonical_bytes(
                {
                    key: value
                    for key, value in backend_attestation.items()
                    if key != "signature"
                }
            )
        )
    ).decode()
    with pytest.raises(scope.ScopeEvidenceError, match="not policy-approved"):
        scope.validate_test_result(
            tampered,
            policy_path=policy_path,
            today=TODAY,
            allow_synthetic_policy=True,
        )


def test_rgw_backend_must_match_the_exact_ceph_input_lineage(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="does not match the Ceph input",
    ):
        compile_scope(
            tmp_path,
            "rgw_barbican_kms",
            "rgw-barbican-sse-kms",
            backend_overrides={"provider_revision": "3" * 40},
        )


def test_expired_storage_catalog_and_result_fail_closed() -> None:
    signing_keys = input_test.keys()
    policy = input_test.synthetic_policy(signing_keys)
    manifests = provider_manifests(
        "storage_backend",
        "s3-compatible",
        environment="synthetic",
    )
    add_scope_policy(
        policy,
        scope_name="storage_backend",
        signing_keys=signing_keys,
        provider_manifests=manifests,
        environment="synthetic",
    )
    policy["storage_backends"][BACKEND_ID]["support_ends_on"] = "2026-07-27"

    with pytest.raises(trust.TrustPolicyError, match="storage backend"):
        trust.validate_policy(policy, today=TODAY)


def test_scope_evidence_and_qualification_require_independent_domains(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="not independent",
    ):
        compile_scope(
            tmp_path,
            "registry_core",
            "core",
            environment="production",
            same_trust_domain=True,
        )


def test_each_scope_result_must_be_within_the_adapter_interval(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="scope evidence result is invalid",
    ):
        compile_scope(
            tmp_path,
            "registry_core",
            "core",
            environment="production",
            adapter_valid_from=TODAY.isoformat(),
            result_observed_on="2026-07-27",
        )


@pytest.mark.parametrize(
    ("mode", "advertised", "limitations"),
    (
        ("native", True, []),
        ("fallback-tag", True, list(scope.FALLBACK_LIMITATIONS)),
        ("disabled", False, []),
    ),
)
def test_referrers_dispositions_are_exact(
    tmp_path: Path,
    mode: str,
    advertised: bool,
    limitations: list[str],
) -> None:
    result, _, _ = compile_scope(tmp_path, "referrers", mode)

    assert result["derived"]["referrers"] == {
        "advertised": advertised,
        "limitations": limitations,
    }


def test_operational_ttl_is_rechecked(tmp_path: Path) -> None:
    result, policy_path, _ = compile_scope(tmp_path, "registry_core", "core")

    with pytest.raises(scope.ScopeEvidenceError):
        scope.validate_test_result(
            result,
            policy_path=policy_path,
            today=date(2026, 8, 5),
            allow_synthetic_policy=True,
        )


def test_unsigned_all_true_document_is_not_scope_evidence(tmp_path: Path) -> None:
    caller = loaded(
        tmp_path,
        "caller.json",
        {
            "predicate": {
                "checks": {
                    name: True
                    for name in scope.CHECKS[("storage_backend", "s3-compatible")]
                },
                "scope": "storage_backend",
            }
        },
    )

    with pytest.raises(scope.ScopeEvidenceError):
        scope.compile_result(
            evidence_attestation=caller,
            qualification_attestation=caller,
            provider_inputs={},
        )


def test_compile_api_refuses_objects_and_policy_substitution() -> None:
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="loaded document",
    ):
        scope.compile_result(
            evidence_attestation={},
            qualification_attestation={},
            provider_inputs={},
        )
    with pytest.raises(TypeError):
        scope.validate_final_result({}, today=TODAY)
    with pytest.raises(TypeError):
        scope.validate_final_result(
            {},
            policy_path=Path("/tmp/attacker-policy.json"),
        )


def test_scope_result_serialized_budget_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scope, "SCOPE_RESULT_MAX_BYTES", 1)
    with pytest.raises(
        scope.ScopeEvidenceError,
        match="fixed budget",
    ):
        compile_scope(tmp_path, "referrers", "disabled")


def test_cli_cannot_substitute_policy_or_publish_synthetic_scope(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    evidence = tmp_path / "evidence.json"
    qualification = tmp_path / "qualification.json"
    input_test.write_json(
        evidence,
        {"predicate": {"mode": "s3-compatible", "scope": "storage_backend"}},
        private=True,
    )
    input_test.write_json(qualification, {}, private=True)
    output = tmp_path / "result.json"

    assert (
        scope.main(
            [
                "--scope",
                "storage_backend",
                "--evidence-attestation",
                str(evidence),
                "--qualification-attestation",
                str(qualification),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert not output.exists()
