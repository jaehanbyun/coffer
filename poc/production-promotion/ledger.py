from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]
READINESS_SOURCE = DIRECTORY / "readiness.py"
GC_RESULT_SOURCE = DIRECTORY / "gc_retention.py"
ARTIFACT_RESULT_SOURCE = DIRECTORY / "artifacts.py"
RGW_KMS_RESULT_SOURCE = DIRECTORY / "rgw_kms.py"
MAINTENANCE_IDENTITY_RESULT_SOURCE = DIRECTORY / "maintenance_identity.py"
DATA_PROTECTION_RESULT_SOURCE = DIRECTORY / "data_protection.py"
OBSERVABILITY_RESULT_SOURCE = DIRECTORY / "observability.py"
LOAD_SOAK_RESULT_SOURCE = DIRECTORY / "load_soak.py"
KOLLA_MULTINODE_RESULT_SOURCE = DIRECTORY / "kolla_multinode.py"

SCHEMA = "coffer.production-promotion-ledger/v1"
RELEASE_SCHEMA = "coffer.production-promotion-release-readiness/v1"
STATUS_ORDER = {
    "blocked": 0,
    "candidate-released": 1,
    "candidate-qualified": 2,
}
GATE_ORDER = (
    "release_inputs",
    "immutable_artifacts",
    "rgw_kms",
    "maintenance_identity",
    "data_protection",
    "observability",
    "gc_retention",
    "load_soak",
    "kolla_multinode",
    "operator_release",
)
PENDING_REASONS = {
    "immutable_artifacts": (
        "exact x86_64 and aarch64 production artifact qualification is absent"
    ),
    "rgw_kms": (
        "released Ceph RGW zero-byte SSE-KMS and failure recovery evidence is absent"
    ),
    "maintenance_identity": (
        "live expiring maintenance identity rotation and revocation evidence is absent"
    ),
    "data_protection": (
        "writer-excluded backup, restore, import, cutover, and rollback "
        "evidence is absent"
    ),
    "observability": (
        "live restart-correct signals, alerts, and failure-budget evidence is absent"
    ),
    "load_soak": (
        "representative private-TLS shared-SQL RGW load and fault evidence is absent"
    ),
    "kolla_multinode": (
        "fresh production-candidate Kolla multinode and audited teardown "
        "evidence is absent"
    ),
    "operator_release": (
        "final operator documentation, release, and supply-chain review is absent"
    ),
}


class PromotionLedgerError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise PromotionLedgerError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise PromotionLedgerError(f"unable to load {path}") from error
    return module


GC_RESULT = _load_module("coffer_production_promotion_gc_result", GC_RESULT_SOURCE)
ARTIFACT_RESULT = _load_module(
    "coffer_production_promotion_artifact_result",
    ARTIFACT_RESULT_SOURCE,
)
RGW_KMS_RESULT = _load_module(
    "coffer_production_promotion_rgw_kms_result",
    RGW_KMS_RESULT_SOURCE,
)
MAINTENANCE_IDENTITY_RESULT = _load_module(
    "coffer_production_promotion_maintenance_identity_result",
    MAINTENANCE_IDENTITY_RESULT_SOURCE,
)
DATA_PROTECTION_RESULT = _load_module(
    "coffer_production_promotion_data_protection_result",
    DATA_PROTECTION_RESULT_SOURCE,
)
OBSERVABILITY_RESULT = _load_module(
    "coffer_production_promotion_observability_result",
    OBSERVABILITY_RESULT_SOURCE,
)
LOAD_SOAK_RESULT = _load_module(
    "coffer_production_promotion_load_soak_result",
    LOAD_SOAK_RESULT_SOURCE,
)
KOLLA_MULTINODE_RESULT = _load_module(
    "coffer_production_promotion_kolla_multinode_result",
    KOLLA_MULTINODE_RESULT_SOURCE,
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as error:
        raise PromotionLedgerError(f"unable to hash {path}") from error


def source_hashes() -> dict[str, str]:
    return {
        "artifact_result_verifier_sha256": _sha256(ARTIFACT_RESULT_SOURCE),
        "data_protection_result_verifier_sha256": _sha256(
            DATA_PROTECTION_RESULT_SOURCE
        ),
        "gc_result_verifier_sha256": _sha256(GC_RESULT_SOURCE),
        "ledger_sha256": _sha256(Path(__file__).resolve()),
        "kolla_multinode_result_verifier_sha256": _sha256(
            KOLLA_MULTINODE_RESULT_SOURCE
        ),
        "load_soak_result_verifier_sha256": _sha256(
            LOAD_SOAK_RESULT_SOURCE
        ),
        "maintenance_identity_result_verifier_sha256": _sha256(
            MAINTENANCE_IDENTITY_RESULT_SOURCE
        ),
        "observability_result_verifier_sha256": _sha256(
            OBSERVABILITY_RESULT_SOURCE
        ),
        "release_readiness_verifier_sha256": _sha256(READINESS_SOURCE),
        "rgw_kms_result_verifier_sha256": _sha256(RGW_KMS_RESULT_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PromotionLedgerError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise PromotionLedgerError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise PromotionLedgerError(f"{label} is invalid")
    try:
        bytes.fromhex(value.removeprefix("sha256:"))
    except ValueError as error:
        raise PromotionLedgerError(f"{label} is invalid") from error
    return value


def _validate_release(
    value: object,
    *,
    today: date,
) -> tuple[dict[str, Any], list[str]]:
    item = _mapping(value, "release readiness")
    _exact_keys(
        item,
        {
            "blockers",
            "components",
            "next_action",
            "production_candidate",
            "release_inputs_qualified",
            "schema",
            "source",
            "status",
            "ui_observed_on",
        },
        "release readiness",
    )
    if item["schema"] != RELEASE_SCHEMA:
        raise PromotionLedgerError("release readiness schema is unsupported")
    status = item["status"]
    if status not in STATUS_ORDER:
        raise PromotionLedgerError("release readiness status is unsupported")
    if (
        item["production_candidate"] is not False
        or item["release_inputs_qualified"]
        is not (status == "candidate-qualified")
    ):
        raise PromotionLedgerError("release readiness disposition is invalid")

    try:
        observed = date.fromisoformat(item["ui_observed_on"])
    except (TypeError, ValueError) as error:
        raise PromotionLedgerError(
            "release readiness observation date is invalid"
        ) from error
    if observed > today or (today - observed).days > 1:
        raise PromotionLedgerError("release readiness observation is stale")

    components = _mapping(item["components"], "release readiness components")
    if set(components) != {"distribution", "ceph", "oslo_messaging"}:
        raise PromotionLedgerError("release readiness components are invalid")
    expected_blockers: list[str] = []
    statuses: list[str] = []
    for name in ("distribution", "ceph", "oslo_messaging"):
        component = _mapping(components[name], f"release readiness {name}")
        _exact_keys(
            component,
            {"reasons", "revision", "status", "version"},
            f"release readiness {name}",
        )
        component_status = component["status"]
        reasons = component["reasons"]
        if (
            component_status not in STATUS_ORDER
            or not isinstance(reasons, list)
            or any(
                not isinstance(reason, str) or not reason
                for reason in reasons
            )
            or (
                component_status == "candidate-qualified"
                and reasons
            )
        ):
            raise PromotionLedgerError(
                f"release readiness {name} is invalid"
            )
        statuses.append(component_status)
        expected_blockers.extend(
            f"{name}: {reason}" for reason in reasons
        )
    expected_status = min(statuses, key=STATUS_ORDER.__getitem__)
    if expected_status != status or item["blockers"] != expected_blockers:
        raise PromotionLedgerError("release readiness aggregate is invalid")

    sources = _mapping(item["source"], "release readiness source")
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
    if sources != expected_sources:
        raise PromotionLedgerError("release readiness source binding changed")
    return dict(item), expected_blockers


def _evidence(schema: str, digest: str) -> dict[str, str]:
    return {"schema": schema, "sha256": _digest(digest, "evidence digest")}


def compile_ledger(
    *,
    release_readiness: object,
    release_digest: str,
    gc_result: object | None = None,
    gc_digest: str | None = None,
    artifact_result: object | None = None,
    artifact_digest: str | None = None,
    rgw_kms_result: object | None = None,
    rgw_kms_digest: str | None = None,
    maintenance_identity_result: object | None = None,
    maintenance_identity_digest: str | None = None,
    data_protection_result: object | None = None,
    data_protection_digest: str | None = None,
    observability_result: object | None = None,
    observability_digest: str | None = None,
    load_soak_result: object | None = None,
    load_soak_digest: str | None = None,
    kolla_multinode_result: object | None = None,
    kolla_multinode_digest: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    release, release_blockers = _validate_release(
        release_readiness,
        today=current,
    )
    gates: dict[str, dict[str, Any]] = {}
    release_qualified = release["status"] == "candidate-qualified"
    gates["release_inputs"] = {
        "evidence": _evidence(RELEASE_SCHEMA, release_digest),
        "reason": (
            None
            if release_qualified
            else "official release readiness is not candidate-qualified"
        ),
        "status": "passed" if release_qualified else "blocked",
    }

    for gate_id, reason in PENDING_REASONS.items():
        gates[gate_id] = {
            "evidence": None,
            "reason": reason,
            "status": "pending",
        }

    if artifact_result is None:
        if artifact_digest is not None:
            raise PromotionLedgerError(
                "artifact digest has no specialist result"
            )
    else:
        if artifact_digest is None:
            raise PromotionLedgerError(
                "artifact specialist result digest is required"
            )
        try:
            qualified_artifact = ARTIFACT_RESULT.validate_final_result(
                artifact_result
            )
        except ARTIFACT_RESULT.ArtifactResultError as error:
            raise PromotionLedgerError(
                "artifact specialist result is invalid"
            ) from error
        if qualified_artifact["release_readiness_sha256"] != release_digest:
            raise PromotionLedgerError(
                "artifact specialist release binding changed"
            )
        gates["immutable_artifacts"] = {
            "evidence": _evidence(
                qualified_artifact["schema"],
                artifact_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if rgw_kms_result is None:
        if rgw_kms_digest is not None:
            raise PromotionLedgerError(
                "RGW/KMS digest has no specialist result"
            )
    else:
        if rgw_kms_digest is None:
            raise PromotionLedgerError(
                "RGW/KMS specialist result digest is required"
            )
        try:
            qualified_rgw_kms = RGW_KMS_RESULT.validate_final_result(
                rgw_kms_result
            )
        except RGW_KMS_RESULT.RgwKmsResultError as error:
            raise PromotionLedgerError(
                "RGW/KMS specialist result is invalid"
            ) from error
        if qualified_rgw_kms["release_readiness_sha256"] != release_digest:
            raise PromotionLedgerError(
                "RGW/KMS specialist release binding changed"
            )
        gates["rgw_kms"] = {
            "evidence": _evidence(
                qualified_rgw_kms["schema"],
                rgw_kms_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if maintenance_identity_result is None:
        if maintenance_identity_digest is not None:
            raise PromotionLedgerError(
                "maintenance identity digest has no specialist result"
            )
    else:
        if maintenance_identity_digest is None:
            raise PromotionLedgerError(
                "maintenance identity specialist result digest is required"
            )
        if (
            artifact_result is None
            or artifact_digest is None
            or rgw_kms_result is None
            or rgw_kms_digest is None
        ):
            raise PromotionLedgerError(
                "maintenance identity prerequisite results are absent"
            )
        try:
            qualified_identity = (
                MAINTENANCE_IDENTITY_RESULT.validate_final_result(
                    maintenance_identity_result
                )
            )
        except (
            MAINTENANCE_IDENTITY_RESULT.MaintenanceIdentityResultError
        ) as error:
            raise PromotionLedgerError(
                "maintenance identity specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_identity["prerequisites"],
            "maintenance identity prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_kms_digest,
        }:
            raise PromotionLedgerError(
                "maintenance identity prerequisite binding changed"
            )
        gates["maintenance_identity"] = {
            "evidence": _evidence(
                qualified_identity["schema"],
                maintenance_identity_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if data_protection_result is None:
        if data_protection_digest is not None:
            raise PromotionLedgerError(
                "data-protection digest has no specialist result"
            )
    else:
        if data_protection_digest is None:
            raise PromotionLedgerError(
                "data-protection specialist result digest is required"
            )
        if (
            artifact_result is None
            or artifact_digest is None
            or rgw_kms_result is None
            or rgw_kms_digest is None
            or maintenance_identity_result is None
            or maintenance_identity_digest is None
        ):
            raise PromotionLedgerError(
                "data-protection prerequisite results are absent"
            )
        try:
            qualified_data_protection = (
                DATA_PROTECTION_RESULT.validate_final_result(
                    data_protection_result
                )
            )
        except DATA_PROTECTION_RESULT.DataProtectionResultError as error:
            raise PromotionLedgerError(
                "data-protection specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_data_protection["prerequisites"],
            "data-protection prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "maintenance_identity_result_sha256": (
                maintenance_identity_digest
            ),
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_kms_digest,
        }:
            raise PromotionLedgerError(
                "data-protection prerequisite binding changed"
            )
        gates["data_protection"] = {
            "evidence": _evidence(
                qualified_data_protection["schema"],
                data_protection_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if observability_result is None:
        if observability_digest is not None:
            raise PromotionLedgerError(
                "observability digest has no specialist result"
            )
    else:
        if observability_digest is None:
            raise PromotionLedgerError(
                "observability specialist result digest is required"
            )
        if (
            artifact_result is None
            or artifact_digest is None
            or rgw_kms_result is None
            or rgw_kms_digest is None
            or maintenance_identity_result is None
            or maintenance_identity_digest is None
            or data_protection_result is None
            or data_protection_digest is None
        ):
            raise PromotionLedgerError(
                "observability prerequisite results are absent"
            )
        try:
            qualified_observability = (
                OBSERVABILITY_RESULT.validate_final_result(
                    observability_result
                )
            )
        except OBSERVABILITY_RESULT.ObservabilityResultError as error:
            raise PromotionLedgerError(
                "observability specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_observability["prerequisites"],
            "observability prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "data_protection_result_sha256": data_protection_digest,
            "maintenance_identity_result_sha256": (
                maintenance_identity_digest
            ),
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_kms_digest,
        }:
            raise PromotionLedgerError(
                "observability prerequisite binding changed"
            )
        gates["observability"] = {
            "evidence": _evidence(
                qualified_observability["schema"],
                observability_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if gc_result is None:
        if gc_digest is not None:
            raise PromotionLedgerError("GC digest has no specialist result")
        gates["gc_retention"] = {
            "evidence": None,
            "reason": "qualified disposable GC and restore evidence is absent",
            "status": "pending",
        }
    else:
        if gc_digest is None:
            raise PromotionLedgerError("GC specialist result digest is required")
        if artifact_result is None or artifact_digest is None:
            raise PromotionLedgerError(
                "GC prerequisite artifact result is absent"
            )
        try:
            qualified_gc = GC_RESULT.validate_final_result(gc_result)
        except GC_RESULT.ProductionGCResultError as error:
            raise PromotionLedgerError(
                "GC specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_gc["prerequisites"],
            "GC prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "release_readiness_sha256": release_digest,
        }:
            raise PromotionLedgerError(
                "GC prerequisite binding changed"
            )
        gates["gc_retention"] = {
            "evidence": _evidence(qualified_gc["schema"], gc_digest),
            "reason": None,
            "status": "passed",
        }

    if load_soak_result is None:
        if load_soak_digest is not None:
            raise PromotionLedgerError(
                "load/soak digest has no specialist result"
            )
    else:
        if load_soak_digest is None:
            raise PromotionLedgerError(
                "load/soak specialist result digest is required"
            )
        if (
            artifact_result is None
            or artifact_digest is None
            or rgw_kms_result is None
            or rgw_kms_digest is None
            or maintenance_identity_result is None
            or maintenance_identity_digest is None
            or data_protection_result is None
            or data_protection_digest is None
            or observability_result is None
            or observability_digest is None
            or gc_result is None
            or gc_digest is None
        ):
            raise PromotionLedgerError(
                "load/soak prerequisite results are absent"
            )
        try:
            qualified_load_soak = LOAD_SOAK_RESULT.validate_final_result(
                load_soak_result
            )
        except LOAD_SOAK_RESULT.LoadSoakResultError as error:
            raise PromotionLedgerError(
                "load/soak specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_load_soak["prerequisites"],
            "load/soak prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "data_protection_result_sha256": data_protection_digest,
            "gc_retention_result_sha256": gc_digest,
            "maintenance_identity_result_sha256": (
                maintenance_identity_digest
            ),
            "observability_result_sha256": observability_digest,
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_kms_digest,
        }:
            raise PromotionLedgerError(
                "load/soak prerequisite binding changed"
            )
        gates["load_soak"] = {
            "evidence": _evidence(
                qualified_load_soak["schema"],
                load_soak_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    if kolla_multinode_result is None:
        if kolla_multinode_digest is not None:
            raise PromotionLedgerError(
                "Kolla multinode digest has no specialist result"
            )
    else:
        if kolla_multinode_digest is None:
            raise PromotionLedgerError(
                "Kolla multinode specialist result digest is required"
            )
        if (
            artifact_result is None
            or artifact_digest is None
            or rgw_kms_result is None
            or rgw_kms_digest is None
            or maintenance_identity_result is None
            or maintenance_identity_digest is None
            or data_protection_result is None
            or data_protection_digest is None
            or observability_result is None
            or observability_digest is None
            or gc_result is None
            or gc_digest is None
            or load_soak_result is None
            or load_soak_digest is None
        ):
            raise PromotionLedgerError(
                "Kolla multinode prerequisite results are absent"
            )
        try:
            qualified_kolla = (
                KOLLA_MULTINODE_RESULT.validate_final_result(
                    kolla_multinode_result
                )
            )
        except KOLLA_MULTINODE_RESULT.KollaMultinodeResultError as error:
            raise PromotionLedgerError(
                "Kolla multinode specialist result is invalid"
            ) from error
        prerequisites = _mapping(
            qualified_kolla["prerequisites"],
            "Kolla multinode prerequisites",
        )
        if prerequisites != {
            "artifact_result_sha256": artifact_digest,
            "data_protection_result_sha256": data_protection_digest,
            "gc_retention_result_sha256": gc_digest,
            "load_soak_result_sha256": load_soak_digest,
            "maintenance_identity_result_sha256": (
                maintenance_identity_digest
            ),
            "observability_result_sha256": observability_digest,
            "release_readiness_sha256": release_digest,
            "rgw_kms_result_sha256": rgw_kms_digest,
        }:
            raise PromotionLedgerError(
                "Kolla multinode prerequisite binding changed"
            )
        gates["kolla_multinode"] = {
            "evidence": _evidence(
                qualified_kolla["schema"],
                kolla_multinode_digest,
            ),
            "reason": None,
            "status": "passed",
        }

    ordered_gates = [
        {"id": gate_id, **gates[gate_id]}
        for gate_id in GATE_ORDER
    ]
    blocked_gates = [
        gate["id"] for gate in ordered_gates if gate["status"] == "blocked"
    ]
    pending_gates = [
        gate["id"] for gate in ordered_gates if gate["status"] == "pending"
    ]
    if blocked_gates:
        status = "blocked"
    elif pending_gates:
        status = "pending"
    else:
        status = "qualified"
    return {
        "blocked_gates": blocked_gates,
        "blockers": release_blockers,
        "gate_count": len(ordered_gates),
        "gates": ordered_gates,
        "passed_gate_count": sum(
            gate["status"] == "passed" for gate in ordered_gates
        ),
        "pending_gates": pending_gates,
        "production_candidate": status == "qualified",
        "schema": SCHEMA,
        "source": source_hashes(),
        "status": status,
    }


def _load_private(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
        ):
            raise PromotionLedgerError(f"{label} ownership is unsafe")
        payload = path.read_bytes()
        if not payload or len(payload) > 16 * 1024 * 1024:
            raise PromotionLedgerError(f"{label} size is invalid")
        value = json.loads(payload)
    except PromotionLedgerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PromotionLedgerError(f"{label} is invalid") from error
    if not isinstance(value, dict):
        raise PromotionLedgerError(f"{label} must be a JSON object")
    return value, _sha256_bytes(payload)


def _write_owner_only(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute():
        raise PromotionLedgerError("output path must be absolute")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    details = path.parent.lstat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PromotionLedgerError("output directory ownership is unsafe")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    except OSError as error:
        raise PromotionLedgerError("unable to write promotion ledger") from error
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the canonical Stage 6 promotion ledger only from "
            "specialist verifier results."
        )
    )
    parser.add_argument("--release-readiness", type=Path, required=True)
    parser.add_argument("--gc-result", type=Path)
    parser.add_argument("--artifact-result", type=Path)
    parser.add_argument("--rgw-kms-result", type=Path)
    parser.add_argument("--maintenance-identity-result", type=Path)
    parser.add_argument("--data-protection-result", type=Path)
    parser.add_argument("--observability-result", type=Path)
    parser.add_argument("--load-soak-result", type=Path)
    parser.add_argument("--kolla-multinode-result", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-qualified", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        release, release_digest = _load_private(
            arguments.release_readiness,
            "release readiness",
        )
        gc_value: dict[str, Any] | None = None
        gc_digest: str | None = None
        artifact_value: dict[str, Any] | None = None
        artifact_digest: str | None = None
        rgw_kms_value: dict[str, Any] | None = None
        rgw_kms_digest: str | None = None
        maintenance_identity_value: dict[str, Any] | None = None
        maintenance_identity_digest: str | None = None
        data_protection_value: dict[str, Any] | None = None
        data_protection_digest: str | None = None
        observability_value: dict[str, Any] | None = None
        observability_digest: str | None = None
        load_soak_value: dict[str, Any] | None = None
        load_soak_digest: str | None = None
        kolla_multinode_value: dict[str, Any] | None = None
        kolla_multinode_digest: str | None = None
        if arguments.gc_result is not None:
            gc_value, gc_digest = _load_private(
                arguments.gc_result,
                "GC specialist result",
            )
        if arguments.artifact_result is not None:
            artifact_value, artifact_digest = _load_private(
                arguments.artifact_result,
                "artifact specialist result",
            )
        if arguments.rgw_kms_result is not None:
            rgw_kms_value, rgw_kms_digest = _load_private(
                arguments.rgw_kms_result,
                "RGW/KMS specialist result",
            )
        if arguments.maintenance_identity_result is not None:
            maintenance_identity_value, maintenance_identity_digest = (
                _load_private(
                    arguments.maintenance_identity_result,
                    "maintenance identity specialist result",
                )
            )
        if arguments.data_protection_result is not None:
            data_protection_value, data_protection_digest = _load_private(
                arguments.data_protection_result,
                "data-protection specialist result",
            )
        if arguments.observability_result is not None:
            observability_value, observability_digest = _load_private(
                arguments.observability_result,
                "observability specialist result",
            )
        if arguments.load_soak_result is not None:
            load_soak_value, load_soak_digest = _load_private(
                arguments.load_soak_result,
                "load/soak specialist result",
            )
        if arguments.kolla_multinode_result is not None:
            kolla_multinode_value, kolla_multinode_digest = _load_private(
                arguments.kolla_multinode_result,
                "Kolla multinode specialist result",
            )
        ledger = compile_ledger(
            release_readiness=release,
            release_digest=release_digest,
            gc_result=gc_value,
            gc_digest=gc_digest,
            artifact_result=artifact_value,
            artifact_digest=artifact_digest,
            rgw_kms_result=rgw_kms_value,
            rgw_kms_digest=rgw_kms_digest,
            maintenance_identity_result=maintenance_identity_value,
            maintenance_identity_digest=maintenance_identity_digest,
            data_protection_result=data_protection_value,
            data_protection_digest=data_protection_digest,
            observability_result=observability_value,
            observability_digest=observability_digest,
            load_soak_result=load_soak_value,
            load_soak_digest=load_soak_digest,
            kolla_multinode_result=kolla_multinode_value,
            kolla_multinode_digest=kolla_multinode_digest,
        )
        _write_owner_only(arguments.output, ledger)
        print(json.dumps(ledger, indent=2, sort_keys=True))
        if arguments.require_qualified and not ledger["production_candidate"]:
            return 3
        return 0
    except PromotionLedgerError as error:
        print(f"production promotion ledger error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
