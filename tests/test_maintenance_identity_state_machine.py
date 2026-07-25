from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "poc"
    / "maintenance-identity"
    / "state_machine.py"
)
TOPOLOGY_PATH = (
    ROOT
    / "poc"
    / "maintenance-identity"
    / "topology.json"
)
SPEC = importlib.util.spec_from_file_location(
    "coffer_maintenance_identity_state_machine",
    MODULE_PATH,
)
assert SPEC is not None and SPEC.loader is not None
LIFECYCLE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LIFECYCLE
SPEC.loader.exec_module(LIFECYCLE)

INVOCATION_ID = "01k0a1b2c3d4e5f6g7h8j9k0mn"
TARGET_SIGNATURE = "a" * 64
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


def topology():
    return LIFECYCLE.load_topology(TOPOLOGY_PATH)


def preflight_state(*, workloads=("reconcile-1", "reconcile-2")):
    return LIFECYCLE.create_preflight_state(
        topology(),
        INVOCATION_ID,
        TARGET_SIGNATURE,
        workloads,
        now=NOW,
    )


def generation_resources(
    state,
    generation: int,
    *,
    role_owned: bool = False,
):
    specs = LIFECYCLE.expected_resource_specs(
        topology(),
        state,
        generation,
        maintenance_role_owned=role_owned,
    )
    resources = {}
    for index, (key, spec) in enumerate(specs.items(), start=1):
        resources[key] = {
            "id": f"immutable-{generation}-{index:03d}-{key}".replace(":", "-"),
            **spec,
        }
    return resources


def registered_generation1(*, role_owned: bool = False):
    state = preflight_state()
    return LIFECYCLE.register_generation(
        topology(),
        state,
        1,
        generation_resources(state, 1, role_owned=role_owned),
        now=NOW,
    )


def verified_generation1(*, role_owned: bool = False):
    return LIFECYCLE.verify_generation(
        topology(),
        registered_generation1(role_owned=role_owned),
        1,
        now=NOW,
    )


def verified_generation2(*, role_owned: bool = False):
    state = verified_generation1(role_owned=role_owned)
    state = LIFECYCLE.register_generation(
        topology(),
        state,
        2,
        generation_resources(state, 2),
        now=NOW,
    )
    return LIFECYCLE.verify_generation(
        topology(),
        state,
        2,
        now=NOW,
    )


def test_checked_in_topology_is_exact_and_stable() -> None:
    loaded = topology()

    assert loaded.invocation_prefix == "coffer-maint"
    assert loaded.allowed_workloads == (
        "reconcile-1",
        "reconcile-2",
        "comparison-1",
    )
    assert loaded.allowed_generations == (1, 2)
    assert loaded.roles == ("service", "registry_maintenance")
    assert loaded.minimum_lifetime_seconds == 900
    assert loaded.maximum_lifetime_seconds == 7200
    assert loaded.cleanup_order == LIFECYCLE.EXPECTED_CLEANUP_ORDER
    assert len(loaded.digest) == 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "allowed_workloads",
            ["reconcile-1", "operator-shell"],
            "fixed workload allowlist",
        ),
        ("allowed_generations", [1, 2, 3], "exactly 1 and 2"),
        ("roles", ["admin"], "exactly service and maintenance"),
        ("work_root", "../outside", "work/maintenance-identity"),
    ],
)
def test_topology_expansion_fails_closed(
    field: str,
    value: object,
    message: str,
) -> None:
    raw = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    raw[field] = value

    with pytest.raises(LIFECYCLE.LifecycleError, match=message):
        LIFECYCLE.validate_topology(raw)


def test_broader_or_unrestricted_access_rule_fails_closed() -> None:
    raw = json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    raw["application_credential"]["unrestricted"] = True

    with pytest.raises(LIFECYCLE.LifecycleError, match="restricted"):
        LIFECYCLE.validate_topology(raw)

    raw["application_credential"]["unrestricted"] = False
    raw["application_credential"]["access_rules"][0]["method"] = "*"
    with pytest.raises(LIFECYCLE.LifecycleError, match="not exact"):
        LIFECYCLE.validate_topology(raw)


def test_preflight_state_requires_exact_invocation_target_and_workload() -> None:
    with pytest.raises(LIFECYCLE.LifecycleError, match="26-character ULID"):
        LIFECYCLE.create_preflight_state(
            topology(),
            "not-a-ulid",
            TARGET_SIGNATURE,
            ["reconcile-1"],
        )
    with pytest.raises(LIFECYCLE.LifecycleError, match="SHA-256"):
        LIFECYCLE.create_preflight_state(
            topology(),
            INVOCATION_ID,
            "not-a-signature",
            ["reconcile-1"],
        )
    with pytest.raises(LIFECYCLE.LifecycleError, match="exact allowlist"):
        LIFECYCLE.create_preflight_state(
            topology(),
            INVOCATION_ID,
            TARGET_SIGNATURE,
            ["operator-shell"],
        )


def test_generation1_requires_the_complete_exact_resource_set() -> None:
    state = preflight_state(workloads=("reconcile-1",))
    resources = generation_resources(state, 1)
    resources.pop("secret:reconcile-1:g1:client-key")

    with pytest.raises(LIFECYCLE.LifecycleError, match="incomplete"):
        LIFECYCLE.register_generation(topology(), state, 1, resources)


def test_resource_name_or_field_expansion_fails_closed() -> None:
    state = preflight_state(workloads=("reconcile-1",))
    resources = generation_resources(state, 1)
    resources["project"]["name"] = "some-other-project"

    with pytest.raises(LIFECYCLE.LifecycleError, match="exact allowlist"):
        LIFECYCLE.register_generation(topology(), state, 1, resources)

    resources = generation_resources(state, 1)
    resources["project"]["secret"] = "unexpected"
    with pytest.raises(LIFECYCLE.LifecycleError, match="unexpected fields"):
        LIFECYCLE.register_generation(topology(), state, 1, resources)


def test_resource_immutable_ids_must_be_unique() -> None:
    state = preflight_state(workloads=("reconcile-1",))
    resources = generation_resources(state, 1)
    resources["user"]["id"] = resources["project"]["id"]

    with pytest.raises(LIFECYCLE.LifecycleError, match="globally unique"):
        LIFECYCLE.register_generation(topology(), state, 1, resources)


def test_happy_rotation_lifecycle_is_ordered_and_finite() -> None:
    state = verified_generation2()
    assert state["phase"] == "generation2_verified"
    assert set(state["active_generation"].values()) == {2}

    with pytest.raises(LIFECYCLE.LifecycleError, match="has not drained"):
        LIFECYCLE.mark_rotation_drained(
            topology(),
            state,
            elapsed_seconds=59,
            keystone_cache_seconds=30,
            registry_token_seconds=60,
        )

    state = LIFECYCLE.mark_rotation_drained(
        topology(),
        state,
        elapsed_seconds=60,
        keystone_cache_seconds=30,
        registry_token_seconds=60,
        now=NOW,
    )
    state = LIFECYCLE.revoke_old_generation(topology(), state, now=NOW)
    assert state["phase"] == "old_revoked"
    assert all(item["generation"] != 1 for item in state["resources"])
    assert any(item["generation"] == 2 for item in state["resources"])

    state = LIFECYCLE.mark_failure_matrix_verified(
        topology(),
        state,
        now=NOW,
    )
    assert state["phase"] == "failures_verified"


def test_out_of_order_rotation_and_failure_actions_are_refused() -> None:
    state = registered_generation1()
    with pytest.raises(LIFECYCLE.LifecycleError, match="out of order"):
        LIFECYCLE.verify_generation(topology(), state, 2)
    with pytest.raises(LIFECYCLE.LifecycleError, match="verified generation 2"):
        LIFECYCLE.mark_rotation_drained(
            topology(),
            state,
            elapsed_seconds=60,
            keystone_cache_seconds=30,
            registry_token_seconds=60,
        )
    with pytest.raises(LIFECYCLE.LifecycleError, match="old-generation"):
        LIFECYCLE.mark_failure_matrix_verified(topology(), state)


def test_exact_cleanup_target_refuses_name_only_or_unowned_role() -> None:
    state = registered_generation1(role_owned=False)
    project = next(item for item in state["resources"] if item["kind"] == "project")
    LIFECYCLE.assert_exact_cleanup_target(
        topology(),
        state,
        {field: project[field] for field in ("kind", "id", "name")},
    )

    with pytest.raises(LIFECYCLE.LifecycleError, match="kind, ID, and name"):
        LIFECYCLE.assert_exact_cleanup_target(
            topology(),
            state,
            {"kind": "project", "name": project["name"]},
        )
    role = next(item for item in state["resources"] if item["kind"] == "role")
    with pytest.raises(LIFECYCLE.LifecycleError, match="exact owned"):
        LIFECYCLE.assert_exact_cleanup_target(
            topology(),
            state,
            {field: role[field] for field in ("kind", "id", "name")},
        )


def test_cleanup_plan_uses_dependency_order_and_generation2_first() -> None:
    state = verified_generation2(role_owned=True)
    plan = LIFECYCLE.cleanup_plan(topology(), state)
    kinds = [item["kind"] for item in plan]
    ranks = [topology().cleanup_order.index(kind) for kind in kinds]

    assert ranks == sorted(ranks)
    assert kinds[-3:] == ["user", "project", "role"]
    credentials = [
        item for item in plan if item["kind"] == "application_credential"
    ]
    assert "-g2" in credentials[0]["name"]
    assert "-g1" in credentials[-1]["name"]


def test_teardown_requires_exact_plan_and_explicit_zero_residue() -> None:
    state = registered_generation1()
    plan = LIFECYCLE.cleanup_plan(topology(), state)

    with pytest.raises(LIFECYCLE.LifecycleError, match="exact cleanup plan"):
        LIFECYCLE.finalize_teardown(
            topology(),
            state,
            list(reversed(plan)),
            {"identities": 0},
        )
    with pytest.raises(LIFECYCLE.LifecycleError, match="explicit zeroes"):
        LIFECYCLE.finalize_teardown(
            topology(),
            state,
            plan,
            {"identities": 0, "secrets": 1},
        )

    terminal = LIFECYCLE.finalize_teardown(
        topology(),
        state,
        plan,
        {
            "identities": 0,
            "credentials": 0,
            "secrets": 0,
            "mappings": 0,
            "materializations": 0,
        },
        now=NOW,
    )
    assert terminal["phase"] == "torn_down"
    assert terminal["resources"][0]["kind"] == "role"
    assert terminal["resources"][0]["owned"] is False
    assert LIFECYCLE.finalize_teardown(
        topology(),
        terminal,
        [],
        terminal["residue_counts"],
    ) == terminal


def test_owned_role_is_included_only_when_the_invocation_created_it() -> None:
    reused = registered_generation1(role_owned=False)
    created = registered_generation1(role_owned=True)

    assert "role" not in {
        item["kind"] for item in LIFECYCLE.cleanup_plan(topology(), reused)
    }
    assert LIFECYCLE.cleanup_plan(topology(), created)[-1]["kind"] == "role"


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "opaque-secret-value"},
        {"nested": {"private_key": "opaque-secret-value"}},
        {"message": "Authorization: Basic opaque-secret-value"},
        {"message": "Bearer abcdefghijklmnopqrstuvwxyz"},
        {"message": "-----BEGIN PRIVATE KEY-----"},
        {"message": "eyJabcdefghijk.abcdefghijklmnop.signature"},
    ],
)
def test_retained_payload_rejects_secret_fields_and_patterns(payload) -> None:
    with pytest.raises(LIFECYCLE.LifecycleError, match="forbidden|secret-like"):
        LIFECYCLE.validate_retained_payload(payload)


def test_retained_payload_rejects_known_secret_values() -> None:
    with pytest.raises(LIFECYCLE.LifecycleError, match="known secret"):
        LIFECYCLE.validate_retained_payload(
            {"message": "prefix super-secret-material suffix"},
            known_secret_values=["super-secret-material"],
        )


def test_redacted_evidence_hashes_ids_and_allows_only_fixed_fields() -> None:
    state = registered_generation1()
    evidence = LIFECYCLE.redacted_evidence(
        topology(),
        state,
        {
            "http_status_class": "2xx",
            "log_scan_count": 0,
            "residue_counts": {"temporary_files": 0},
        },
        known_secret_values=["never-retain-this-secret"],
    )

    assert evidence["schema"] == LIFECYCLE.EVIDENCE_SCHEMA
    assert evidence["phase"] == "generation1_created"
    assert evidence["immutable_id_hashes"]
    serialized = json.dumps(evidence, sort_keys=True)
    assert "immutable-1-" not in serialized
    assert "never-retain-this-secret" not in serialized

    with pytest.raises(LIFECYCLE.LifecycleError, match="non-allowlisted"):
        LIFECYCLE.redacted_evidence(
            topology(),
            state,
            {"raw_openstack_log": "not permitted"},
        )


def test_state_detects_target_topology_and_resource_tampering() -> None:
    state = registered_generation1()
    tampered = deepcopy(state)
    tampered["target_signature"] = "b" * 63
    with pytest.raises(LIFECYCLE.LifecycleError, match="target signature"):
        LIFECYCLE.validate_state(topology(), tampered)

    tampered = deepcopy(state)
    tampered["topology_digest"] = "b" * 64
    with pytest.raises(LIFECYCLE.LifecycleError, match="does not match"):
        LIFECYCLE.validate_state(topology(), tampered)

    tampered = deepcopy(state)
    tampered["resources"][0]["name"] = "coffer-maint-prefix-collision"
    with pytest.raises(LIFECYCLE.LifecycleError, match="exact allowlist"):
        LIFECYCLE.validate_state(topology(), tampered)
