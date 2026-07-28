from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

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


def pypi_artifact(
    version: str,
    package_type: str,
    digest: str,
) -> dict[str, object]:
    filename = {
        "bdist_wheel": f"oslo_messaging-{version}-py3-none-any.whl",
        "sdist": f"oslo_messaging-{version}.tar.gz",
    }[package_type]
    return {
        "digests": {"sha256": digest},
        "filename": filename,
        "packagetype": package_type,
        "yanked": False,
    }


def observer_metadata(
    *,
    candidate: bool,
    constraint: str | None = None,
    include_patch: bool = True,
    include_probe: bool = True,
) -> tuple[dict[str, object], dict[str, bytes]]:
    releases: dict[str, object] = {
        "17.3.0": [
            pypi_artifact("17.3.0", "bdist_wheel", "1" * 64),
            pypi_artifact("17.3.0", "sdist", "2" * 64),
        ],
        "18.2.0": [],
    }
    json_values: dict[str, object] = {}
    byte_values: dict[str, bytes] = {}
    if candidate:
        releases["17.3.1"] = [
            pypi_artifact("17.3.1", "bdist_wheel", "a" * 64),
            pypi_artifact("17.3.1", "sdist", "b" * 64),
        ]
    json_values[MODULE.PYPI_METADATA_URL] = {
        "info": {"version": "18.2.0"},
        "releases": releases,
    }
    selected = constraint or (
        "oslo.messaging===17.3.1"
        if candidate
        else "oslo.messaging===17.3.0"
    )
    byte_values[MODULE.UPPER_CONSTRAINTS_URL] = (
        f"alembic===1.18.5\n{selected}\nSQLAlchemy===2.0.51\n".encode()
    )
    if candidate and selected == "oslo.messaging===17.3.1":
        source_url = MODULE.COMMIT_SOURCE_TEMPLATE.format(
            revision="d" * 40
        )
        source = b"ssl = config\n"
        if include_probe:
            source += MODULE.SOURCE_PROBE + b" = True\n"
        byte_values[source_url] = source
        history_url = (
            f"{MODULE.OPENDEV_API}/commits?sha={'d' * 40}&path="
            f"{quote(MODULE.SOURCE_PATH, safe='')}&limit=50"
        )
        history = [{"sha": "9" * 40}]
        if include_patch:
            history.insert(0, {"sha": MODULE.STABLE_PATCH_REVISION})
        json_values[history_url] = history
        reference_url = (
            f"{MODULE.OPENDEV_API}/git/refs/tags/17.3.1"
        )
        json_values[reference_url] = [
            {
                "object": {
                    "sha": "e" * 40,
                    "type": "tag",
                    "url": "ignored",
                },
                "ref": "refs/tags/17.3.1",
                "url": reference_url,
            }
        ]
        tag_url = f"{MODULE.OPENDEV_API}/git/tags/{'e' * 40}"
        json_values[tag_url] = {
            "message": "oslo.messaging 17.3.1 release",
            "object": {
                "sha": "d" * 40,
                "type": "commit",
                "url": "ignored",
            },
            "sha": "e" * 40,
            "tag": "17.3.1",
            "tagger": {},
            "url": tag_url,
            "verification": {},
        }
    return json_values, byte_values


def refresh_with(
    json_values: dict[str, object],
    byte_values: dict[str, bytes],
    *,
    observed_on: date = date(2026, 7, 29),
) -> dict[str, object]:
    return MODULE.refresh_current_observation(
        contract_fixture(),
        read_json=lambda url: json_values[url],
        read_bytes=lambda url: byte_values[url],
        observed_on=observed_on,
    )


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


def test_official_observer_refreshes_blocked_state_without_source_probe() -> None:
    json_values, byte_values = observer_metadata(candidate=False)
    original = contract_fixture()

    refreshed = refresh_with(json_values, byte_values)

    assert original["current_observation"]["as_of"] == "2026-07-28"
    assert refreshed["current_observation"] == {
        "as_of": "2026-07-29",
        "fixed_stable_release": None,
        "pypi_latest": "18.2.0",
        "stable_releases": ["17.3.0"],
        "upper_constraint": "oslo.messaging===17.3.0",
    }
    assert MODULE.classify(refreshed)["status"] == "blocked"


def test_official_observer_builds_exact_candidate_release() -> None:
    json_values, byte_values = observer_metadata(candidate=True)

    refreshed = refresh_with(json_values, byte_values)
    release = refreshed["current_observation"]["fixed_stable_release"]

    assert release == {
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
        "source_sha256": MODULE.hashlib.sha256(
            byte_values[
                MODULE.COMMIT_SOURCE_TEMPLATE.format(
                    revision="d" * 40
                )
            ]
        ).hexdigest(),
        "tag_revision": "d" * 40,
        "version": "17.3.1",
    }
    assert MODULE.classify(refreshed)["status"] == "candidate-released"


def test_released_candidate_stays_blocked_until_constraints_select_it() -> None:
    json_values, byte_values = observer_metadata(
        candidate=True,
        constraint="oslo.messaging===17.3.0",
    )

    result = MODULE.classify(refresh_with(json_values, byte_values))

    assert result["fixed_stable_release"] is None
    assert result["reasons"] == [
        "stable/2026.1 upper constraints remain at oslo.messaging 17.3.0"
    ]


@pytest.mark.parametrize(
    ("include_patch", "include_probe"),
    [(False, True), (True, False)],
)
def test_observer_refuses_candidate_without_exact_fix(
    include_patch: bool,
    include_probe: bool,
) -> None:
    json_values, byte_values = observer_metadata(
        candidate=True,
        include_patch=include_patch,
        include_probe=include_probe,
    )

    with pytest.raises(MODULE.ReleaseGateError, match="stable patch"):
        refresh_with(json_values, byte_values)


def test_observer_refuses_missing_or_ambiguous_constraint() -> None:
    json_values, byte_values = observer_metadata(candidate=False)
    byte_values[MODULE.UPPER_CONSTRAINTS_URL] = (
        b"oslo.messaging===17.3.0\noslo.messaging===17.3.1\n"
    )

    with pytest.raises(MODULE.ReleaseGateError, match="ambiguous"):
        refresh_with(json_values, byte_values)


def test_observer_refuses_constraint_release_absent_from_pypi() -> None:
    json_values, byte_values = observer_metadata(candidate=False)
    byte_values[MODULE.UPPER_CONSTRAINTS_URL] = (
        b"oslo.messaging===17.3.1\n"
    )

    with pytest.raises(MODULE.ReleaseGateError, match="absent from PyPI"):
        refresh_with(json_values, byte_values)


def test_observer_refuses_ambiguous_candidate_artifacts() -> None:
    json_values, byte_values = observer_metadata(candidate=True)
    releases = json_values[MODULE.PYPI_METADATA_URL]["releases"]
    releases["17.3.1"].append(
        pypi_artifact("17.3.1", "bdist_wheel", "c" * 64)
    )

    with pytest.raises(MODULE.ReleaseGateError, match="ambiguous"):
        refresh_with(json_values, byte_values)


def test_tag_resolver_accepts_one_exact_lightweight_tag() -> None:
    reference_url = f"{MODULE.OPENDEV_API}/git/refs/tags/17.3.1"
    values = {
        reference_url: [
            {
                "object": {
                    "sha": "d" * 40,
                    "type": "commit",
                    "url": "ignored",
                },
                "ref": "refs/tags/17.3.1",
                "url": reference_url,
            }
        ]
    }

    assert MODULE._tag_revision(
        "17.3.1",
        lambda url: values[url],
    ) == "d" * 40


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


def test_cli_offline_mode_validates_checked_in_baseline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = MODULE.main(
        ["--offline-contract", "--allow-blocked"]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
