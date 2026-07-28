from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

BUNDLE_ID = "coffer.checkpoint-verifier.v2.0.0"
ATTESTATION_SCHEMA = "coffer.signed-attestation/v2"
POLICY_SCHEMA = "coffer.production-trust-policy/v2"
PREDICATE_SCHEMA = "coffer.production-migration-checkpoint-predicate/v2"
MAX_CHECKPOINT_BYTES = 1024 * 1024
MAX_POLICY_BYTES = 4 * 1024 * 1024

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class CheckpointVerificationError(RuntimeError):
    pass


class CheckpointExpiredError(CheckpointVerificationError):
    pass


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise CheckpointVerificationError(
            "checkpoint value is not canonical JSON"
        ) from error


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def strict_json_loads(payload: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise CheckpointVerificationError(
                    "checkpoint JSON contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            payload,
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CheckpointVerificationError(
                    f"checkpoint JSON constant {value} is not allowed"
                )
            ),
        )
    except CheckpointVerificationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CheckpointVerificationError(
            "checkpoint material is not valid JSON"
        ) from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CheckpointVerificationError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CheckpointVerificationError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise CheckpointVerificationError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CheckpointVerificationError(f"{label} is invalid")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise CheckpointVerificationError(f"{label} is invalid")
    return value


def _date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise CheckpointVerificationError(f"{label} is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CheckpointVerificationError(f"{label} is invalid") from error
    if parsed.isoformat() != value:
        raise CheckpointVerificationError(f"{label} is invalid")
    return parsed


def _decode(value: object, label: str, maximum: int) -> bytes:
    maximum_encoded = ((maximum + 2) // 3) * 4
    if not isinstance(value, str) or len(value) > maximum_encoded:
        raise CheckpointVerificationError(f"{label} is invalid")
    try:
        payload = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise CheckpointVerificationError(f"{label} is invalid") from error
    if not 1 <= len(payload) <= maximum:
        raise CheckpointVerificationError(f"{label} size is invalid")
    return payload


def _authority(
    policy: Mapping[str, Any],
    *,
    key_id: str,
    issued: date,
    expires: date,
    accepted_key_ids: list[str],
) -> dict[str, Any]:
    if (
        accepted_key_ids != sorted(set(accepted_key_ids))
        or key_id not in accepted_key_ids
    ):
        raise CheckpointVerificationError(
            "checkpoint authority is not pinned by the verifier registry"
        )
    matches: list[Mapping[str, Any]] = []
    for raw in _array(policy.get("authorities"), "archived policy authorities"):
        authority = _mapping(raw, "archived checkpoint authority")
        if authority.get("key_id") == key_id:
            matches.append(authority)
    if len(matches) != 1:
        raise CheckpointVerificationError(
            "checkpoint authority is not unique in the archived policy"
        )
    authority = matches[0]
    _exact_keys(
        authority,
        {
            "components",
            "input_classes",
            "key_id",
            "not_after",
            "not_before",
            "operator_id",
            "public_key",
            "revoked_on",
            "roles",
            "scopes",
            "trust_domain",
        },
        "archived checkpoint authority",
    )
    roles = _array(authority["roles"], "checkpoint authority roles")
    not_before = _date(authority["not_before"], "checkpoint authority not_before")
    not_after = _date(authority["not_after"], "checkpoint authority not_after")
    revoked_on = (
        None
        if authority["revoked_on"] is None
        else _date(authority["revoked_on"], "checkpoint authority revoked_on")
    )
    if (
        roles != ["migration-checkpoint"]
        or not_before > issued
        or not_after < expires
        or (revoked_on is not None and revoked_on <= expires)
    ):
        raise CheckpointVerificationError(
            "checkpoint authority was not valid at checkpoint issuance"
        )
    public_key_text = authority["public_key"]
    if not isinstance(public_key_text, str) or len(public_key_text) > 128:
        raise CheckpointVerificationError("checkpoint public key is invalid")
    try:
        public_key = base64.b64decode(public_key_text, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key)
    except (ValueError, binascii.Error) as error:
        raise CheckpointVerificationError(
            "checkpoint public key is invalid"
        ) from error
    if len(public_key) != 32:
        raise CheckpointVerificationError("checkpoint public key is invalid")
    return {
        "key_id": _identifier(authority["key_id"], "checkpoint key ID"),
        "operator_id": _identifier(
            authority["operator_id"],
            "checkpoint authority operator",
        ),
        "public_key": public_key_text,
        "trust_domain": _identifier(
            authority["trust_domain"],
            "checkpoint authority trust domain",
        ),
    }


def _deployment_state(predicate: Mapping[str, Any]) -> dict[str, str]:
    return {
        "database_schema_version": _identifier(
            predicate["database_schema_version"],
            "checkpoint database schema",
        ),
        "deployment_generation": _identifier(
            predicate["deployment_generation"],
            "checkpoint deployment generation",
        ),
        "storage_schema_version": _identifier(
            predicate["storage_schema_version"],
            "checkpoint storage schema",
        ),
    }


def verify_checkpoint_record(
    checkpoint_record_value: object,
    *,
    migration: Mapping[str, Any],
    registry_entry_value: object,
    at: date,
) -> dict[str, Any]:
    checkpoint_record = _mapping(
        checkpoint_record_value,
        "migration checkpoint record",
    )
    _exact_keys(
        checkpoint_record,
        {
            "attestation_bytes_base64",
            "attestation_canonical_sha256",
            "attestation_raw_sha256",
            "present",
            "trust_policy_bytes_base64",
            "trust_policy_canonical_sha256",
            "trust_policy_raw_sha256",
        },
        "migration checkpoint record",
    )
    if checkpoint_record["present"] is not True:
        raise CheckpointVerificationError(
            "signed pre-upgrade checkpoint is missing"
        )
    registry_entry = _mapping(
        registry_entry_value,
        "checkpoint verifier registry entry",
    )
    _exact_keys(
        registry_entry,
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
        "checkpoint verifier registry entry",
    )
    if registry_entry["status"] != "active":
        raise CheckpointVerificationError(
            "checkpoint verifier registry entry is not active"
        )
    support_ends = _date(
        registry_entry["support_ends_on"],
        "checkpoint verifier support end",
    )
    if support_ends < at:
        raise CheckpointExpiredError("checkpoint verifier support expired")

    checkpoint_bytes = _decode(
        checkpoint_record["attestation_bytes_base64"],
        "checkpoint attestation bytes",
        MAX_CHECKPOINT_BYTES,
    )
    policy_bytes = _decode(
        checkpoint_record["trust_policy_bytes_base64"],
        "archived trust policy bytes",
        MAX_POLICY_BYTES,
    )
    checkpoint_raw_sha256 = sha256_bytes(checkpoint_bytes)
    policy_raw_sha256 = sha256_bytes(policy_bytes)
    if (
        checkpoint_raw_sha256
        != _digest(
            checkpoint_record["attestation_raw_sha256"],
            "checkpoint raw digest",
        )
        or policy_raw_sha256
        != _digest(
            checkpoint_record["trust_policy_raw_sha256"],
            "archived policy raw digest",
        )
        or policy_raw_sha256
        != _digest(
            registry_entry["accepted_policy_raw_sha256"],
            "registry policy digest",
        )
    ):
        raise CheckpointVerificationError(
            "checkpoint or archived policy raw binding changed"
        )
    checkpoint_value = strict_json_loads(checkpoint_bytes)
    policy_value = strict_json_loads(policy_bytes)
    checkpoint = _mapping(checkpoint_value, "checkpoint attestation")
    policy = _mapping(policy_value, "archived trust policy")
    checkpoint_canonical_sha256 = canonical_sha256(checkpoint)
    policy_canonical_sha256 = canonical_sha256(policy)
    if (
        checkpoint_canonical_sha256
        != _digest(
            checkpoint_record["attestation_canonical_sha256"],
            "checkpoint canonical digest",
        )
        or policy_canonical_sha256
        != _digest(
            checkpoint_record["trust_policy_canonical_sha256"],
            "archived policy canonical digest",
        )
    ):
        raise CheckpointVerificationError(
            "checkpoint or archived policy canonical binding changed"
        )

    if (
        policy.get("schema") != POLICY_SCHEMA
        or policy.get("environment") != "production"
    ):
        raise CheckpointVerificationError(
            "archived checkpoint policy is not a production v2 policy"
        )
    policy_starts = _date(policy.get("valid_from"), "archived policy valid_from")
    policy_ends = _date(policy.get("valid_until"), "archived policy valid_until")
    maximum_age = policy.get("attestation_max_age_days")
    if (
        not isinstance(maximum_age, int)
        or isinstance(maximum_age, bool)
        or not 1 <= maximum_age <= 31
    ):
        raise CheckpointVerificationError(
            "archived checkpoint policy maximum age is invalid"
        )
    predicate_types = _mapping(
        policy.get("predicate_types"),
        "archived policy predicate types",
    )
    predicate_type = predicate_types.get("migration_checkpoint")
    if not isinstance(predicate_type, str) or not predicate_type:
        raise CheckpointVerificationError(
            "archived checkpoint predicate type is invalid"
        )

    _exact_keys(
        checkpoint,
        {
            "algorithm",
            "expires_on",
            "issued_on",
            "key_id",
            "predicate",
            "predicate_type",
            "role",
            "schema",
            "signature",
            "subjects",
        },
        "checkpoint attestation",
    )
    predicate = _mapping(checkpoint["predicate"], "checkpoint predicate")
    _exact_keys(
        predicate,
        {
            "archival_valid_until",
            "backup_checkpoint_sha256",
            "database_schema_version",
            "deployment_generation",
            "deployment_id",
            "legacy_evidence_inventory_sha256",
            "observed_on",
            "rollback_deadline",
            "schema",
            "storage_schema_version",
            "trust_policy_canonical_sha256",
            "trust_policy_raw_sha256",
            "v1_ledger_raw_sha256",
            "v1_release_raw_sha256",
            "verifier_bundle_id",
            "verifier_bundle_sha256",
        },
        "checkpoint predicate",
    )
    issued = _date(checkpoint["issued_on"], "checkpoint issued_on")
    expires = _date(checkpoint["expires_on"], "checkpoint expires_on")
    observed = _date(predicate["observed_on"], "checkpoint observed_on")
    archival_valid_until = _date(
        predicate["archival_valid_until"],
        "checkpoint archival_valid_until",
    )
    rollback_deadline = _date(
        predicate["rollback_deadline"],
        "checkpoint rollback_deadline",
    )
    if (
        checkpoint["schema"] != ATTESTATION_SCHEMA
        or checkpoint["algorithm"] != "ed25519"
        or checkpoint["role"] != "migration-checkpoint"
        or checkpoint["predicate_type"] != predicate_type
        or predicate["schema"] != PREDICATE_SCHEMA
        or issued != observed
        or issued > expires
        or expires - issued > timedelta(days=maximum_age)
        or archival_valid_until > expires
        or rollback_deadline > archival_valid_until
        or policy_starts > issued
        or policy_ends < expires
        or observed > at
    ):
        raise CheckpointVerificationError(
            "checkpoint identity or archival interval is invalid"
        )
    if at > archival_valid_until:
        raise CheckpointExpiredError("checkpoint archival validity expired")

    deployment_id = _identifier(
        predicate["deployment_id"],
        "checkpoint deployment ID",
    )
    deployment_state = _deployment_state(predicate)
    backup = _digest(
        predicate["backup_checkpoint_sha256"],
        "checkpoint backup",
    )
    inventory = _digest(
        predicate["legacy_evidence_inventory_sha256"],
        "checkpoint legacy inventory",
    )
    policy_raw = _digest(
        predicate["trust_policy_raw_sha256"],
        "checkpoint policy raw digest",
    )
    policy_canonical = _digest(
        predicate["trust_policy_canonical_sha256"],
        "checkpoint policy canonical digest",
    )
    bundle_id = _identifier(
        predicate["verifier_bundle_id"],
        "checkpoint verifier bundle ID",
    )
    bundle_sha256 = _digest(
        predicate["verifier_bundle_sha256"],
        "checkpoint verifier bundle digest",
    )
    source_v1 = _mapping(migration.get("source_v1"), "migration v1 source")
    if (
        predicate["v1_ledger_raw_sha256"] != source_v1.get("ledger_raw_sha256")
        or predicate["v1_release_raw_sha256"] != source_v1.get(
            "release_raw_sha256"
        )
        or policy_raw != policy_raw_sha256
        or policy_canonical != policy_canonical_sha256
        or bundle_id != registry_entry["bundle_id"]
        or bundle_sha256 != registry_entry["bundle_sha256"]
        or bundle_id != BUNDLE_ID
    ):
        raise CheckpointVerificationError(
            "checkpoint migration, policy, or verifier binding changed"
        )

    subjects = {
        "backup-checkpoint": backup,
        "deployment": canonical_sha256({"deployment_id": deployment_id}),
        "deployment-state": canonical_sha256(deployment_state),
        "legacy-evidence-inventory": inventory,
        "trust-policy": policy_raw,
        "v1-ledger": predicate["v1_ledger_raw_sha256"],
        "v1-release": predicate["v1_release_raw_sha256"],
        "verifier-bundle": bundle_sha256,
    }
    raw_subjects = _mapping(checkpoint["subjects"], "checkpoint subjects")
    if raw_subjects != dict(sorted(subjects.items())):
        raise CheckpointVerificationError(
            "checkpoint attestation subjects changed"
        )
    key_id = _identifier(checkpoint["key_id"], "checkpoint key ID")
    authority = _authority(
        policy,
        key_id=key_id,
        issued=issued,
        expires=expires,
        accepted_key_ids=_array(
            registry_entry["checkpoint_authority_key_ids"],
            "registry checkpoint authority IDs",
        ),
    )
    signature_text = checkpoint["signature"]
    if not isinstance(signature_text, str) or len(signature_text) > 256:
        raise CheckpointVerificationError("checkpoint signature is invalid")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = base64.b64decode(authority["public_key"], validate=True)
        signed = dict(checkpoint)
        del signed["signature"]
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            canonical_bytes(signed),
        )
    except (InvalidSignature, ValueError, binascii.Error) as error:
        raise CheckpointVerificationError(
            "checkpoint signature is invalid"
        ) from error

    normalized = dict(checkpoint)
    normalized["predicate"] = {
        "archival_valid_until": archival_valid_until.isoformat(),
        "backup_checkpoint_sha256": backup,
        "database_schema_version": deployment_state[
            "database_schema_version"
        ],
        "deployment_generation": deployment_state["deployment_generation"],
        "deployment_id": deployment_id,
        "legacy_evidence_inventory_sha256": inventory,
        "observed_on": observed.isoformat(),
        "rollback_deadline": rollback_deadline.isoformat(),
        "schema": PREDICATE_SCHEMA,
        "storage_schema_version": deployment_state["storage_schema_version"],
        "trust_policy_canonical_sha256": policy_canonical,
        "trust_policy_raw_sha256": policy_raw,
        "v1_ledger_raw_sha256": predicate["v1_ledger_raw_sha256"],
        "v1_release_raw_sha256": predicate["v1_release_raw_sha256"],
        "verifier_bundle_id": bundle_id,
        "verifier_bundle_sha256": bundle_sha256,
    }
    if canonical_sha256(normalized) != checkpoint_canonical_sha256:
        raise CheckpointVerificationError(
            "normalized checkpoint binding changed"
        )
    return {
        "attestation": normalized,
        "authority": authority,
        "deployment_id": deployment_id,
        "policy_canonical_sha256": policy_canonical,
        "policy_raw_sha256": policy_raw,
        "rollback_deadline": rollback_deadline.isoformat(),
        "verifier_bundle_id": bundle_id,
        "verifier_bundle_sha256": bundle_sha256,
    }
