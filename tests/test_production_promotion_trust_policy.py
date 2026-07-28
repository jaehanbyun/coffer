from __future__ import annotations

import base64
import importlib.util
import json
import os
import stat
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "trust_policy.py"
POLICY_SOURCE = ROOT / "poc" / "production-promotion" / "trust-policy-v2.json"
SPEC = importlib.util.spec_from_file_location(
    "coffer_test_production_promotion_trust_policy",
    SOURCE,
)
assert SPEC is not None and SPEC.loader is not None
trust = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trust
SPEC.loader.exec_module(trust)

TODAY = date(2026, 7, 28)
DIGEST = f"sha256:{'1' * 64}"


def public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def synthetic_policy(
    private_key: Ed25519PrivateKey,
    *,
    environment: str = "synthetic",
) -> dict[str, object]:
    policy = json.loads(POLICY_SOURCE.read_text())
    policy["environment"] = environment
    policy["components"]["distribution"]["release_signing_identities"] = [
        "fixture-release-signer"
    ]
    policy["authorities"] = [
        {
            "components": ["distribution"],
            "input_classes": ["official-upstream"],
            "key_id": "fixture-qualification",
            "not_after": "2027-01-31",
            "not_before": "2026-07-01",
            "operator_id": "operator-fixture-qualification",
            "public_key": public_key(private_key),
            "revoked_on": None,
            "roles": ["input-qualification"],
            "scopes": [],
            "trust_domain": "domain-fixture-qualification",
        }
    ]
    return policy


def signed_attestation(
    private_key: Ed25519PrivateKey,
    *,
    signature_key: str = "fixture-qualification",
) -> dict[str, object]:
    attestation: dict[str, object] = {
        "algorithm": "ed25519",
        "expires_on": "2026-08-04",
        "issued_on": "2026-07-28",
        "key_id": signature_key,
        "predicate": {"check": "source-bound"},
        "predicate_type": ("https://coffer.invalid/attestations/production-input/v2"),
        "role": "input-qualification",
        "schema": trust.ATTESTATION_SCHEMA,
        "subjects": {"lineage": DIGEST},
    }
    attestation["signature"] = base64.b64encode(
        private_key.sign(trust.canonical_bytes(attestation))
    ).decode()
    return attestation


def validate(
    attestation: object,
    policy: object,
) -> dict[str, object]:
    parsed = trust.validate_policy(policy, today=TODAY)
    return trust.verify_attestation(
        attestation,
        policy=parsed,
        role="input-qualification",
        predicate_type=parsed["predicate_types"]["input_qualification"],
        subjects={"lineage": DIGEST},
        component="distribution",
        input_class="official-upstream",
        today=TODAY,
    )


def test_checked_in_policy_has_no_implicit_production_authority() -> None:
    policy, policy_digest = trust.load_policy(today=TODAY)

    assert policy["environment"] == "production"
    assert policy["authorities"] == []
    assert policy["vendors"] == []
    assert policy_digest == trust.sha256_file(POLICY_SOURCE)

    key = Ed25519PrivateKey.generate()
    with pytest.raises(
        trust.TrustPolicyError,
        match="authority is not trusted",
    ):
        validate(signed_attestation(key), policy)


@pytest.mark.parametrize(
    "url",
    (
        "https://vendor.example/advisories/../untrusted",
        "https://vendor.example/advisories/%2e%2e/untrusted",
        "https://vendor.example/advisories//untrusted",
        "https://vendor.example/advisories/foo\\..\\..\\untrusted",
        "https://user@vendor.example/advisories",
    ),
)
def test_policy_https_url_rejects_ambiguous_or_traversing_paths(
    url: str,
) -> None:
    with pytest.raises(trust.TrustPolicyError, match="invalid"):
        trust._https_url(url, "fixture URL")


def test_ed25519_attestation_binds_role_subject_and_predicate() -> None:
    key = Ed25519PrivateKey.generate()
    policy = synthetic_policy(key)
    attestation = signed_attestation(key)

    result = validate(attestation, policy)

    assert result["key_id"] == "fixture-qualification"
    assert result["subjects"] == {"lineage": DIGEST}
    assert result["predicate"] == {"check": "source-bound"}

    for field, value in (
        ("predicate", {"check": "forged"}),
        ("role", "builder"),
        ("predicate_type", "https://attacker.invalid/predicate"),
        ("subjects", {"lineage": f"sha256:{'2' * 64}"}),
        ("signature", base64.b64encode(b"x" * 64).decode()),
    ):
        tampered = deepcopy(attestation)
        tampered[field] = value
        with pytest.raises(trust.TrustPolicyError):
            validate(tampered, policy)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("not_before", "2026-07-29"),
        ("not_after", "2026-07-27"),
        ("revoked_on", "2026-07-28"),
    ),
)
def test_authority_date_or_revocation_blocks_attestation(
    field: str,
    value: str,
) -> None:
    key = Ed25519PrivateKey.generate()
    policy = synthetic_policy(key)
    policy["authorities"][0][field] = value

    with pytest.raises(trust.TrustPolicyError):
        validate(signed_attestation(key), policy)


def test_attestation_expiry_and_maximum_age_are_fail_closed() -> None:
    key = Ed25519PrivateKey.generate()
    policy = synthetic_policy(key)
    expired = signed_attestation(key)
    expired["expires_on"] = "2026-07-27"
    expired["signature"] = base64.b64encode(
        key.sign(
            trust.canonical_bytes(
                {name: value for name, value in expired.items() if name != "signature"}
            )
        )
    ).decode()

    with pytest.raises(
        trust.TrustPolicyError,
        match="identity is invalid",
    ):
        validate(expired, policy)

    too_long = signed_attestation(key)
    too_long["expires_on"] = "2026-08-05"
    too_long["signature"] = base64.b64encode(
        key.sign(
            trust.canonical_bytes(
                {name: value for name, value in too_long.items() if name != "signature"}
            )
        )
    ).decode()
    with pytest.raises(
        trust.TrustPolicyError,
        match="identity is invalid",
    ):
        validate(too_long, policy)


def test_authority_public_key_reuse_and_multi_role_keys_are_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    policy = synthetic_policy(key)
    reused = deepcopy(policy["authorities"][0])
    reused["key_id"] = "fixture-second-key-id"
    reused["operator_id"] = "operator-fixture-second"
    reused["trust_domain"] = "domain-fixture-second"
    policy["authorities"].append(reused)

    with pytest.raises(
        trust.TrustPolicyError,
        match="public keys are not unique",
    ):
        trust.validate_policy(policy, today=TODAY)

    policy = synthetic_policy(key)
    policy["authorities"][0]["roles"] = ["builder", "input-qualification"]
    with pytest.raises(
        trust.TrustPolicyError,
        match="exactly one role",
    ):
        trust.validate_policy(policy, today=TODAY)


def test_strict_json_rejects_duplicate_keys_and_non_finite_values() -> None:
    with pytest.raises(
        trust.TrustPolicyError,
        match="duplicate keys",
    ):
        trust.strict_json_loads(b'{"schema":"one","schema":"two"}')

    with pytest.raises(
        trust.TrustPolicyError,
        match="not allowed",
    ):
        trust.strict_json_loads(b'{"value":NaN}')


def test_synthetic_policy_requires_explicit_test_boundary(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    policy_path = tmp_path / "synthetic-policy.json"
    policy_path.write_text(json.dumps(synthetic_policy(key)))

    with pytest.raises(
        trust.TrustPolicyError,
        match="not production",
    ):
        trust.load_policy(policy_path, today=TODAY)

    policy, _ = trust.load_policy(
        policy_path,
        today=TODAY,
        allow_synthetic=True,
    )
    assert policy["environment"] == "synthetic"


def test_owner_only_reader_rejects_mode_link_and_duplicate_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.json"
    path.write_text("{}")
    path.chmod(0o644)
    with pytest.raises(
        trust.TrustPolicyError,
        match="unsafe",
    ):
        trust.load_private_json(path, "evidence")

    path.chmod(0o600)
    linked = tmp_path / "linked.json"
    os.link(path, linked)
    with pytest.raises(
        trust.TrustPolicyError,
        match="unsafe",
    ):
        trust.load_private_json(path, "evidence")
    linked.unlink()

    path.write_text('{"value":1,"value":2}')
    with pytest.raises(
        trust.TrustPolicyError,
        match="duplicate keys",
    ):
        trust.load_private_json(path, "evidence")


def test_loaded_document_binding_rejects_false_digests_and_post_load_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.json"
    path.write_text('{"value":1}')
    path.chmod(0o600)
    loaded = trust.load_private_json(path, "evidence")
    loaded.value["value"] = 2
    with pytest.raises(
        trust.TrustPolicyError,
        match="binding changed",
    ):
        trust.verify_loaded_document(loaded, "evidence")

    forged = trust.LoadedDocument(
        value={"value": 1},
        raw_sha256=f"sha256:{'0' * 64}",
        canonical_sha256=f"sha256:{'1' * 64}",
        raw_bytes=b'{"value":1}',
    )
    with pytest.raises(
        trust.TrustPolicyError,
        match="binding changed",
    ):
        trust.verify_loaded_document(forged, "evidence")


def test_atomic_owner_only_writer_never_overwrites(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "result.json"

    trust.write_owner_only(output, {"schema": "fixture"})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_nlink == 1
    assert json.loads(output.read_text()) == {"schema": "fixture"}
    with pytest.raises(
        trust.TrustPolicyError,
        match="already exists",
    ):
        trust.write_owner_only(output, {"schema": "replacement"})
    assert json.loads(output.read_text()) == {"schema": "fixture"}


def test_deterministic_owner_only_result_is_reused_only_when_exact(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    output = tmp_path / "result.json"
    expected = {"schema": "fixture", "value": 1}

    trust.write_or_verify_owner_only(
        output,
        expected,
        label="fixture result",
    )
    original = output.read_bytes()
    trust.write_or_verify_owner_only(
        output,
        expected,
        label="fixture result",
    )

    assert output.read_bytes() == original
    with pytest.raises(
        trust.TrustPolicyError,
        match="does not match requested inputs",
    ):
        trust.write_or_verify_owner_only(
            output,
            {"schema": "fixture", "value": 2},
            label="fixture result",
        )
    assert output.read_bytes() == original


def test_deterministic_result_reuse_enforces_destination_security(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.chmod(0o700)
    expected = {"schema": "fixture", "value": 1}
    payload = trust.canonical_bytes(expected) + b"\n"
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    unsafe_output = unsafe / "result.json"
    unsafe_output.write_bytes(payload)
    unsafe_output.chmod(0o600)

    with pytest.raises(
        trust.TrustPolicyError,
        match="output directory ownership is unsafe",
    ):
        trust.write_or_verify_owner_only(
            unsafe_output,
            expected,
            label="fixture result",
        )

    existing = tmp_path / "relative.json"
    existing.write_bytes(payload)
    existing.chmod(0o600)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(
        trust.TrustPolicyError,
        match="output path must be absolute",
    ):
        trust.write_or_verify_owner_only(
            Path("relative.json"),
            expected,
            label="fixture result",
        )


def test_owner_only_writer_uses_an_explicit_bounded_publication_limit(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    accepted = tmp_path / "accepted.bin"
    payload = b"bounded-payload"

    trust.write_owner_only_bytes(
        accepted,
        payload,
        maximum_bytes=len(payload),
    )
    assert accepted.read_bytes() == payload
    assert stat.S_IMODE(accepted.stat().st_mode) == 0o600

    with pytest.raises(
        trust.TrustPolicyError,
        match="payload size",
    ):
        trust.write_owner_only_bytes(
            tmp_path / "too-small.bin",
            payload,
            maximum_bytes=len(payload) - 1,
        )
    with pytest.raises(
        trust.TrustPolicyError,
        match="payload size",
    ):
        trust.write_owner_only_bytes(
            tmp_path / "above-hard-limit.bin",
            b"x",
            maximum_bytes=trust.OWNER_ONLY_HARD_MAX_BYTES + 1,
        )
