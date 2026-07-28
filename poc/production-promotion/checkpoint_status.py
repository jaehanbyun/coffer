from __future__ import annotations

import base64
import binascii
import importlib.util
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
REGISTRY_SOURCE = DIRECTORY / "verifier_registry.py"
PRODUCTION_REGISTRY_SOURCE = DIRECTORY / "verifier-bundles-v2.json"
CHECKPOINT_MAX_BYTES = 1024 * 1024


class CheckpointStatusError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise CheckpointStatusError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise CheckpointStatusError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise CheckpointStatusError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
REGISTRY = _load_module(
    "coffer_production_checkpoint_verifier_registry_v2",
    REGISTRY_SOURCE,
)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CheckpointStatusError(f"{label} must be a JSON object")
    return value


def _decode(value: object) -> bytes:
    maximum_encoded = ((CHECKPOINT_MAX_BYTES + 2) // 3) * 4
    if not isinstance(value, str) or len(value) > maximum_encoded:
        raise CheckpointStatusError("checkpoint attestation bytes are invalid")
    try:
        payload = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CheckpointStatusError(
            "checkpoint attestation bytes are invalid"
        ) from error
    if not 1 <= len(payload) <= CHECKPOINT_MAX_BYTES:
        raise CheckpointStatusError(
            "checkpoint attestation bytes size is invalid"
        )
    return payload


def _untrusted_bundle_identity(
    checkpoint_record: Mapping[str, Any],
) -> tuple[str, str]:
    payload = _decode(checkpoint_record.get("attestation_bytes_base64"))
    try:
        value = TRUST.strict_json_loads(payload)
    except TRUST.TrustPolicyError as error:
        raise CheckpointStatusError(
            "checkpoint attestation JSON is invalid"
        ) from error
    attestation = _mapping(value, "checkpoint attestation")
    predicate = _mapping(
        attestation.get("predicate"),
        "checkpoint predicate",
    )
    try:
        bundle_id = TRUST.identifier(
            predicate.get("verifier_bundle_id"),
            "checkpoint verifier bundle ID",
        )
        bundle_sha256 = TRUST.digest(
            predicate.get("verifier_bundle_sha256"),
            "checkpoint verifier bundle digest",
        )
    except TRUST.TrustPolicyError as error:
        raise CheckpointStatusError(str(error)) from error
    return bundle_id, bundle_sha256


def _revoked(
    *,
    verified: Mapping[str, Any],
    current_policy: Mapping[str, Any],
    at: date,
) -> bool:
    key_id = verified["authority"]["key_id"]
    issued = TRUST.parse_date(
        verified["attestation"]["issued_on"],
        "checkpoint issued_on",
    )
    for revocation in current_policy["checkpoint_revocations"]:
        if revocation["key_id"] != key_id:
            continue
        revoked_on = TRUST.parse_date(
            revocation["revoked_on"],
            "checkpoint revoked_on",
        )
        compromised_since = (
            None
            if revocation["compromised_since"] is None
            else TRUST.parse_date(
                revocation["compromised_since"],
                "checkpoint compromised_since",
            )
        )
        if revoked_on <= at or (
            compromised_since is not None and compromised_since <= issued
        ):
            return True
    return False


def evaluate_checkpoint(
    *,
    migration: Mapping[str, Any],
    current_policy: Mapping[str, Any],
    at: date,
    registry_path: Path = PRODUCTION_REGISTRY_SOURCE,
) -> dict[str, Any]:
    checkpoint_record = _mapping(
        migration.get("checkpoint"),
        "migration checkpoint record",
    )
    base = {
        "checkpoint_attestation_sha256": checkpoint_record.get(
            "attestation_canonical_sha256"
        ),
        "checkpoint_embedded": checkpoint_record.get("present") is True,
        "checkpoint_status": "missing",
        "checkpoint_verified": False,
        "deployment_id": None,
        "reason_codes": ["signed-pre-upgrade-checkpoint-missing"],
        "rollback_deadline": None,
        "verifier_bundle_id": None,
        "verifier_bundle_sha256": None,
    }
    if checkpoint_record.get("present") is not True:
        return base
    try:
        bundle_id, bundle_sha256 = _untrusted_bundle_identity(
            checkpoint_record
        )
    except CheckpointStatusError:
        return {
            **base,
            "checkpoint_status": "invalid",
            "reason_codes": ["signed-pre-upgrade-checkpoint-invalid"],
        }
    base["verifier_bundle_id"] = bundle_id
    base["verifier_bundle_sha256"] = bundle_sha256
    try:
        registry_entry, verifier = REGISTRY.resolve_verifier(
            bundle_id=bundle_id,
            bundle_sha256=bundle_sha256,
            registry_path=registry_path,
        )
    except REGISTRY.UnsupportedVerifierError:
        return {
            **base,
            "checkpoint_status": "unsupported-verifier",
            "reason_codes": ["checkpoint-verifier-not-admitted"],
        }
    except REGISTRY.VerifierRegistryError:
        return {
            **base,
            "checkpoint_status": "invalid",
            "reason_codes": ["checkpoint-verifier-registry-invalid"],
        }
    try:
        verified = verifier(
            checkpoint_record,
            migration=migration,
            registry_entry_value=registry_entry,
            at=at,
        )
    except Exception as error:
        if error.__class__.__name__ == "CheckpointExpiredError":
            return {
                **base,
                "checkpoint_status": "expired",
                "reason_codes": ["signed-pre-upgrade-checkpoint-expired"],
            }
        return {
            **base,
            "checkpoint_status": "invalid",
            "reason_codes": ["signed-pre-upgrade-checkpoint-invalid"],
        }
    if _revoked(
        verified=verified,
        current_policy=current_policy,
        at=at,
    ):
        return {
            **base,
            "checkpoint_status": "policy-revoked",
            "deployment_id": verified["deployment_id"],
            "reason_codes": ["checkpoint-authority-revoked"],
            "rollback_deadline": verified["rollback_deadline"],
        }
    return {
        **base,
        "checkpoint_status": "verified",
        "checkpoint_verified": True,
        "deployment_id": verified["deployment_id"],
        "reason_codes": [],
        "rollback_deadline": verified["rollback_deadline"],
    }


def verify_checkpoint(
    *,
    migration: Mapping[str, Any],
    current_policy: Mapping[str, Any],
    at: date,
    registry_path: Path = PRODUCTION_REGISTRY_SOURCE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    status = evaluate_checkpoint(
        migration=migration,
        current_policy=current_policy,
        at=at,
        registry_path=registry_path,
    )
    if status["checkpoint_status"] != "verified":
        raise CheckpointStatusError(
            f"checkpoint is not verified: {status['checkpoint_status']}"
        )
    bundle_id = status["verifier_bundle_id"]
    bundle_sha256 = status["verifier_bundle_sha256"]
    try:
        registry_entry, verifier = REGISTRY.resolve_verifier(
            bundle_id=bundle_id,
            bundle_sha256=bundle_sha256,
            registry_path=registry_path,
        )
        verified = verifier(
            migration["checkpoint"],
            migration=migration,
            registry_entry_value=registry_entry,
            at=at,
        )
    except Exception as error:
        raise CheckpointStatusError(
            "verified checkpoint could not be reproduced"
        ) from error
    return status, verified
