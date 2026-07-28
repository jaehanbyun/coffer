from __future__ import annotations

import base64
import importlib.util
import json
import sys
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "production-promotion"
SOURCE = HARNESS / "rollback.py"
INPUT_TEST_SOURCE = ROOT / "tests" / "test_production_promotion_input_lineage.py"
CURRENT = ROOT / "work" / "production-promotion"


def load(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


rollback = load("coffer_test_production_rollback", SOURCE)
input_test = load("coffer_rollback_fixture_helpers", INPUT_TEST_SOURCE)
trust = rollback.TRUST
registry = rollback.CHECKPOINT_STATUS.REGISTRY
TODAY = date(2026, 7, 28)
NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)
EXPIRES = "2026-08-04"
TARGET_ID = "controller-1-ledger-v1"
DESTINATION_ID = "controller-1-production-ledger-v1"


def destination_descriptor(root: Path) -> dict[str, str]:
    return {
        "destination_id": DESTINATION_ID,
        "output_path": str((root / "replayed-v1.json").resolve()),
        "receipt_path": str((root / "rollback-receipt.json").resolve()),
        "schema": rollback.DESTINATION_SCHEMA,
    }


def loaded(tmp_path: Path, name: str, value: object) -> Any:
    path = tmp_path / name
    input_test.write_json(path, value, private=True)
    return trust.load_private_json(path, name)


def loaded_bytes(tmp_path: Path, name: str, value: bytes) -> Any:
    path = tmp_path / name
    path.write_bytes(value)
    path.chmod(0o600)
    return trust.load_private_json(path, name)


def sign_at(
    predicate: dict[str, Any],
    *,
    private_key: Any,
    key_id: str,
    role: str,
    predicate_type: str,
    subjects: dict[str, str],
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    attestation: dict[str, Any] = {
        "algorithm": "ed25519",
        "expires_on": expires_at.date().isoformat(),
        "issued_on": issued_at.date().isoformat(),
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


def build_test_registry(
    tmp_path: Path,
    *,
    policy_path: Path,
    authority_key_id: str = "fixture-migration-checkpoint",
) -> tuple[Path, dict[str, Any]]:
    metadata = registry.bundle_metadata(
        "coffer.checkpoint-verifier.v2.0.0"
    )
    value = {
        "entries": [
            {
                "accepted_policy_raw_sha256": trust.sha256_bytes(
                    policy_path.read_bytes()
                ),
                "bundle_id": metadata["bundle_id"],
                "bundle_sha256": metadata["bundle_sha256"],
                "checkpoint_authority_key_ids": [authority_key_id],
                "entry_point": metadata["entry_point"],
                "manifest_sha256": metadata["manifest_sha256"],
                "status": "active",
                "support_ends_on": "2027-01-31",
            }
        ],
        "schema": registry.REGISTRY_SCHEMA,
    }
    path = tmp_path / "verifier-registry.json"
    input_test.write_json(path, value)
    return path, metadata


def checkpoint_attestation(
    *,
    signing_keys: Any,
    policy: dict[str, Any],
    policy_bytes: bytes,
    ledger_bytes: bytes,
    release_bytes: bytes,
    bundle_metadata: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy_value = trust.strict_json_loads(policy_bytes)
    predicate = {
        "archival_valid_until": EXPIRES,
        "backup_checkpoint_sha256": f"sha256:{'a' * 64}",
        "database_schema_version": "0007_artifact_projection",
        "deployment_generation": "generation-42",
        "deployment_id": "fixture-deployment-42",
        "legacy_evidence_inventory_sha256": f"sha256:{'b' * 64}",
        "observed_on": TODAY.isoformat(),
        "rollback_deadline": EXPIRES,
        "schema": rollback.CHECKPOINT_PREDICATE_SCHEMA,
        "storage_schema_version": "oci-layout-v1",
        "trust_policy_canonical_sha256": trust.canonical_sha256(
            policy_value
        ),
        "trust_policy_raw_sha256": trust.sha256_bytes(policy_bytes),
        "v1_ledger_raw_sha256": trust.sha256_bytes(ledger_bytes),
        "v1_release_raw_sha256": trust.sha256_bytes(release_bytes),
        "verifier_bundle_id": bundle_metadata["bundle_id"],
        "verifier_bundle_sha256": bundle_metadata["bundle_sha256"],
    }
    if overrides is not None:
        predicate.update(overrides)
    deployment_state = rollback._deployment_state(
        deployment_generation=predicate["deployment_generation"],
        database_schema_version=predicate["database_schema_version"],
        storage_schema_version=predicate["storage_schema_version"],
    )
    return input_test.sign(
        predicate,
        private_key=signing_keys.migration_checkpoint,
        key_id="fixture-migration-checkpoint",
        role="migration-checkpoint",
        predicate_type=policy["predicate_types"]["migration_checkpoint"],
        subjects={
            "backup-checkpoint": predicate["backup_checkpoint_sha256"],
            "deployment": trust.canonical_sha256(
                {"deployment_id": predicate["deployment_id"]}
            ),
            "deployment-state": trust.canonical_sha256(deployment_state),
            "legacy-evidence-inventory": predicate[
                "legacy_evidence_inventory_sha256"
            ],
            "trust-policy": predicate["trust_policy_raw_sha256"],
            "v1-ledger": predicate["v1_ledger_raw_sha256"],
            "v1-release": predicate["v1_release_raw_sha256"],
            "verifier-bundle": predicate["verifier_bundle_sha256"],
        },
    )


def writer_fence_attestation(
    *,
    signing_keys: Any,
    policy: dict[str, Any],
    checkpoint: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint_predicate = checkpoint["predicate"]
    expires_at = NOW + timedelta(minutes=5)
    predicate = {
        "active": True,
        "active_uploads": 0,
        "active_writers": 0,
        "adapter_id": "fixture-shared-cas-fence",
        "database_schema_version": checkpoint_predicate[
            "database_schema_version"
        ],
        "deployment_generation": checkpoint_predicate[
            "deployment_generation"
        ],
        "deployment_id": checkpoint_predicate["deployment_id"],
        "expires_at": rollback._format_timestamp(expires_at),
        "lease_epoch": 42,
        "lease_id": "fixture-held-lease-42",
        "lease_state_sha256": f"sha256:{'c' * 64}",
        "observed_at": rollback._format_timestamp(NOW),
        "schema": rollback.WRITER_FENCE_PREDICATE_SCHEMA,
        "storage_schema_version": checkpoint_predicate[
            "storage_schema_version"
        ],
        "unknown_listeners": 0,
    }
    if overrides is not None:
        predicate.update(overrides)
    deployment_state = rollback._deployment_state(
        deployment_generation=predicate["deployment_generation"],
        database_schema_version=predicate["database_schema_version"],
        storage_schema_version=predicate["storage_schema_version"],
    )
    adapter = policy["writer_fence_adapters"][predicate["adapter_id"]]
    return sign_at(
        predicate,
        private_key=signing_keys.writer_fence,
        key_id="fixture-writer-fence",
        role="writer-fence",
        predicate_type=policy["predicate_types"]["writer_fence"],
        subjects={
            "adapter": trust.canonical_sha256(adapter),
            "deployment": trust.canonical_sha256(
                {"deployment_id": predicate["deployment_id"]}
            ),
            "deployment-state": trust.canonical_sha256(deployment_state),
            "lease": trust.canonical_sha256(
                {
                    "lease_epoch": predicate["lease_epoch"],
                    "lease_id": predicate["lease_id"],
                }
            ),
            "lease-state": predicate["lease_state_sha256"],
        },
        issued_at=NOW,
        expires_at=expires_at,
    )


def authorization_attestation(
    *,
    signing_keys: Any,
    policy: dict[str, Any],
    migration: dict[str, Any],
    ledger: dict[str, Any],
    checkpoint: dict[str, Any],
    writer_fence: dict[str, Any],
    destination: dict[str, str],
    rollback_target_id: str = TARGET_ID,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checkpoint_predicate = checkpoint["predicate"]
    expires_at = NOW + timedelta(minutes=5)
    predicate = {
        "authorization_id": "fixture-rollback-authorization-42",
        "backup_checkpoint_sha256": checkpoint_predicate[
            "backup_checkpoint_sha256"
        ],
        "checkpoint_sha256": trust.canonical_sha256(checkpoint),
        "database_schema_version": checkpoint_predicate[
            "database_schema_version"
        ],
        "deployment_generation": checkpoint_predicate[
            "deployment_generation"
        ],
        "deployment_id": checkpoint_predicate["deployment_id"],
        "destination_id": destination["destination_id"],
        "destination_sha256": trust.canonical_sha256(destination),
        "expires_at": rollback._format_timestamp(expires_at),
        "irreversible_database_migration": False,
        "issued_at": rollback._format_timestamp(NOW),
        "ledger_v2_sha256": trust.canonical_sha256(ledger),
        "migration_sha256": trust.canonical_sha256(migration),
        "restorability_evidence_sha256": f"sha256:{'d' * 64}",
        "rollback_target_id": rollback_target_id,
        "schema": rollback.AUTHORIZATION_PREDICATE_SCHEMA,
        "storage_schema_version": checkpoint_predicate[
            "storage_schema_version"
        ],
        "v2_only_storage_writes": False,
        "writer_fence_sha256": trust.canonical_sha256(writer_fence),
    }
    if overrides is not None:
        predicate.update(overrides)
    deployment_state = rollback._deployment_state(
        deployment_generation=predicate["deployment_generation"],
        database_schema_version=predicate["database_schema_version"],
        storage_schema_version=predicate["storage_schema_version"],
    )
    return sign_at(
        predicate,
        private_key=signing_keys.rollback_authorization,
        key_id="fixture-rollback-authorization",
        role="rollback-authorization",
        predicate_type=policy["predicate_types"]["rollback_authorization"],
        subjects={
            "backup-checkpoint": predicate["backup_checkpoint_sha256"],
            "checkpoint": predicate["checkpoint_sha256"],
            "deployment": trust.canonical_sha256(
                {"deployment_id": predicate["deployment_id"]}
            ),
            "destination": predicate["destination_sha256"],
            "deployment-state": trust.canonical_sha256(deployment_state),
            "ledger-v2": predicate["ledger_v2_sha256"],
            "migration": predicate["migration_sha256"],
            "restorability-evidence": predicate[
                "restorability_evidence_sha256"
            ],
            "rollback-target": trust.canonical_sha256(
                {
                    "deployment_id": predicate["deployment_id"],
                    "rollback_target_id": predicate[
                        "rollback_target_id"
                    ],
                }
            ),
            "v1-ledger": migration["rollback"]["v1_ledger_raw_sha256"],
            "writer-fence": predicate["writer_fence_sha256"],
        },
        issued_at=NOW,
        expires_at=expires_at,
    )


@dataclass
class Bundle:
    migration: dict[str, Any]
    ledger: dict[str, Any]
    checkpoint: dict[str, Any]
    writer_fence: dict[str, Any]
    authorization: dict[str, Any]
    destination: dict[str, str]
    policy_path: Path
    registry_path: Path
    signing_keys: Any


def rollback_bundle(tmp_path: Path) -> Bundle:
    signing_keys = input_test.keys()
    policy_value = input_test.synthetic_policy(
        signing_keys,
        environment="production",
    )
    policy_path, policy, _ = input_test.policy_file(tmp_path, policy_value)
    registry_path, metadata = build_test_registry(
        tmp_path,
        policy_path=policy_path,
    )
    ledger_bytes = (CURRENT / "promotion-ledger.json").read_bytes()
    release_bytes = (CURRENT / "release-readiness.json").read_bytes()
    checkpoint = checkpoint_attestation(
        signing_keys=signing_keys,
        policy=policy,
        policy_bytes=policy_path.read_bytes(),
        ledger_bytes=ledger_bytes,
        release_bytes=release_bytes,
        bundle_metadata=metadata,
    )
    migration = rollback.MIGRATION.compile_migration(
        v1_ledger=loaded_bytes(tmp_path, "ledger-v1.json", ledger_bytes),
        release_readiness=loaded_bytes(
            tmp_path,
            "release-v1.json",
            release_bytes,
        ),
        checkpoint=loaded(tmp_path, "checkpoint.json", checkpoint),
        checkpoint_policy=loaded_bytes(
            tmp_path,
            "checkpoint-policy.json",
            policy_path.read_bytes(),
        ),
    )
    providers = rollback.LEDGER_V2.PROVIDER_INPUTS.compile_test_result(
        migration=loaded(
            tmp_path,
            "migration-for-providers.json",
            migration,
        ),
        inputs={},
        policy_path=policy_path,
        today=TODAY,
    )
    ledger = rollback.LEDGER_V2.compile_test_result(
        provider_inputs=loaded(
            tmp_path,
            "provider-inputs.json",
            providers,
        ),
        scopes={},
        policy_path=policy_path,
        today=TODAY,
        verifier_registry_path=registry_path,
    )
    writer_fence = writer_fence_attestation(
        signing_keys=signing_keys,
        policy=policy,
        checkpoint=checkpoint,
    )
    destination = destination_descriptor(tmp_path)
    authorization = authorization_attestation(
        signing_keys=signing_keys,
        policy=policy,
        migration=migration,
        ledger=ledger,
        checkpoint=checkpoint,
        writer_fence=writer_fence,
        destination=destination,
    )
    return Bundle(
        migration=migration,
        ledger=ledger,
        checkpoint=checkpoint,
        writer_fence=writer_fence,
        authorization=authorization,
        destination=destination,
        policy_path=policy_path,
        registry_path=registry_path,
        signing_keys=signing_keys,
    )


class FixtureSharedCAS:
    def __init__(self, destination_root: Path) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.active = True
        self.destination = destination_descriptor(destination_root)

    @contextmanager
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
    ) -> Iterator[Mapping[str, Any]]:
        if (
            not self.active
            or fence["active"] is not True
            or fence["active_writers"] != 0
            or fence["active_uploads"] != 0
            or fence["unknown_listeners"] != 0
            or rollback._timestamp(
                fence["expires_at"],
                "fixture lease expiry",
            )
            <= now
        ):
            raise RuntimeError("fixture shared lease is not held")
        key = (deployment_id, authorization_id)
        record = self.records.get(key)
        identity = {
            "authorization_id": authorization_id,
            "authorization_sha256": authorization_sha256,
            "deployment_id": deployment_id,
            "destination_id": destination_id,
            "destination_sha256": destination_sha256,
            "lease_epoch": fence["lease_epoch"],
            "lease_id": fence["lease_id"],
            "lease_state_sha256": fence["lease_state_sha256"],
            "rollback_target_id": rollback_target_id,
        }
        if record is None:
            record = {
                **identity,
                "receipt": None,
                "status": "claimed",
            }
            self.records[key] = record
        elif any(record[name] != value for name, value in identity.items()):
            raise RuntimeError("authorization was already claimed differently")
        yield deepcopy(record)

    def begin_publication(
        self,
        *,
        claim: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        key = (claim["deployment_id"], claim["authorization_id"])
        record = self.records[key]
        if (
            record["status"] != "claimed"
            or record["receipt"] is not None
            or any(
                record[name] != claim[name]
                for name in record
                if name not in {"receipt", "status"}
            )
        ):
            raise RuntimeError("fixture publication state changed")
        record["status"] = "publishing"
        return deepcopy(record)

    def complete_authorization(
        self,
        *,
        claim: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        key = (claim["deployment_id"], claim["authorization_id"])
        record = self.records[key]
        if record["status"] == "completed":
            if record["receipt"] != receipt:
                raise RuntimeError("completion receipt changed")
            return
        if record["status"] != "publishing":
            raise RuntimeError("fixture publication never began")
        record["receipt"] = deepcopy(dict(receipt))
        record["status"] = "completed"

    def resolve_destination(
        self,
        *,
        deployment_id: str,
        rollback_target_id: str,
    ) -> Mapping[str, Any]:
        if (
            deployment_id != "fixture-deployment-42"
            or rollback_target_id != TARGET_ID
        ):
            raise RuntimeError("fixture destination is unknown")
        return deepcopy(self.destination)


class FailFirstCompletionCAS(FixtureSharedCAS):
    def __init__(self, destination_root: Path) -> None:
        super().__init__(destination_root)
        self.fail_completion = True

    def complete_authorization(
        self,
        *,
        claim: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> None:
        if self.fail_completion:
            self.fail_completion = False
            raise RuntimeError("fixture completion outage")
        super().complete_authorization(claim=claim, receipt=receipt)


def replay(
    tmp_path: Path,
    *,
    bundle: Bundle,
    state: FixtureSharedCAS,
    target_id: str = TARGET_ID,
    now: datetime = NOW,
) -> dict[str, Any]:
    return rollback.replay_test_exact_v1(
        migration=loaded(tmp_path, "migration.json", bundle.migration),
        ledger_v2=loaded(tmp_path, "ledger-v2.json", bundle.ledger),
        authorization=loaded(
            tmp_path,
            "authorization.json",
            bundle.authorization,
        ),
        writer_fence=loaded(
            tmp_path,
            "writer-fence.json",
            bundle.writer_fence,
        ),
        rollback_target_id=target_id,
        policy_path=bundle.policy_path,
        verifier_registry_path=bundle.registry_path,
        now=now,
        state_adapter=state,
    )


def test_signed_rollback_replays_exact_v1_and_records_shared_consumption(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    state = FixtureSharedCAS(tmp_path)

    result = replay(tmp_path, bundle=bundle, state=state)

    output = tmp_path / "replayed-v1.json"
    receipt = tmp_path / "rollback-receipt.json"
    assert result["derived"]["authorized"] is True
    assert result["replay"]["status"] == "replayed"
    assert output.read_bytes() == (CURRENT / "promotion-ledger.json").read_bytes()
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert next(iter(state.records.values()))["status"] == "completed"


def test_idempotent_replay_and_missing_local_receipt_recovery(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    state = FixtureSharedCAS(tmp_path)
    first = replay(tmp_path, bundle=bundle, state=state)
    second = replay(tmp_path, bundle=bundle, state=state)
    assert second["replay"]["status"] == "already-replayed"
    assert second["replay"]["receipt"] == first["replay"]["receipt"]

    (tmp_path / "rollback-receipt.json").unlink()
    recovered = replay(tmp_path, bundle=bundle, state=state)
    assert recovered["replay"]["status"] == "recovered-completed-replay"
    assert recovered["replay"]["receipt"] == first["replay"]["receipt"]


def test_signed_destination_binding_prevents_completed_replay_duplication(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    state = FixtureSharedCAS(tmp_path)
    replay(tmp_path, bundle=bundle, state=state)

    alternate = tmp_path / "alternate"
    alternate.mkdir(mode=0o700)
    state.destination = destination_descriptor(alternate)
    with pytest.raises(
        rollback.RollbackError,
        match="rollback destination is invalid",
    ):
        replay(tmp_path, bundle=bundle, state=state)
    assert not (alternate / "replayed-v1.json").exists()
    assert not (alternate / "rollback-receipt.json").exists()
    assert len(state.records) == 1


def test_local_replay_never_bypasses_shared_completion(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    interrupted_state = FailFirstCompletionCAS(tmp_path)

    with pytest.raises(
        rollback.RollbackError,
        match="deployment-wide rollback completion failed",
    ):
        replay(tmp_path, bundle=bundle, state=interrupted_state)
    interrupted_record = next(iter(interrupted_state.records.values()))
    assert interrupted_record["status"] == "publishing"
    assert (tmp_path / "replayed-v1.json").exists()
    assert (tmp_path / "rollback-receipt.json").exists()

    recovered = replay(
        tmp_path,
        bundle=bundle,
        state=interrupted_state,
    )
    assert recovered["replay"]["status"] == "recovered-shared-completion"
    assert next(iter(interrupted_state.records.values()))["status"] == "completed"

    unrecorded_state = FixtureSharedCAS(tmp_path)
    with pytest.raises(
        rollback.RollbackError,
        match="local rollback artifacts exist without shared publication",
    ):
        replay(tmp_path, bundle=bundle, state=unrecorded_state)
    assert next(iter(unrecorded_state.records.values()))["status"] == "claimed"

    unavailable_state = FixtureSharedCAS(tmp_path)
    unavailable_state.active = False
    with pytest.raises(
        rollback.RollbackError,
        match="deployment-wide rollback state could not be claimed",
    ):
        replay(tmp_path, bundle=bundle, state=unavailable_state)
    assert unavailable_state.records == {}


def test_authorization_cannot_be_reused_for_another_target_or_deployment(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    state = FixtureSharedCAS(tmp_path)
    replay(tmp_path, bundle=bundle, state=state)

    with pytest.raises(rollback.RollbackError):
        replay(
            tmp_path,
            bundle=bundle,
            state=state,
            target_id="controller-2-ledger-v1",
        )

    tampered = deepcopy(bundle)
    tampered.migration["checkpoint"]["attestation_raw_sha256"] = (
        f"sha256:{'0' * 64}"
    )
    with pytest.raises(
        rollback.RollbackError,
        match="migration result is invalid",
    ):
        replay(
            tmp_path,
            bundle=tampered,
            state=state,
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"active": False},
        {"active_writers": 1},
        {"active_uploads": 1},
        {"unknown_listeners": 1},
        {"deployment_generation": "generation-43"},
        {"database_schema_version": "0008_irreversible"},
        {"storage_schema_version": "oci-layout-v2"},
        {"expires_at": "2026-07-28T12:06:00Z"},
        {"observed_at": "2026-07-28"},
    ),
)
def test_writer_fence_changes_fail_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    bundle = rollback_bundle(tmp_path)
    policy, _ = trust.load_policy(bundle.policy_path, today=TODAY)
    bundle.writer_fence = writer_fence_attestation(
        signing_keys=bundle.signing_keys,
        policy=policy,
        checkpoint=bundle.checkpoint,
        overrides=overrides,
    )
    bundle.authorization = authorization_attestation(
        signing_keys=bundle.signing_keys,
        policy=policy,
        migration=bundle.migration,
        ledger=bundle.ledger,
        checkpoint=bundle.checkpoint,
        writer_fence=bundle.writer_fence,
        destination=bundle.destination,
    )
    with pytest.raises(rollback.RollbackError):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))


@pytest.mark.parametrize(
    "overrides",
    (
        {"irreversible_database_migration": True},
        {"v2_only_storage_writes": True},
        {"deployment_generation": "generation-43"},
        {"database_schema_version": "0008_irreversible"},
        {"storage_schema_version": "oci-layout-v2"},
        {"expires_at": "2026-07-28T12:06:00Z"},
        {"issued_at": "2026-07-28"},
    ),
)
def test_authorization_boundary_changes_fail_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    bundle = rollback_bundle(tmp_path)
    policy, _ = trust.load_policy(bundle.policy_path, today=TODAY)
    bundle.authorization = authorization_attestation(
        signing_keys=bundle.signing_keys,
        policy=policy,
        migration=bundle.migration,
        ledger=bundle.ledger,
        checkpoint=bundle.checkpoint,
        writer_fence=bundle.writer_fence,
        destination=bundle.destination,
        overrides=overrides,
    )
    with pytest.raises(rollback.RollbackError):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))


def test_checkpoint_policy_and_registry_are_not_self_selected(
    tmp_path: Path,
) -> None:
    bundle = rollback_bundle(tmp_path)
    registry_value = json.loads(bundle.registry_path.read_text())
    registry_value["entries"][0]["accepted_policy_raw_sha256"] = (
        f"sha256:{'f' * 64}"
    )
    input_test.write_json(bundle.registry_path, registry_value)

    with pytest.raises(
        rollback.RollbackError,
        match="ledger v2 result is invalid",
    ):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))


def test_checkpoint_current_revocation_overlay_is_fail_closed(
    tmp_path: Path,
) -> None:
    bundle = rollback_bundle(tmp_path)
    policy_value = json.loads(bundle.policy_path.read_text())
    policy_value["checkpoint_revocations"] = [
        {
            "compromised_since": "2026-07-01",
            "key_id": "fixture-migration-checkpoint",
            "reason": "fixture compromise",
            "revoked_on": TODAY.isoformat(),
        }
    ]
    input_test.write_json(bundle.policy_path, policy_value)

    with pytest.raises(
        rollback.RollbackError,
        match="ledger v2 result is invalid",
    ):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))


def test_partial_v2_missing_checkpoint_and_expired_fence_never_replay(
    tmp_path: Path,
) -> None:
    bundle = rollback_bundle(tmp_path)
    partial = {
        "schema": bundle.ledger["schema"],
        "production_candidate": False,
        "profiles": {},
    }
    bundle.ledger = partial
    with pytest.raises(
        rollback.RollbackError,
        match="ledger v2 result is invalid",
    ):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))

    fresh_path = tmp_path / "fresh"
    fresh_path.mkdir(mode=0o700)
    fresh = rollback_bundle(fresh_path)
    with pytest.raises(rollback.RollbackError):
        replay(
            fresh_path,
            bundle=fresh,
            state=FixtureSharedCAS(fresh_path),
            now=NOW + timedelta(minutes=5),
        )


def test_existing_mismatched_output_or_receipt_is_never_overwritten(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    bundle = rollback_bundle(tmp_path)
    output = tmp_path / "replayed-v1.json"
    output.write_bytes(b"sentinel")
    output.chmod(0o600)

    with pytest.raises(
        rollback.RollbackError,
        match="without shared publication",
    ):
        replay(tmp_path, bundle=bundle, state=FixtureSharedCAS(tmp_path))
    assert output.read_bytes() == b"sentinel"


def test_production_replay_remains_closed_without_shared_cas_adapter(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        rollback.RollbackError,
        match="shared-CAS",
    ):
        rollback.replay_exact_v1(
            migration={},
            ledger_v2={},
            authorization={},
            writer_fence={},
            rollback_target_id=TARGET_ID,
        )
    assert rollback.main(
        [
            "--migration",
            "unused",
            "--ledger-v2",
            "unused",
            "--authorization",
            "unused",
            "--writer-fence",
            "unused",
            "--rollback-target-id",
            TARGET_ID,
        ]
    ) == 2


def test_rollback_modules_import_without_circular_initialization() -> None:
    assert rollback.MIGRATION.SCHEMA == "coffer.production-ledger-migration/v2"
    assert rollback.LEDGER_V2.SCHEMA == "coffer.production-promotion-ledger/v2"
    policy = json.loads((HARNESS / "trust-policy-v2.json").read_text())
    assert policy["predicate_types"]["writer_fence"].endswith(
        "/writer-fence/v2"
    )
