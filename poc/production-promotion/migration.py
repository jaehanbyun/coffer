from __future__ import annotations

import argparse
import base64
import binascii
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
LEDGER_V1_SOURCE = DIRECTORY / "ledger.py"
READINESS_SOURCE = DIRECTORY / "readiness.py"

SCHEMA = "coffer.production-ledger-migration/v2"
V1_LEDGER_SCHEMA = "coffer.production-promotion-ledger/v1"
V1_RELEASE_SCHEMA = "coffer.production-promotion-release-readiness/v1"
V2_LEDGER_SCHEMA = "coffer.production-promotion-ledger/v2"
MAPPING_STATUSES = ("blocked", "pending")
VERIFIER_ID = "coffer.production-ledger-migration/v2.0"
V1_INPUT_MAX_BYTES = 4 * 1024 * 1024
CHECKPOINT_MAX_BYTES = 1024 * 1024
CHECKPOINT_POLICY_MAX_BYTES = 4 * 1024 * 1024
MIGRATION_MAX_BYTES = 16 * 1024 * 1024


class MigrationError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise MigrationError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise MigrationError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise MigrationError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
LEDGER_V1 = _load_module("coffer_production_ledger_v1_for_migration", LEDGER_V1_SOURCE)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise MigrationError(str(error)) from error


def source_hashes() -> dict[str, str]:
    return {
        "ledger_v1_sha256": _sha256(LEDGER_V1_SOURCE),
        "migration_verifier_id": VERIFIER_ID,
        "migration_verifier_sha256": _sha256(Path(__file__).resolve()),
        "readiness_v1_sha256": _sha256(READINESS_SOURCE),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MigrationError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise MigrationError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    try:
        return TRUST.digest(value, label)
    except TRUST.TrustPolicyError as error:
        raise MigrationError(str(error)) from error


def _decode(
    value: object,
    label: str,
    *,
    maximum_bytes: int,
) -> bytes:
    maximum_encoded = ((maximum_bytes + 2) // 3) * 4
    if not isinstance(value, str) or len(value) > maximum_encoded:
        raise MigrationError(f"{label} is invalid")
    try:
        payload = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise MigrationError(f"{label} is invalid") from error
    if not payload or len(payload) > maximum_bytes:
        raise MigrationError(f"{label} size is invalid")
    return payload


def _validate_release(
    value: object,
    *,
    as_of: date,
) -> tuple[dict[str, Any], list[str]]:
    try:
        return LEDGER_V1._validate_release(value, today=as_of)
    except LEDGER_V1.PromotionLedgerError as error:
        raise MigrationError("v1 release readiness is invalid") from error


def _validate_v1_ledger(
    value: object,
    *,
    release: Mapping[str, Any],
    release_raw_sha256: str,
) -> dict[str, Any]:
    ledger = dict(_mapping(value, "v1 ledger"))
    _exact_keys(
        ledger,
        {
            "blocked_gates",
            "blockers",
            "gate_count",
            "gates",
            "passed_gate_count",
            "pending_gates",
            "production_candidate",
            "schema",
            "source",
            "status",
        },
        "v1 ledger",
    )
    if ledger["schema"] != V1_LEDGER_SCHEMA:
        raise MigrationError("v1 ledger schema is invalid")
    if ledger["source"] != LEDGER_V1.source_hashes():
        raise MigrationError("v1 ledger source binding changed")
    gates = ledger["gates"]
    if not isinstance(gates, list) or len(gates) != len(LEDGER_V1.GATE_ORDER):
        raise MigrationError("v1 ledger gate inventory is invalid")
    blocked: list[str] = []
    pending: list[str] = []
    passed = 0
    parsed_gates: list[dict[str, Any]] = []
    for expected_id, raw in zip(LEDGER_V1.GATE_ORDER, gates, strict=True):
        gate = _mapping(raw, f"v1 gate {expected_id}")
        _exact_keys(
            gate,
            {"evidence", "id", "reason", "status"},
            f"v1 gate {expected_id}",
        )
        status = gate["status"]
        if gate["id"] != expected_id or status not in {"blocked", "passed", "pending"}:
            raise MigrationError(f"v1 gate {expected_id} is invalid")
        reason = gate["reason"]
        if (status == "passed" and reason is not None) or (
            status != "passed" and (not isinstance(reason, str) or not reason)
        ):
            raise MigrationError(f"v1 gate {expected_id} reason is invalid")
        evidence = gate["evidence"]
        if evidence is not None:
            evidence_map = _mapping(evidence, f"v1 gate {expected_id} evidence")
            _exact_keys(
                evidence_map,
                {"schema", "sha256"},
                f"v1 gate {expected_id} evidence",
            )
            _digest(
                evidence_map["sha256"],
                f"v1 gate {expected_id} evidence",
            )
        if expected_id == "release_inputs":
            if (
                not isinstance(evidence, Mapping)
                or evidence["schema"] != V1_RELEASE_SCHEMA
                or evidence["sha256"] != release_raw_sha256
            ):
                raise MigrationError("v1 release gate binding changed")
            expected_release_status = (
                "passed" if release["status"] == "candidate-qualified" else "blocked"
            )
            if status != expected_release_status:
                raise MigrationError("v1 release gate disposition changed")
        if status == "blocked":
            blocked.append(expected_id)
        elif status == "pending":
            pending.append(expected_id)
        else:
            passed += 1
        parsed_gates.append(dict(gate))
    expected_status = "blocked" if blocked else ("pending" if pending else "qualified")
    if (
        ledger["blocked_gates"] != blocked
        or ledger["pending_gates"] != pending
        or ledger["passed_gate_count"] != passed
        or ledger["gate_count"] != len(parsed_gates)
        or ledger["status"] != expected_status
        or ledger["production_candidate"] is not (expected_status == "qualified")
        or ledger["blockers"] != release["blockers"]
    ):
        raise MigrationError("v1 ledger aggregate changed")
    return ledger


def _component_mapping(
    release: Mapping[str, Any],
    *,
    release_raw_sha256: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for component in ("ceph", "distribution", "oslo_messaging"):
        legacy = release["components"][component]
        blocked = legacy["status"] == "blocked"
        result[component] = {
            "legacy": {
                "reasons": list(legacy["reasons"]),
                "release_readiness_sha256": release_raw_sha256,
                "revision": legacy["revision"],
                "status": legacy["status"],
                "version": legacy["version"],
            },
            "reason_code": (
                "legacy-explicit-blocker" if blocked else "v2-requalification-required"
            ),
            "status": "blocked" if blocked else "pending",
        }
    return result


def _derive(
    *,
    ledger_bytes: bytes,
    release_bytes: bytes,
    checkpoint_bytes: bytes | None,
    checkpoint_policy_bytes: bytes | None,
) -> dict[str, Any]:
    try:
        ledger_value = TRUST.strict_json_loads(ledger_bytes)
        release_value = TRUST.strict_json_loads(release_bytes)
    except TRUST.TrustPolicyError as error:
        raise MigrationError(str(error)) from error
    release_map = _mapping(release_value, "v1 release readiness")
    try:
        as_of = date.fromisoformat(str(release_map.get("ui_observed_on")))
    except ValueError as error:
        raise MigrationError("v1 release observation is invalid") from error
    release, _ = _validate_release(release_value, as_of=as_of)
    release_raw_sha256 = TRUST.sha256_bytes(release_bytes)
    ledger = _validate_v1_ledger(
        ledger_value,
        release=release,
        release_raw_sha256=release_raw_sha256,
    )
    ledger_raw_sha256 = TRUST.sha256_bytes(ledger_bytes)
    if checkpoint_bytes is None and checkpoint_policy_bytes is None:
        checkpoint = {
            "attestation_bytes_base64": None,
            "attestation_canonical_sha256": None,
            "attestation_raw_sha256": None,
            "present": False,
            "trust_policy_bytes_base64": None,
            "trust_policy_canonical_sha256": None,
            "trust_policy_raw_sha256": None,
        }
    elif checkpoint_bytes is not None and checkpoint_policy_bytes is not None:
        try:
            checkpoint_value = TRUST.strict_json_loads(checkpoint_bytes)
            checkpoint_policy_value = TRUST.strict_json_loads(
                checkpoint_policy_bytes
            )
        except TRUST.TrustPolicyError as error:
            raise MigrationError(
                "migration checkpoint material is invalid"
            ) from error
        checkpoint_map = _mapping(
            checkpoint_value,
            "migration checkpoint",
        )
        checkpoint_policy_map = _mapping(
            checkpoint_policy_value,
            "migration checkpoint trust policy",
        )
        checkpoint = {
            "attestation_bytes_base64": base64.b64encode(checkpoint_bytes).decode(),
            "attestation_canonical_sha256": TRUST.canonical_sha256(checkpoint_map),
            "attestation_raw_sha256": TRUST.sha256_bytes(checkpoint_bytes),
            "present": True,
            "trust_policy_bytes_base64": base64.b64encode(
                checkpoint_policy_bytes
            ).decode(),
            "trust_policy_canonical_sha256": TRUST.canonical_sha256(
                checkpoint_policy_map
            ),
            "trust_policy_raw_sha256": TRUST.sha256_bytes(
                checkpoint_policy_bytes
            ),
        }
    else:
        raise MigrationError(
            "checkpoint and archived trust policy must be supplied together"
        )
    result = {
        "checkpoint": checkpoint,
        "components": _component_mapping(
            release,
            release_raw_sha256=release_raw_sha256,
        ),
        "legacy_gates": {
            gate["id"]: {
                "legacy_evidence": gate["evidence"],
                "legacy_status": gate["status"],
                "v2_default_status": (
                    "blocked" if gate["status"] == "blocked" else "pending"
                ),
            }
            for gate in ledger["gates"]
        },
        "rollback": {
            "mode": "exact-v1-byte-replay-only",
            "projection": "forbidden",
            "v1_ledger_bytes_base64": base64.b64encode(ledger_bytes).decode(),
            "v1_ledger_raw_sha256": ledger_raw_sha256,
        },
        "schema": SCHEMA,
        "source": source_hashes(),
        "source_v1": {
            "ledger_canonical_sha256": TRUST.canonical_sha256(ledger),
            "ledger_raw_sha256": ledger_raw_sha256,
            "ledger_schema": V1_LEDGER_SCHEMA,
            "release_canonical_sha256": TRUST.canonical_sha256(release),
            "release_observed_on": as_of.isoformat(),
            "release_raw_sha256": release_raw_sha256,
            "release_schema": V1_RELEASE_SCHEMA,
            "release_bytes_base64": base64.b64encode(release_bytes).decode(),
        },
    }
    if len(TRUST.canonical_bytes(result)) + 1 > MIGRATION_MAX_BYTES:
        raise MigrationError("migration result exceeds its publication limit")
    return result


def compile_migration(
    *,
    v1_ledger: Any,
    release_readiness: Any,
    checkpoint: Any | None = None,
    checkpoint_policy: Any | None = None,
) -> dict[str, Any]:
    try:
        TRUST.verify_loaded_document(
            v1_ledger,
            "v1 ledger",
            maximum_bytes=V1_INPUT_MAX_BYTES,
        )
        TRUST.verify_loaded_document(
            release_readiness,
            "v1 release readiness",
            maximum_bytes=V1_INPUT_MAX_BYTES,
        )
        if checkpoint is not None:
            TRUST.verify_loaded_document(
                checkpoint,
                "migration checkpoint",
                maximum_bytes=CHECKPOINT_MAX_BYTES,
            )
        if checkpoint_policy is not None:
            TRUST.verify_loaded_document(
                checkpoint_policy,
                "migration checkpoint trust policy",
                maximum_bytes=CHECKPOINT_POLICY_MAX_BYTES,
            )
    except TRUST.TrustPolicyError as error:
        raise MigrationError(str(error)) from error
    return _derive(
        ledger_bytes=v1_ledger.raw_bytes,
        release_bytes=release_readiness.raw_bytes,
        checkpoint_bytes=(None if checkpoint is None else checkpoint.raw_bytes),
        checkpoint_policy_bytes=(
            None
            if checkpoint_policy is None
            else checkpoint_policy.raw_bytes
        ),
    )


def validate_final_result(value: object) -> dict[str, Any]:
    result = dict(_mapping(value, "migration result"))
    _exact_keys(
        result,
        {
            "checkpoint",
            "components",
            "legacy_gates",
            "rollback",
            "schema",
            "source",
            "source_v1",
        },
        "migration result",
    )
    if result["schema"] != SCHEMA or result["source"] != source_hashes():
        raise MigrationError("migration result source is invalid")
    source_v1 = _mapping(result["source_v1"], "migration v1 source")
    rollback = _mapping(result["rollback"], "migration rollback")
    checkpoint = _mapping(result["checkpoint"], "migration checkpoint")
    _exact_keys(
        checkpoint,
        {
            "attestation_bytes_base64",
            "attestation_canonical_sha256",
            "attestation_raw_sha256",
            "present",
            "trust_policy_bytes_base64",
            "trust_policy_canonical_sha256",
            "trust_policy_raw_sha256",
        },
        "migration checkpoint",
    )
    _exact_keys(
        source_v1,
        {
            "ledger_canonical_sha256",
            "ledger_raw_sha256",
            "ledger_schema",
            "release_bytes_base64",
            "release_canonical_sha256",
            "release_observed_on",
            "release_raw_sha256",
            "release_schema",
        },
        "migration v1 source",
    )
    _exact_keys(
        rollback,
        {
            "mode",
            "projection",
            "v1_ledger_bytes_base64",
            "v1_ledger_raw_sha256",
        },
        "migration rollback",
    )
    if checkpoint["present"] is True:
        checkpoint_bytes = _decode(
            checkpoint["attestation_bytes_base64"],
            "migration checkpoint bytes",
            maximum_bytes=CHECKPOINT_MAX_BYTES,
        )
        checkpoint_policy_bytes = _decode(
            checkpoint["trust_policy_bytes_base64"],
            "migration checkpoint trust policy bytes",
            maximum_bytes=CHECKPOINT_POLICY_MAX_BYTES,
        )
    elif (
        checkpoint["present"] is False
        and checkpoint["attestation_bytes_base64"] is None
        and checkpoint["attestation_canonical_sha256"] is None
        and checkpoint["attestation_raw_sha256"] is None
        and checkpoint["trust_policy_bytes_base64"] is None
        and checkpoint["trust_policy_canonical_sha256"] is None
        and checkpoint["trust_policy_raw_sha256"] is None
    ):
        checkpoint_bytes = None
        checkpoint_policy_bytes = None
    else:
        raise MigrationError("migration checkpoint disposition is invalid")
    expected = _derive(
        ledger_bytes=_decode(
            rollback["v1_ledger_bytes_base64"],
            "migration v1 ledger bytes",
            maximum_bytes=V1_INPUT_MAX_BYTES,
        ),
        release_bytes=_decode(
            source_v1["release_bytes_base64"],
            "migration v1 release bytes",
            maximum_bytes=V1_INPUT_MAX_BYTES,
        ),
        checkpoint_bytes=checkpoint_bytes,
        checkpoint_policy_bytes=checkpoint_policy_bytes,
    )
    if result != expected:
        raise MigrationError("migration result was not derived")
    return result


def project_v2_to_v1(value: object) -> None:
    del value
    raise MigrationError("general v2-to-v1 projection is forbidden")


def replay_exact_v1(
    *,
    migration: object,
    ledger_v2: object,
    output: Path,
) -> None:
    del migration, ledger_v2, output
    raise MigrationError(
        "direct v1 replay is forbidden; use the signed rollback verifier"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate the immutable ledger v1 without authorizing rollback."
    )
    parser.add_argument("--v1-ledger", type=Path, required=True)
    parser.add_argument(
        "--release-readiness",
        type=Path,
        required=True,
    )
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-policy", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = compile_migration(
            v1_ledger=TRUST.load_private_json(
                arguments.v1_ledger,
                "v1 ledger",
                maximum_bytes=V1_INPUT_MAX_BYTES,
            ),
            release_readiness=TRUST.load_private_json(
                arguments.release_readiness,
                "v1 release readiness",
                maximum_bytes=V1_INPUT_MAX_BYTES,
            ),
            checkpoint=(
                None
                if arguments.checkpoint is None
                else TRUST.load_private_json(
                    arguments.checkpoint,
                    "migration checkpoint",
                    maximum_bytes=CHECKPOINT_MAX_BYTES,
                )
            ),
            checkpoint_policy=(
                None
                if arguments.checkpoint_policy is None
                else TRUST.load_private_json(
                    arguments.checkpoint_policy,
                    "migration checkpoint trust policy",
                    maximum_bytes=CHECKPOINT_POLICY_MAX_BYTES,
                )
            ),
        )
        TRUST.write_or_verify_owner_only(
            arguments.output,
            result,
            label="ledger migration result",
            maximum_bytes=MIGRATION_MAX_BYTES,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (MigrationError, TRUST.TrustPolicyError) as error:
        print(f"ledger migration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
