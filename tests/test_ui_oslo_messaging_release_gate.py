from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "poc" / "ui-images"
CONTRACT = HARNESS / "oslo_messaging_release_gate.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


load("python_target", HARNESS / "python_target.py")
load("collect_python_trial", HARNESS / "collect_python_trial.py")
MODULE = load(
    "coffer_ui_oslo_messaging_release_gate",
    HARNESS / "oslo_messaging_release_gate.py",
)


def contract_fixture() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def fixed_release() -> dict[str, object]:
    return {
        "artifacts": [
            {
                "filename": "oslo_messaging-17.3.1-py3-none-any.whl",
                "packagetype": "bdist_wheel",
                "sha256": "a" * 64,
                "yanked": False,
            },
            {
                "filename": "oslo_messaging-17.3.1.tar.gz",
                "packagetype": "sdist",
                "sha256": "b" * 64,
                "yanked": False,
            },
        ],
        "contains_stable_patch": True,
        "source_probe_present": True,
        "source_sha256": "c" * 64,
        "tag_revision": "d" * 40,
        "version": "17.3.1",
    }


def released_fixture() -> dict[str, object]:
    document = contract_fixture()
    observation = document["current_observation"]
    observation["stable_releases"].append("17.3.1")
    observation["fixed_stable_release"] = fixed_release()
    observation["upper_constraint"] = "oslo.messaging===17.3.1"
    return document


def qualification() -> dict[str, object]:
    return {
        "artifacts_sha256": {
            "oslo_messaging-17.3.1-py3-none-any.whl": "a" * 64,
            "oslo_messaging-17.3.1.tar.gz": "b" * 64,
        },
        "schema": "coffer.ui-oslo-messaging-qualification/v1",
        "surfaces": {
            surface: {
                "finding_absent": True,
                "installed_version": "17.3.1",
                "runtime_hostname_verification": True,
            }
            for surface in ("horizon", "skyline")
        },
        "tag_revision": "d" * 40,
        "version": "17.3.1",
    }


def test_current_official_stable_release_state_is_blocked() -> None:
    result = MODULE.classify(contract_fixture())

    assert result["status"] == "blocked"
    assert result["production_candidate"] is False
    assert result["stable_patch_merged"] is True
    assert result["fixed_stable_release"] is None
    assert result["qualification_accepted"] is False
    assert result["mainline_advisory_discrepancy"] == {
        "claimed_version": "18.0.0",
        "first_verified_source_version": "18.1.0",
    }
    assert result["reasons"] == [
        "stable/2026.1 has no official fixed oslo.messaging release",
        "stable/2026.1 upper constraints remain at oslo.messaging 17.3.0",
    ]


def test_official_release_is_only_a_candidate_until_both_surfaces_qualify() -> None:
    document = released_fixture()

    result = MODULE.classify(document)

    assert result["status"] == "candidate-released"
    assert result["production_candidate"] is False
    assert result["qualification_accepted"] is False
    assert result["fixed_stable_release"]["version"] == "17.3.1"


def test_exact_two_surface_qualification_is_accepted_but_not_global_promotion() -> None:
    document = released_fixture()
    document["qualification"] = qualification()

    result = MODULE.classify(document)

    assert result["status"] == "candidate-qualified"
    assert result["production_candidate"] is False
    assert result["qualification_accepted"] is True
    assert result["reasons"] == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda document: document["current_observation"].update(
                upper_constraint="oslo.messaging===17.3.0"
            ),
            "upper constraint",
        ),
        (
            lambda document: document["current_observation"]["stable_releases"].remove(
                "17.3.1"
            ),
            "absent from PyPI",
        ),
        (
            lambda document: document["current_observation"][
                "fixed_stable_release"
            ].update(contains_stable_patch=False),
            "outside policy",
        ),
        (
            lambda document: document["current_observation"]["fixed_stable_release"][
                "artifacts"
            ].reverse(),
            "unsorted",
        ),
        (
            lambda document: document["current_observation"]["fixed_stable_release"][
                "artifacts"
            ][0].update(yanked=True),
            "artifact is invalid",
        ),
    ],
)
def test_fixed_release_metadata_drift_fails_closed(mutation, message: str) -> None:
    document = released_fixture()
    mutation(document)

    with pytest.raises(MODULE.ReleaseGateError, match=message):
        MODULE.classify(document)


def test_qualification_without_release_fails_closed() -> None:
    document = contract_fixture()
    document["qualification"] = qualification()

    with pytest.raises(MODULE.ReleaseGateError, match="without a fixed release"):
        MODULE.classify(document)


def test_qualification_fails_if_one_surface_does_not_prove_runtime_behavior() -> None:
    document = released_fixture()
    document["qualification"] = qualification()
    document["qualification"]["surfaces"]["skyline"][
        "runtime_hostname_verification"
    ] = False

    with pytest.raises(MODULE.ReleaseGateError, match="surface is not accepted"):
        MODULE.classify(document)


def test_mainline_advisory_source_discrepancy_is_immutable() -> None:
    document = contract_fixture()
    document["mainline_observation"]["tags"][0]["source_probe_present"] = True

    with pytest.raises(MODULE.ReleaseGateError, match="observation drifted"):
        MODULE.classify(document)


def test_exact_upstream_revisions_are_immutable() -> None:
    mutations = (
        ("advisory", "security_revision"),
        ("stable_series", "patch_revision"),
        ("mainline_observation", "patch_revision"),
    )
    for section, field in mutations:
        document = contract_fixture()
        document[section][field] = "f" * 40

        with pytest.raises(MODULE.ReleaseGateError):
            MODULE.classify(document)


def test_non_object_mainline_tag_fails_closed() -> None:
    document = contract_fixture()
    document["mainline_observation"]["tags"][0] = "18.0.0"

    with pytest.raises(MODULE.ReleaseGateError, match="mainline tags are invalid"):
        MODULE.classify(document)


def test_unknown_contract_field_fails_closed() -> None:
    document = contract_fixture()
    document["unexpected"] = True

    with pytest.raises(MODULE.ReleaseGateError, match="release gate is invalid"):
        MODULE.classify(document)


def test_loader_rejects_linked_contract(tmp_path: Path) -> None:
    linked = tmp_path / "gate.json"
    linked.symlink_to(CONTRACT)

    with pytest.raises(MODULE.ReleaseGateError, match="missing or linked"):
        MODULE.load_contract(linked)


def test_checked_in_contract_is_canonical_and_classifiable() -> None:
    document = MODULE.load_contract(CONTRACT)

    assert CONTRACT.read_text(encoding="utf-8") == (
        json.dumps(document, indent=2, sort_keys=True) + "\n"
    )
    assert MODULE.classify(document)["status"] == "blocked"
