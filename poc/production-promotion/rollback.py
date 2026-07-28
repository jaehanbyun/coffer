from __future__ import annotations

import argparse
import importlib.util
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
MIGRATION_SOURCE = DIRECTORY / "migration.py"
LEDGER_V2_SOURCE = DIRECTORY / "ledger_v2.py"
CHECKPOINT_STATUS_SOURCE = DIRECTORY / "checkpoint_status.py"
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"
PRODUCTION_VERIFIER_REGISTRY_SOURCE = DIRECTORY / "verifier-bundles-v2.json"

CHECKPOINT_PREDICATE_SCHEMA = (
    "coffer.production-migration-checkpoint-predicate/v2"
)
AUTHORIZATION_PREDICATE_SCHEMA = (
    "coffer.production-rollback-authorization-predicate/v2"
)
WRITER_FENCE_PREDICATE_SCHEMA = (
    "coffer.production-writer-fence-predicate/v2"
)
RESULT_SCHEMA = "coffer.production-rollback-verification/v2"
RECEIPT_SCHEMA = "coffer.production-rollback-receipt/v2"
DESTINATION_SCHEMA = "coffer.production-rollback-destination/v2"
MAX_OPERATION_INTERVAL = timedelta(minutes=5)
CLOCK_SKEW = timedelta(seconds=5)
ROLLBACK_DOCUMENT_MAX_BYTES = 16 * 1024 * 1024
RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class RollbackError(RuntimeError):
    pass


class RollbackStateAdapter(Protocol):
    """A deployment-wide CAS and held-lease adapter.

    Production implementations must use a shared state system. The test API
    accepts an explicit fixture implementation; the production API never
    accepts a caller-supplied adapter.
    """

    def hold_authorization(
        self,
        *,
        authorization_id: str,
        authorization_sha256: str,
        deployment_id: str,
        destination_id: str,
        destination_sha256: str,
        fence: Mapping[str, Any],
        rollback_target_id: str,
        now: datetime,
    ) -> AbstractContextManager[Mapping[str, Any]]: ...

    def complete_authorization(
        self,
        *,
        claim: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None: ...

    def begin_publication(
        self,
        *,
        claim: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def resolve_destination(
        self,
        *,
        deployment_id: str,
        rollback_target_id: str,
    ) -> Mapping[str, Any]: ...


@contextmanager
def _held_claim(
    context: AbstractContextManager[Mapping[str, Any]],
) -> Any:
    try:
        with context as claim:
            yield claim
    except RollbackError:
        raise
    except Exception as error:
        raise RollbackError(
            "deployment-wide rollback state could not be claimed"
        ) from error


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise RollbackError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RollbackError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise RollbackError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
MIGRATION = _load_module(
    "coffer_production_ledger_migration_v2",
    MIGRATION_SOURCE,
)
LEDGER_V2 = _load_module(
    "coffer_production_ledger_v2",
    LEDGER_V2_SOURCE,
)
CHECKPOINT_STATUS = _load_module(
    "coffer_production_checkpoint_status_v2",
    CHECKPOINT_STATUS_SOURCE,
)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error


def _canonical_digest(value: object) -> str:
    try:
        return TRUST.canonical_sha256(value)
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error


def source_hashes() -> dict[str, str]:
    return {
        "checkpoint_status_verifier_sha256": _sha256(
            CHECKPOINT_STATUS_SOURCE
        ),
        "ledger_v2_verifier_sha256": _sha256(LEDGER_V2_SOURCE),
        "migration_verifier_sha256": _sha256(MIGRATION_SOURCE),
        "rollback_verifier_sha256": _sha256(Path(__file__).resolve()),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RollbackError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise RollbackError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    try:
        return TRUST.digest(value, label)
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error


def _identifier(value: object, label: str) -> str:
    try:
        return TRUST.identifier(value, label)
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error


def _text(value: object, label: str, *, maximum: int = 4096) -> str:
    try:
        return TRUST.text(value, label, maximum=maximum)
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or RFC3339_UTC.fullmatch(value) is None:
        raise RollbackError(f"{label} must be strict RFC3339 UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
    except ValueError as error:
        raise RollbackError(f"{label} must be strict RFC3339 UTC") from error
    if _format_timestamp(parsed) != value:
        raise RollbackError(f"{label} must be strict RFC3339 UTC")
    return parsed


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise RollbackError("rollback timestamp must be UTC aware")
    return value.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise RollbackError("rollback clock must be UTC aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _deployment_state(
    *,
    deployment_generation: str,
    database_schema_version: str,
    storage_schema_version: str,
) -> dict[str, str]:
    return {
        "database_schema_version": database_schema_version,
        "deployment_generation": deployment_generation,
        "storage_schema_version": storage_schema_version,
    }


def _current_revocation_allows(
    *,
    current_policy: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    now: datetime,
) -> None:
    key_id = checkpoint["authority"]["key_id"]
    issued = TRUST.parse_date(
        checkpoint["attestation"]["issued_on"],
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
        if revoked_on <= now.date() or (
            compromised_since is not None and compromised_since <= issued
        ):
            raise RollbackError("checkpoint authority is currently revoked")


def _writer_fence(
    value: object,
    *,
    checkpoint: Mapping[str, Any],
    policy: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    attestation = _mapping(value, "writer fence attestation")
    predicate = _mapping(
        attestation.get("predicate"),
        "writer fence predicate",
    )
    _exact_keys(
        predicate,
        {
            "active",
            "active_uploads",
            "active_writers",
            "adapter_id",
            "database_schema_version",
            "deployment_generation",
            "deployment_id",
            "expires_at",
            "lease_epoch",
            "lease_id",
            "lease_state_sha256",
            "observed_at",
            "schema",
            "storage_schema_version",
            "unknown_listeners",
        },
        "writer fence predicate",
    )
    checkpoint_predicate = checkpoint["attestation"]["predicate"]
    deployment_id = _identifier(
        predicate["deployment_id"],
        "writer fence deployment ID",
    )
    generation = _identifier(
        predicate["deployment_generation"],
        "writer fence deployment generation",
    )
    database_schema = _identifier(
        predicate["database_schema_version"],
        "writer fence database schema",
    )
    storage_schema = _identifier(
        predicate["storage_schema_version"],
        "writer fence storage schema",
    )
    adapter_id = _identifier(
        predicate["adapter_id"],
        "writer fence adapter ID",
    )
    lease_id = _identifier(predicate["lease_id"], "writer fence lease ID")
    lease_epoch = predicate["lease_epoch"]
    lease_state = _digest(
        predicate["lease_state_sha256"],
        "writer fence lease state",
    )
    observed = _timestamp(predicate["observed_at"], "writer fence observed_at")
    expires = _timestamp(predicate["expires_at"], "writer fence expires_at")
    adapter = policy["writer_fence_adapters"].get(adapter_id)
    deployment_state = _deployment_state(
        deployment_generation=generation,
        database_schema_version=database_schema,
        storage_schema_version=storage_schema,
    )
    lease_identity = {
        "lease_epoch": lease_epoch,
        "lease_id": lease_id,
    }
    if (
        adapter is None
        or adapter["state_backend"] != "shared-cas-lease"
        or predicate["schema"] != WRITER_FENCE_PREDICATE_SCHEMA
        or deployment_id != checkpoint["deployment_id"]
        or generation != checkpoint_predicate["deployment_generation"]
        or database_schema
        != checkpoint_predicate["database_schema_version"]
        or storage_schema != checkpoint_predicate["storage_schema_version"]
        or predicate["active"] is not True
        or predicate["active_writers"] != 0
        or predicate["active_uploads"] != 0
        or predicate["unknown_listeners"] != 0
        or not isinstance(lease_epoch, int)
        or isinstance(lease_epoch, bool)
        or lease_epoch < 1
        or observed > now + CLOCK_SKEW
        or now >= expires
        or expires <= observed
        or expires - observed > MAX_OPERATION_INTERVAL
        or now - observed > MAX_OPERATION_INTERVAL
    ):
        raise RollbackError("writer fence is not an active held lease")
    subjects = {
        "adapter": _canonical_digest(adapter),
        "deployment": _canonical_digest({"deployment_id": deployment_id}),
        "deployment-state": _canonical_digest(deployment_state),
        "lease": _canonical_digest(lease_identity),
        "lease-state": lease_state,
    }
    try:
        verified = TRUST.verify_attestation(
            attestation,
            policy=policy,
            role="writer-fence",
            predicate_type=policy["predicate_types"]["writer_fence"],
            subjects=dict(sorted(subjects.items())),
            today=now.date(),
        )
        authority = TRUST.policy_authority(
            policy,
            key_id=verified["key_id"],
            role="writer-fence",
            today=now.date(),
        )
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error
    if (
        verified["key_id"] != adapter["authority_key_id"]
        or TRUST.parse_date(
            verified["issued_on"],
            "writer fence issued_on",
        )
        != observed.date()
        or TRUST.parse_date(
            verified["expires_on"],
            "writer fence expires_on",
        )
        != expires.date()
    ):
        raise RollbackError("writer fence authority or interval changed")
    normalized = dict(verified)
    normalized["predicate"] = {
        "active": True,
        "active_uploads": 0,
        "active_writers": 0,
        "adapter_id": adapter_id,
        "database_schema_version": database_schema,
        "deployment_generation": generation,
        "deployment_id": deployment_id,
        "expires_at": _format_timestamp(expires),
        "lease_epoch": lease_epoch,
        "lease_id": lease_id,
        "lease_state_sha256": lease_state,
        "observed_at": _format_timestamp(observed),
        "schema": WRITER_FENCE_PREDICATE_SCHEMA,
        "storage_schema_version": storage_schema,
        "unknown_listeners": 0,
    }
    if _canonical_digest(normalized) != _canonical_digest(attestation):
        raise RollbackError("normalized writer fence binding changed")
    return normalized, authority


def _authorization(
    value: object,
    *,
    migration: Mapping[str, Any],
    ledger: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    fence: Mapping[str, Any],
    checkpoint_authority: Mapping[str, Any],
    fence_authority: Mapping[str, Any],
    policy: Mapping[str, Any],
    rollback_target_id: str,
    now: datetime,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    attestation = _mapping(value, "rollback authorization attestation")
    predicate = _mapping(
        attestation.get("predicate"),
        "rollback authorization predicate",
    )
    _exact_keys(
        predicate,
        {
            "authorization_id",
            "backup_checkpoint_sha256",
            "checkpoint_sha256",
            "database_schema_version",
            "deployment_generation",
            "deployment_id",
            "destination_id",
            "destination_sha256",
            "expires_at",
            "irreversible_database_migration",
            "issued_at",
            "ledger_v2_sha256",
            "migration_sha256",
            "restorability_evidence_sha256",
            "rollback_target_id",
            "schema",
            "storage_schema_version",
            "v2_only_storage_writes",
            "writer_fence_sha256",
        },
        "rollback authorization predicate",
    )
    checkpoint_predicate = checkpoint["attestation"]["predicate"]
    authorization_id = _identifier(
        predicate["authorization_id"],
        "rollback authorization ID",
    )
    deployment_id = _identifier(
        predicate["deployment_id"],
        "authorization deployment ID",
    )
    target_id = _identifier(
        predicate["rollback_target_id"],
        "authorization rollback target ID",
    )
    destination_id = _identifier(
        predicate["destination_id"],
        "authorization destination ID",
    )
    destination_sha256 = _digest(
        predicate["destination_sha256"],
        "authorization destination",
    )
    generation = _identifier(
        predicate["deployment_generation"],
        "authorization deployment generation",
    )
    database_schema = _identifier(
        predicate["database_schema_version"],
        "authorization database schema",
    )
    storage_schema = _identifier(
        predicate["storage_schema_version"],
        "authorization storage schema",
    )
    backup = _digest(
        predicate["backup_checkpoint_sha256"],
        "authorization backup checkpoint",
    )
    restorability = _digest(
        predicate["restorability_evidence_sha256"],
        "authorization restorability evidence",
    )
    fence_digest = _digest(
        predicate["writer_fence_sha256"],
        "authorization writer fence",
    )
    issued = _timestamp(predicate["issued_at"], "authorization issued_at")
    expires = _timestamp(predicate["expires_at"], "authorization expires_at")
    migration_digest = _canonical_digest(migration)
    ledger_digest = _canonical_digest(ledger)
    checkpoint_digest = _canonical_digest(checkpoint["attestation"])
    deployment_state = _deployment_state(
        deployment_generation=generation,
        database_schema_version=database_schema,
        storage_schema_version=storage_schema,
    )
    if (
        predicate["schema"] != AUTHORIZATION_PREDICATE_SCHEMA
        or deployment_id != checkpoint["deployment_id"]
        or target_id != rollback_target_id
        or predicate["migration_sha256"] != migration_digest
        or predicate["ledger_v2_sha256"] != ledger_digest
        or predicate["checkpoint_sha256"] != checkpoint_digest
        or fence_digest != _canonical_digest(fence)
        or backup != checkpoint_predicate["backup_checkpoint_sha256"]
        or generation != checkpoint_predicate["deployment_generation"]
        or database_schema
        != checkpoint_predicate["database_schema_version"]
        or storage_schema != checkpoint_predicate["storage_schema_version"]
        or predicate["irreversible_database_migration"] is not False
        or predicate["v2_only_storage_writes"] is not False
        or issued > now + CLOCK_SKEW
        or now >= expires
        or expires <= issued
        or expires - issued > MAX_OPERATION_INTERVAL
        or now - issued > MAX_OPERATION_INTERVAL
        or now.date()
        > TRUST.parse_date(
            checkpoint["rollback_deadline"],
            "checkpoint rollback deadline",
        )
    ):
        raise RollbackError("rollback authorization boundary is invalid")
    subjects = {
        "backup-checkpoint": backup,
        "checkpoint": checkpoint_digest,
        "deployment": _canonical_digest({"deployment_id": deployment_id}),
        "destination": destination_sha256,
        "deployment-state": _canonical_digest(deployment_state),
        "ledger-v2": ledger_digest,
        "migration": migration_digest,
        "restorability-evidence": restorability,
        "rollback-target": _canonical_digest(
            {
                "deployment_id": deployment_id,
                "rollback_target_id": target_id,
            }
        ),
        "v1-ledger": migration["rollback"]["v1_ledger_raw_sha256"],
        "writer-fence": fence_digest,
    }
    try:
        verified = TRUST.verify_attestation(
            attestation,
            policy=policy,
            role="rollback-authorization",
            predicate_type=policy["predicate_types"][
                "rollback_authorization"
            ],
            subjects=dict(sorted(subjects.items())),
            today=now.date(),
        )
        authority = TRUST.policy_authority(
            policy,
            key_id=verified["key_id"],
            role="rollback-authorization",
            today=now.date(),
        )
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error
    if (
        verified["key_id"] == fence["key_id"]
        or verified["key_id"] == checkpoint["attestation"]["key_id"]
        or authority["operator_id"] == fence_authority["operator_id"]
        or authority["trust_domain"] == fence_authority["trust_domain"]
        or authority["operator_id"] == checkpoint_authority["operator_id"]
        or authority["trust_domain"] == checkpoint_authority["trust_domain"]
        or TRUST.parse_date(
            verified["issued_on"],
            "authorization issued_on",
        )
        != issued.date()
        or TRUST.parse_date(
            verified["expires_on"],
            "authorization expires_on",
        )
        != expires.date()
    ):
        raise RollbackError(
            "rollback authorization is not independent or current"
        )
    normalized = dict(verified)
    normalized["predicate"] = {
        "authorization_id": authorization_id,
        "backup_checkpoint_sha256": backup,
        "checkpoint_sha256": checkpoint_digest,
        "database_schema_version": database_schema,
        "deployment_generation": generation,
        "deployment_id": deployment_id,
        "destination_id": destination_id,
        "destination_sha256": destination_sha256,
        "expires_at": _format_timestamp(expires),
        "irreversible_database_migration": False,
        "issued_at": _format_timestamp(issued),
        "ledger_v2_sha256": ledger_digest,
        "migration_sha256": migration_digest,
        "restorability_evidence_sha256": restorability,
        "rollback_target_id": target_id,
        "schema": AUTHORIZATION_PREDICATE_SCHEMA,
        "storage_schema_version": storage_schema,
        "v2_only_storage_writes": False,
        "writer_fence_sha256": fence_digest,
    }
    if _canonical_digest(normalized) != _canonical_digest(attestation):
        raise RollbackError("normalized rollback authorization changed")
    return normalized, authority


def _derive(
    *,
    migration_value: object,
    ledger_value: object,
    authorization_value: object,
    writer_fence_value: object,
    policy: Mapping[str, Any],
    policy_path: Path,
    verifier_registry_path: Path,
    rollback_target_id: str,
    now: datetime,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        migration = MIGRATION.validate_final_result(migration_value)
    except MIGRATION.MigrationError as error:
        raise RollbackError("migration result is invalid") from error
    try:
        if injected_policy:
            ledger = LEDGER_V2.validate_test_result(
                ledger_value,
                policy_path=policy_path,
                today=now.date(),
                verifier_registry_path=verifier_registry_path,
            )
        else:
            ledger = LEDGER_V2.validate_final_result(ledger_value)
    except LEDGER_V2.ProductionLedgerV2Error as error:
        raise RollbackError("ledger v2 result is invalid") from error
    compatibility = _mapping(
        ledger["compatibility"],
        "ledger v2 compatibility",
    )
    if (
        compatibility["migration_sha256"] != _canonical_digest(migration)
        or compatibility["checkpoint_embedded"] is not True
        or compatibility["checkpoint_status"] != "verified"
        or compatibility["checkpoint_verified"] is not True
        or compatibility["semantic_replay_eligible"] is not True
        or compatibility["v1_replay_eligible"] is not False
        or compatibility["rollback_authorized"] is not False
        or compatibility["rollback_authorization_required"] is not True
        or ledger["production_candidate"] is not False
        or ledger["bundle"]["scopes"] != {}
        or ledger["bundle"]["provider_inputs"]["derived"][
            "qualified_input_classes"
        ]
        != []
    ):
        raise RollbackError("ledger v2 is not semantically replayable")
    try:
        checkpoint_status, checkpoint = (
            CHECKPOINT_STATUS.verify_checkpoint(
                migration=migration,
                current_policy=policy,
                at=now.date(),
                registry_path=verifier_registry_path,
            )
        )
    except CHECKPOINT_STATUS.CheckpointStatusError as error:
        raise RollbackError("migration checkpoint is not verified") from error
    if (
        checkpoint_status["checkpoint_attestation_sha256"]
        != compatibility["checkpoint_attestation_sha256"]
        or checkpoint_status["deployment_id"]
        != compatibility["deployment_id"]
    ):
        raise RollbackError("ledger checkpoint compatibility changed")
    _current_revocation_allows(
        current_policy=policy,
        checkpoint=checkpoint,
        now=now,
    )
    fence, fence_authority = _writer_fence(
        writer_fence_value,
        checkpoint=checkpoint,
        policy=policy,
        now=now,
    )
    authorization, _ = _authorization(
        authorization_value,
        migration=migration,
        ledger=ledger,
        checkpoint=checkpoint,
        fence=fence,
        checkpoint_authority=checkpoint["authority"],
        fence_authority=fence_authority,
        policy=policy,
        rollback_target_id=rollback_target_id,
        now=now,
    )
    result = {
        "authorization": authorization,
        "checkpoint": checkpoint["attestation"],
        "derived": {
            "authorization_id": authorization["predicate"][
                "authorization_id"
            ],
            "authorization_sha256": _canonical_digest(authorization),
            "authorized": True,
            "checkpoint_sha256": _canonical_digest(
                checkpoint["attestation"]
            ),
            "deployment_id": checkpoint["deployment_id"],
            "destination_id": authorization["predicate"][
                "destination_id"
            ],
            "destination_sha256": authorization["predicate"][
                "destination_sha256"
            ],
            "ledger_v2_sha256": _canonical_digest(ledger),
            "migration_sha256": _canonical_digest(migration),
            "rollback_target_id": rollback_target_id,
            "v1_ledger_raw_sha256": migration["rollback"][
                "v1_ledger_raw_sha256"
            ],
            "writer_fence_sha256": _canonical_digest(fence),
        },
        "schema": RESULT_SCHEMA,
        "source": source_hashes(),
        "writer_fence": fence,
    }
    if len(TRUST.canonical_bytes(result)) + 1 > ROLLBACK_DOCUMENT_MAX_BYTES:
        raise RollbackError("rollback verification result is too large")
    return result


def _verify_with_policy(
    *,
    migration: Any,
    ledger_v2: Any,
    authorization: Any,
    writer_fence: Any,
    policy_path: Path,
    verifier_registry_path: Path,
    rollback_target_id: str,
    now: datetime,
    injected_policy: bool,
) -> tuple[dict[str, Any], bytes]:
    current = _normalize_now(now)
    try:
        migration_value = TRUST.verify_loaded_document(
            migration,
            "migration result",
            maximum_bytes=MIGRATION.MIGRATION_MAX_BYTES,
        )
        ledger_value = TRUST.verify_loaded_document(
            ledger_v2,
            "ledger v2 result",
            maximum_bytes=LEDGER_V2.LEDGER_RESULT_MAX_BYTES,
        )
        authorization_value = TRUST.verify_loaded_document(
            authorization,
            "rollback authorization",
            maximum_bytes=MIGRATION.CHECKPOINT_MAX_BYTES,
        )
        writer_fence_value = TRUST.verify_loaded_document(
            writer_fence,
            "writer fence",
            maximum_bytes=MIGRATION.CHECKPOINT_MAX_BYTES,
        )
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error
    try:
        policy, _ = TRUST.load_policy(
            policy_path,
            today=current.date(),
        )
    except TRUST.TrustPolicyError as error:
        raise RollbackError(str(error)) from error
    result = _derive(
        migration_value=migration_value,
        ledger_value=ledger_value,
        authorization_value=authorization_value,
        writer_fence_value=writer_fence_value,
        policy=policy,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        rollback_target_id=_identifier(
            rollback_target_id,
            "rollback target ID",
        ),
        now=current,
        injected_policy=injected_policy,
    )
    payload = MIGRATION._decode(
        migration_value["rollback"]["v1_ledger_bytes_base64"],
        "migration v1 ledger bytes",
        maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
    )
    if TRUST.sha256_bytes(payload) != result["derived"][
        "v1_ledger_raw_sha256"
    ]:
        raise RollbackError("exact v1 replay bytes changed")
    return result, payload


def _read_owner_only_bytes(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
) -> bytes:
    if not path.is_absolute():
        raise RollbackError(f"{label} path must be absolute")
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or not 1 <= details.st_size <= maximum_bytes
        ):
            raise RollbackError(f"{label} ownership or size is unsafe")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(
                descriptor,
                min(65536, maximum_bytes + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if not 1 <= len(payload) <= maximum_bytes:
            raise RollbackError(f"{label} size is invalid")
        return bytes(payload)
    except RollbackError:
        raise
    except OSError as error:
        raise RollbackError(f"{label} is unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _existing_receipt(
    *,
    receipt_path: Path,
    output: Path,
    payload: bytes,
    expected: Mapping[str, Any],
    fence: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    receipt_bytes = _read_owner_only_bytes(
        receipt_path,
        label="rollback receipt",
        maximum_bytes=MIGRATION.CHECKPOINT_MAX_BYTES,
    )
    try:
        receipt = TRUST.strict_json_loads(receipt_bytes)
    except TRUST.TrustPolicyError as error:
        raise RollbackError("rollback receipt is invalid") from error
    receipt_map = _validate_receipt(
        receipt,
        expected=expected,
        fence=fence,
        now=now,
        label="rollback receipt",
    )
    if not output.exists() or output.is_symlink():
        raise RollbackError("rollback receipt exists without safe output")
    if (
        _read_owner_only_bytes(
            output,
            label="rollback output",
            maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
        )
        != payload
    ):
        raise RollbackError("rollback output differs from the receipt")
    return receipt_map


def _validate_receipt(
    value: object,
    *,
    expected: Mapping[str, Any],
    fence: Mapping[str, Any],
    now: datetime,
    label: str,
) -> dict[str, Any]:
    receipt_map = dict(_mapping(value, label))
    _exact_keys(
        receipt_map,
        {
            "authorization_id",
            "authorization_sha256",
            "completed_at",
            "deployment_id",
            "destination_id",
            "destination_sha256",
            "fence_sha256",
            "output_raw_sha256",
            "rollback_target_id",
            "schema",
            "status",
        },
        label,
    )
    if (
        receipt_map["schema"] != RECEIPT_SCHEMA
        or receipt_map["status"] != "replayed"
        or any(
            receipt_map[key] != expected[key]
            for key in (
                "authorization_id",
                "authorization_sha256",
                "deployment_id",
                "destination_id",
                "destination_sha256",
                "fence_sha256",
                "output_raw_sha256",
                "rollback_target_id",
            )
        )
    ):
        raise RollbackError("rollback receipt binding changed")
    completed_at = _timestamp(
        receipt_map["completed_at"],
        "rollback receipt completed_at",
    )
    if (
        completed_at
        < _timestamp(
            fence["observed_at"],
            "writer fence observed_at",
        )
        or completed_at
        >= _timestamp(
            fence["expires_at"],
            "writer fence expires_at",
        )
        or completed_at > _normalize_now(now) + CLOCK_SKEW
    ):
        raise RollbackError("rollback receipt completion time is invalid")
    return receipt_map


def _publish(
    *,
    result: Mapping[str, Any],
    payload: bytes,
    state_adapter: RollbackStateAdapter,
    now: datetime,
) -> dict[str, Any]:
    derived = result["derived"]
    try:
        destination_value = state_adapter.resolve_destination(
            deployment_id=derived["deployment_id"],
            rollback_target_id=derived["rollback_target_id"],
        )
    except Exception as error:
        raise RollbackError(
            "rollback destination could not be resolved"
        ) from error
    destination = dict(
        _mapping(destination_value, "rollback destination")
    )
    _exact_keys(
        destination,
        {
            "destination_id",
            "output_path",
            "receipt_path",
            "schema",
        },
        "rollback destination",
    )
    destination_id = _identifier(
        destination["destination_id"],
        "rollback destination ID",
    )
    output_text = _text(
        destination["output_path"],
        "rollback output path",
    )
    receipt_text = _text(
        destination["receipt_path"],
        "rollback receipt path",
    )
    output = Path(output_text)
    receipt_path = Path(receipt_text)
    if (
        destination["schema"] != DESTINATION_SCHEMA
        or destination_id != derived["destination_id"]
        or _canonical_digest(destination) != derived["destination_sha256"]
        or not output.is_absolute()
        or not receipt_path.is_absolute()
        or str(output) != output_text
        or str(receipt_path) != receipt_text
        or ".." in output.parts
        or ".." in receipt_path.parts
        or output == receipt_path
    ):
        raise RollbackError("rollback destination is invalid")
    expected_receipt = {
        "authorization_id": derived["authorization_id"],
        "authorization_sha256": derived["authorization_sha256"],
        "deployment_id": derived["deployment_id"],
        "destination_id": destination_id,
        "destination_sha256": derived["destination_sha256"],
        "fence_sha256": derived["writer_fence_sha256"],
        "output_raw_sha256": derived["v1_ledger_raw_sha256"],
        "rollback_target_id": derived["rollback_target_id"],
    }
    fence_predicate = result["writer_fence"]["predicate"]
    try:
        context = state_adapter.hold_authorization(
            authorization_id=derived["authorization_id"],
            authorization_sha256=derived["authorization_sha256"],
            deployment_id=derived["deployment_id"],
            destination_id=destination_id,
            destination_sha256=derived["destination_sha256"],
            fence=fence_predicate,
            rollback_target_id=derived["rollback_target_id"],
            now=now,
        )
    except Exception as error:
        raise RollbackError(
            "deployment-wide rollback state could not be claimed"
        ) from error
    with _held_claim(context) as claim_value:
        claim = _mapping(claim_value, "rollback state claim")
        _exact_keys(
            claim,
            {
                "authorization_id",
                "authorization_sha256",
                "deployment_id",
                "destination_id",
                "destination_sha256",
                "lease_epoch",
                "lease_id",
                "lease_state_sha256",
                "receipt",
                "rollback_target_id",
                "status",
            },
            "rollback state claim",
        )
        if any(
            claim[key] != expected
            for key, expected in {
                "authorization_id": derived["authorization_id"],
                "authorization_sha256": derived["authorization_sha256"],
                "deployment_id": derived["deployment_id"],
                "destination_id": destination_id,
                "destination_sha256": derived["destination_sha256"],
                "lease_epoch": fence_predicate["lease_epoch"],
                "lease_id": fence_predicate["lease_id"],
                "lease_state_sha256": fence_predicate[
                    "lease_state_sha256"
                ],
                "rollback_target_id": derived["rollback_target_id"],
            }.items()
        ):
            raise RollbackError("deployment-wide rollback claim changed")
        if claim["status"] == "claimed":
            if claim["receipt"] is not None:
                raise RollbackError(
                    "deployment-wide rollback claim is invalid"
                )
            if (
                output.exists()
                or output.is_symlink()
                or receipt_path.exists()
                or receipt_path.is_symlink()
            ):
                raise RollbackError(
                    "local rollback artifacts exist without shared publication"
                )
            try:
                publication_value = state_adapter.begin_publication(
                    claim=claim,
                )
            except Exception as error:
                raise RollbackError(
                    "deployment-wide rollback publication could not begin"
                ) from error
            publication = _mapping(
                publication_value,
                "rollback publication claim",
            )
            _exact_keys(
                publication,
                set(claim),
                "rollback publication claim",
            )
            if (
                any(
                    publication[key] != claim[key]
                    for key in claim
                    if key not in {"receipt", "status"}
                )
                or publication["status"] != "publishing"
                or publication["receipt"] is not None
            ):
                raise RollbackError(
                    "deployment-wide rollback publication claim changed"
                )
            claim = publication
        if claim["status"] not in {"completed", "publishing"}:
            raise RollbackError("deployment-wide rollback claim is invalid")
        existing = _existing_receipt(
            receipt_path=receipt_path,
            output=output,
            payload=payload,
            expected=expected_receipt,
            fence=fence_predicate,
            now=now,
        )
        if claim["status"] == "completed":
            remote_receipt = _validate_receipt(
                claim["receipt"],
                expected=expected_receipt,
                fence=fence_predicate,
                now=now,
                label="completed rollback receipt",
            )
            if output.exists() or output.is_symlink():
                if (
                    _read_owner_only_bytes(
                        output,
                        label="rollback output",
                        maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
                    )
                    != payload
                ):
                    raise RollbackError(
                        "completed rollback output digest changed"
                    )
            else:
                try:
                    TRUST.write_owner_only_bytes(
                        output,
                        payload,
                        maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
                    )
                except TRUST.TrustPolicyError as error:
                    raise RollbackError(str(error)) from error
            if receipt_path.exists() or receipt_path.is_symlink():
                existing = _existing_receipt(
                    receipt_path=receipt_path,
                    output=output,
                    payload=payload,
                    expected=expected_receipt,
                    fence=fence_predicate,
                    now=now,
                )
                if existing != remote_receipt:
                    raise RollbackError(
                        "local and deployment-wide receipts differ"
                    )
            else:
                try:
                    TRUST.write_owner_only(
                        receipt_path,
                        remote_receipt,
                        maximum_bytes=MIGRATION.CHECKPOINT_MAX_BYTES,
                    )
                except TRUST.TrustPolicyError as error:
                    raise RollbackError(str(error)) from error
            return {
                **dict(result),
                "replay": {
                    "receipt": remote_receipt,
                    "status": (
                        "already-replayed"
                        if existing is not None
                        else "recovered-completed-replay"
                    ),
                },
            }
        if claim["status"] != "publishing" or claim["receipt"] is not None:
            raise RollbackError("deployment-wide rollback claim is invalid")
        publish_now = _normalize_now(now)
        if (
            publish_now
            >= _timestamp(
                fence_predicate["expires_at"],
                "writer fence expires_at",
            )
        ):
            raise RollbackError("writer fence expired before publication")
        if existing is not None:
            try:
                state_adapter.complete_authorization(
                    claim=claim,
                    receipt=existing,
                )
            except Exception as error:
                raise RollbackError(
                    "deployment-wide rollback completion failed"
                ) from error
            return {
                **dict(result),
                "replay": {
                    "receipt": existing,
                    "status": "recovered-shared-completion",
                },
            }
        if output.exists() or output.is_symlink():
            if (
                _read_owner_only_bytes(
                    output,
                    label="rollback output",
                    maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
                )
                != payload
            ):
                raise RollbackError("existing rollback output differs")
            replay_status = "recovered-output"
        else:
            try:
                TRUST.write_owner_only_bytes(
                    output,
                    payload,
                    maximum_bytes=MIGRATION.V1_INPUT_MAX_BYTES,
                )
            except TRUST.TrustPolicyError as error:
                raise RollbackError(str(error)) from error
            replay_status = "replayed"
        receipt = {
            **expected_receipt,
            "completed_at": _format_timestamp(publish_now),
            "schema": RECEIPT_SCHEMA,
            "status": "replayed",
        }
        if receipt_path.exists() or receipt_path.is_symlink():
            existing = _existing_receipt(
                receipt_path=receipt_path,
                output=output,
                payload=payload,
                expected=expected_receipt,
                fence=fence_predicate,
                now=now,
            )
            if existing != receipt:
                raise RollbackError("existing rollback receipt differs")
        else:
            try:
                TRUST.write_owner_only(
                    receipt_path,
                    receipt,
                    maximum_bytes=MIGRATION.CHECKPOINT_MAX_BYTES,
                )
            except TRUST.TrustPolicyError as error:
                raise RollbackError(str(error)) from error
        try:
            state_adapter.complete_authorization(
                claim=claim,
                receipt=receipt,
            )
        except Exception as error:
            raise RollbackError(
                "deployment-wide rollback completion failed"
            ) from error
        return {
            **dict(result),
            "replay": {"receipt": receipt, "status": replay_status},
        }


def replay_exact_v1(
    *,
    migration: Any,
    ledger_v2: Any,
    authorization: Any,
    writer_fence: Any,
    rollback_target_id: str,
) -> dict[str, Any]:
    del (
        migration,
        ledger_v2,
        authorization,
        writer_fence,
        rollback_target_id,
    )
    raise RollbackError(
        "no production shared-CAS rollback adapter is configured; "
        "the rollback boundary remains fail-closed"
    )


def replay_test_exact_v1(
    *,
    migration: Any,
    ledger_v2: Any,
    authorization: Any,
    writer_fence: Any,
    rollback_target_id: str,
    policy_path: Path,
    verifier_registry_path: Path,
    now: datetime,
    state_adapter: RollbackStateAdapter,
) -> dict[str, Any]:
    """Exercise injected trust and shared-CAS fixtures; never use in release."""
    current = _normalize_now(now)
    result, payload = _verify_with_policy(
        migration=migration,
        ledger_v2=ledger_v2,
        authorization=authorization,
        writer_fence=writer_fence,
        policy_path=policy_path,
        verifier_registry_path=verifier_registry_path,
        rollback_target_id=rollback_target_id,
        now=current,
        injected_policy=True,
    )
    return _publish(
        result=result,
        payload=payload,
        state_adapter=state_adapter,
        now=current,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse rollback until a production shared-CAS lease adapter "
            "is configured."
        )
    )
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--ledger-v2", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--writer-fence", type=Path, required=True)
    parser.add_argument("--rollback-target-id", required=True)
    arguments = parser.parse_args(argv)
    del arguments
    print(
        "production rollback error: no production shared-CAS rollback "
        "adapter is configured",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
