from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
INPUT_LINEAGE_SOURCE = DIRECTORY / "input_lineage.py"
MIGRATION_SOURCE = DIRECTORY / "migration.py"
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"

SCHEMA = "coffer.production-provider-inputs/v2"
COMPONENTS = ("ceph", "distribution", "oslo_messaging")
PROVIDER_MIGRATION_MAX_BYTES = 16 * 1024 * 1024
PROVIDER_INPUT_MAX_BYTES = 8 * 1024 * 1024
PROVIDER_RESULT_MAX_BYTES = 16 * 1024 * 1024


class ProviderInputsError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise ProviderInputsError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ProviderInputsError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise ProviderInputsError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)
INPUT_LINEAGE = _load_module(
    "coffer_production_input_lineage_v2",
    INPUT_LINEAGE_SOURCE,
)
MIGRATION = _load_module(
    "coffer_production_ledger_migration_v2",
    MIGRATION_SOURCE,
)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error


def _canonical_digest(value: object) -> str:
    try:
        return TRUST.canonical_sha256(value)
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error


def _require_serialized_size(
    value: object,
    *,
    maximum_bytes: int,
    label: str,
) -> None:
    try:
        size = len(TRUST.canonical_bytes(value)) + 1
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error
    if size > maximum_bytes:
        raise ProviderInputsError(f"{label} size exceeds the fixed budget")


def source_hashes() -> dict[str, str]:
    return {
        "input_lineage_verifier_sha256": _sha256(INPUT_LINEAGE_SOURCE),
        "migration_verifier_sha256": _sha256(MIGRATION_SOURCE),
        "provider_inputs_verifier_sha256": _sha256(Path(__file__).resolve()),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderInputsError(f"{label} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ProviderInputsError(f"{label} fields are invalid")


def _derive(
    *,
    migration_value: object,
    input_values: object,
    policy: Mapping[str, Any],
    policy_sha256: str,
    policy_path: Path,
    today: date,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        migration = MIGRATION.validate_final_result(migration_value)
    except MIGRATION.MigrationError as error:
        raise ProviderInputsError("ledger migration is invalid") from error
    inputs = _mapping(input_values, "provider input results")
    if any(component not in COMPONENTS for component in inputs):
        raise ProviderInputsError("provider input component is unknown")
    parsed_inputs: dict[str, Any] = {}
    components: dict[str, Any] = {}
    qualified_classes: set[str] = set()
    validity: list[date] = []
    for component in COMPONENTS:
        legacy = migration["components"][component]
        if component not in inputs:
            components[component] = {
                "input": None,
                "legacy": legacy["legacy"],
                "reason_code": legacy["reason_code"],
                "status": legacy["status"],
            }
            continue
        raw = inputs[component]
        try:
            if injected_policy:
                result = INPUT_LINEAGE.validate_test_result(
                    raw,
                    policy_path=policy_path,
                    today=today,
                    allow_synthetic_policy=False,
                )
            else:
                result = INPUT_LINEAGE.validate_final_result(raw)
        except INPUT_LINEAGE.InputLineageError as error:
            raise ProviderInputsError(f"{component} input is invalid") from error
        derived = result["derived"]
        if (
            derived["component"] != component
            or derived["policy_sha256"] != policy_sha256
            or (
                derived["status"] == "qualified"
                and derived["production_input"] is not True
            )
            or (
                derived["status"] == "blocked"
                and derived["production_input"] is not False
            )
            or derived["status"] not in {"blocked", "qualified"}
        ):
            raise ProviderInputsError(f"{component} input identity is invalid")
        parsed_inputs[component] = result
        if derived["status"] == "qualified":
            qualified_classes.add(derived["input_class"])
        validity.append(
            TRUST.parse_date(derived["valid_until"], f"{component} valid_until")
        )
        components[component] = {
            "input": {
                "input_class": derived["input_class"],
                "input_result_sha256": _canonical_digest(result),
                "lineage_sha256": derived["lineage_sha256"],
                "qualification_sha256": derived["qualification_sha256"],
                "valid_until": derived["valid_until"],
            },
            "legacy": legacy["legacy"],
            "reason_code": (
                "source-bound-v2-input-qualified"
                if derived["status"] == "qualified"
                else ",".join(derived["reason_codes"])
            ),
            "status": derived["status"],
        }
    return {
        "bundle": {
            "inputs": parsed_inputs,
            "migration": migration,
        },
        "derived": {
            "components": components,
            "migration_sha256": _canonical_digest(migration),
            "policy_id": policy["policy_id"],
            "policy_sha256": policy_sha256,
            "qualified_input_classes": sorted(qualified_classes),
            "valid_until": None if not validity else min(validity).isoformat(),
        },
        "schema": SCHEMA,
        "source": source_hashes(),
    }


def _compile_with_policy(
    *,
    migration: Any,
    inputs: Mapping[str, Any],
    policy_path: Path,
    today: date | None,
    injected_policy: bool,
) -> dict[str, Any]:
    try:
        migration_value = TRUST.verify_loaded_document(
            migration,
            "ledger migration",
            maximum_bytes=PROVIDER_MIGRATION_MAX_BYTES,
        )
        input_values = {
            component: TRUST.verify_loaded_document(
                item,
                f"{component} provider input",
                maximum_bytes=PROVIDER_INPUT_MAX_BYTES,
            )
            for component, item in inputs.items()
        }
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error
    _require_serialized_size(
        migration_value,
        maximum_bytes=PROVIDER_MIGRATION_MAX_BYTES,
        label="ledger migration",
    )
    for component, item in input_values.items():
        _require_serialized_size(
            item,
            maximum_bytes=PROVIDER_INPUT_MAX_BYTES,
            label=f"{component} provider input",
        )
    current = datetime.now(tz=UTC).date() if today is None else today
    try:
        policy, policy_sha256 = TRUST.load_policy(policy_path, today=current)
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error
    result = _derive(
        migration_value=migration_value,
        input_values=input_values,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        today=current,
        injected_policy=injected_policy,
    )
    _require_serialized_size(
        result,
        maximum_bytes=PROVIDER_RESULT_MAX_BYTES,
        label="provider inputs result",
    )
    return result


def compile_result(
    *,
    migration: Any,
    inputs: Mapping[str, Any],
) -> dict[str, Any]:
    return _compile_with_policy(
        migration=migration,
        inputs=inputs,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        injected_policy=False,
    )


def compile_test_result(
    *,
    migration: Any,
    inputs: Mapping[str, Any],
    policy_path: Path,
    today: date,
) -> dict[str, Any]:
    """Exercise an injected production policy in tests; never use in a ledger."""
    return _compile_with_policy(
        migration=migration,
        inputs=inputs,
        policy_path=policy_path,
        today=today,
        injected_policy=True,
    )


def _validate_with_policy(
    value: object,
    *,
    policy_path: Path,
    today: date | None,
    injected_policy: bool,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    _require_serialized_size(
        value,
        maximum_bytes=PROVIDER_RESULT_MAX_BYTES,
        label="provider inputs result",
    )
    result = dict(_mapping(value, "provider inputs result"))
    _exact_keys(
        result,
        {"bundle", "derived", "schema", "source"},
        "provider inputs result",
    )
    if result["schema"] != SCHEMA or result["source"] != source_hashes():
        raise ProviderInputsError("provider inputs result source is invalid")
    bundle = _mapping(result["bundle"], "provider inputs bundle")
    _exact_keys(bundle, {"inputs", "migration"}, "provider inputs bundle")
    _require_serialized_size(
        bundle["migration"],
        maximum_bytes=PROVIDER_MIGRATION_MAX_BYTES,
        label="ledger migration",
    )
    embedded_inputs = _mapping(bundle["inputs"], "provider input results")
    for component, item in embedded_inputs.items():
        _require_serialized_size(
            item,
            maximum_bytes=PROVIDER_INPUT_MAX_BYTES,
            label=f"{component} provider input",
        )
    try:
        policy, policy_sha256 = TRUST.load_policy(policy_path, today=current)
    except TRUST.TrustPolicyError as error:
        raise ProviderInputsError(str(error)) from error
    expected = _derive(
        migration_value=bundle["migration"],
        input_values=embedded_inputs,
        policy=policy,
        policy_sha256=policy_sha256,
        policy_path=policy_path,
        today=current,
        injected_policy=injected_policy,
    )
    if result != expected:
        raise ProviderInputsError("provider inputs result was not derived")
    return result


def validate_final_result(
    value: object,
) -> dict[str, Any]:
    return _validate_with_policy(
        value,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        injected_policy=False,
    )


def validate_test_result(
    value: object,
    *,
    policy_path: Path,
    today: date,
) -> dict[str, Any]:
    """Validate an injected-policy result in tests; never use in a ledger."""
    return _validate_with_policy(
        value,
        policy_path=policy_path,
        today=today,
        injected_policy=True,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate source-bound provider inputs for ledger v2."
    )
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--ceph-input", type=Path)
    parser.add_argument("--distribution-input", type=Path)
    parser.add_argument("--oslo-messaging-input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    paths = {
        "ceph": arguments.ceph_input,
        "distribution": arguments.distribution_input,
        "oslo_messaging": arguments.oslo_messaging_input,
    }
    try:
        result = compile_result(
            migration=TRUST.load_private_json(
                arguments.migration,
                "ledger migration",
                maximum_bytes=PROVIDER_MIGRATION_MAX_BYTES,
            ),
            inputs={
                component: TRUST.load_private_json(
                    path,
                    f"{component} input",
                    maximum_bytes=PROVIDER_INPUT_MAX_BYTES,
                )
                for component, path in paths.items()
                if path is not None
            },
        )
        TRUST.write_or_verify_owner_only(
            arguments.output,
            result,
            label="provider input result",
            maximum_bytes=PROVIDER_RESULT_MAX_BYTES,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (
        ProviderInputsError,
        TRUST.TrustPolicyError,
    ) as error:
        print(f"provider input error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
