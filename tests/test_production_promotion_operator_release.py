from __future__ import annotations

import importlib.util
import json
import stat
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "poc" / "production-promotion" / "operator_release.py"
KOLLA_TEST_SOURCE = (
    ROOT / "tests" / "test_production_promotion_kolla_multinode.py"
)


def _load(name: str, path: Path) -> object:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


operator = _load("coffer_test_production_operator_release", SOURCE)
kolla_test = _load(
    "coffer_operator_release_kolla_test_helpers",
    KOLLA_TEST_SOURCE,
)

KOLLA_RESULT_DIGEST = f"sha256:{'f' * 64}"
ADR_NAMES = tuple(operator.adr_dispositions())


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def final_dispositions() -> dict[str, str]:
    return {
        name: "accepted"
        for name in ADR_NAMES
    }


def prerequisites() -> dict[str, str]:
    return {
        **kolla_test.prerequisites(),
        "kolla_multinode_result_sha256": KOLLA_RESULT_DIGEST,
    }


def kolla_result() -> dict[str, object]:
    return kolla_test.kolla.compile_result(**kolla_test.compile_inputs())


def evidence(
    *,
    dispositions: dict[str, str] | None = None,
    prerequisite_values: dict[str, str] | None = None,
) -> dict[str, object]:
    artifact = kolla_test.load_test.artifact_result()
    adr_values = dispositions or final_dispositions()
    return {
        "adr_review": {
            "dispositions": adr_values,
            "evidence_sha256": _digest(1),
            "reviewed_count": len(adr_values),
            "unresolved_count": 0,
        },
        "documentation": {
            "checks": {
                name: True for name in operator.DOCUMENTATION_CHECKS
            },
            "evidence_sha256": _digest(2),
            "local_links_valid": True,
            "markdown_fences_valid": True,
            "release_notes_sha256": operator._sha256(
                operator.RELEASE_NOTES_SOURCE
            ),
            "reviewed_document_count": operator.reviewed_document_count(),
        },
        "evidence_sha256": {
            name: _digest(index)
            for index, name in enumerate(
                operator.EVIDENCE_HASH_NAMES, start=10
            )
        },
        "execution": {
            "adapter": "independent-review",
            "independent_reviewer_count": 1,
            "no_waivers": True,
            "non_synthetic": True,
            "release_revision": artifact["cross_architecture"][
                "core_revision"
            ],
            "review_duration_seconds": 3_600,
            "reviewer_count": 2,
            "source_tree_clean": True,
            "tag": f"v{operator.project_version()}",
            "version": operator.project_version(),
        },
        "prerequisites": prerequisite_values or prerequisites(),
        "release_review": {
            "checks": {
                name: True
                for name in operator.RELEASE_REVIEW_CHECKS
            },
            "evidence_sha256": _digest(4),
        },
        "repository_verification": {
            "checks": {
                name: True for name in operator.REPOSITORY_CHECKS
            },
            "evidence_sha256": _digest(5),
            "full_regression_count": 1_823,
            "kolla_lifecycle_count": 107,
            "promotion_harness_count": 150,
            "secret_scan_count": 10_000,
        },
        "residue": {
            **{name: 0 for name in operator.RESIDUE_KEYS},
            "total": 0,
        },
        "schema": operator.EVIDENCE_SCHEMA,
        "source": operator.review_source_hashes(),
        "supply_chain": {
            "checks": {
                name: True for name in operator.SUPPLY_CHAIN_CHECKS
            },
            "critical_findings": 0,
            "evidence_sha256": _digest(6),
            "high_findings": 0,
            "image_signature_bundle_sha256": _digest(7),
            "provenance_bundle_sha256": _digest(8),
            "sbom_bundle_sha256": _digest(9),
            "source_archive_sha256": _digest(20),
            "vulnerability_bundle_sha256": _digest(21),
        },
    }


def compile_inputs() -> dict[str, object]:
    inputs = kolla_test.compile_inputs()
    inputs.update(
        {
            "evidence": evidence(),
            "evidence_digest": f"sha256:{'e' * 64}",
            "kolla_multinode_digest": KOLLA_RESULT_DIGEST,
            "kolla_multinode_result": kolla_result(),
        }
    )
    return inputs


def _patch_final_adrs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        operator,
        "adr_dispositions",
        final_dispositions,
    )
    monkeypatch.setattr(
        operator,
        "release_notes_status",
        lambda: "production-candidate",
    )


def _write_private(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_compiles_final_operator_release_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_final_adrs(monkeypatch)

    result = operator.compile_result(**compile_inputs())

    assert result["schema"] == operator.SCHEMA
    assert result["production_candidate"] is True
    assert result["adr_review"]["unresolved_count"] == 0
    assert result["documentation"]["check_count"] == 15
    assert result["supply_chain"]["critical_findings"] == 0
    assert operator.validate_final_result(result) == result


def test_unresolved_adrs_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = final_dispositions()
    current[ADR_NAMES[0]] = "proposed"
    monkeypatch.setattr(operator, "adr_dispositions", lambda: current)
    monkeypatch.setattr(
        operator,
        "release_notes_status",
        lambda: "production-candidate",
    )
    inputs = compile_inputs()
    inputs["evidence"]["adr_review"]["dispositions"] = current
    inputs["evidence"]["adr_review"]["reviewed_count"] = len(current)

    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="unresolved decisions",
    ):
        operator.compile_result(**inputs)


def test_current_release_notes_status_fails_closed() -> None:
    assert operator.release_notes_status() == "blocked"
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="documentation validation",
    ):
        operator.compile_result(**compile_inputs())


def test_release_and_first_nine_specialists_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_final_adrs(monkeypatch)
    blocked = compile_inputs()
    blocked["release_readiness"] = (
        kolla_test.load_test.observability_test.data_test.maintenance_test.release(
            False
        )
    )
    blocked["evidence"] = {}
    with pytest.raises(
        operator.OperatorReleaseInputsBlocked,
        match="not candidate-qualified",
    ):
        operator.compile_result(**blocked)

    changed_kolla = compile_inputs()
    changed_kolla["kolla_multinode_result"]["topology"][
        "controller_count"
    ] = 2
    with pytest.raises(
        operator.OperatorReleaseInputsBlocked,
        match="Kolla multinode",
    ):
        operator.compile_result(**changed_kolla)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("execution", "no_waivers", False, "execution"),
        ("execution", "reviewer_count", 1, "independent"),
        (
            "documentation",
            "local_links_valid",
            False,
            "documentation validation",
        ),
        (
            "supply_chain",
            "high_findings",
            1,
            "unresolved findings",
        ),
        (
            "repository_verification",
            "secret_scan_count",
            0,
            "secret scan count",
        ),
    ],
)
def test_review_sections_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    _patch_final_adrs(monkeypatch)
    inputs = compile_inputs()
    inputs["evidence"][section][field] = value
    with pytest.raises(operator.OperatorReleaseResultError, match=message):
        operator.compile_result(**inputs)


def test_check_maps_and_residue_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_final_adrs(monkeypatch)
    documentation = compile_inputs()
    documentation["evidence"]["documentation"]["checks"]["upgrade"] = False
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="documentation checks",
    ):
        operator.compile_result(**documentation)

    release_review = compile_inputs()
    release_review["evidence"]["release_review"]["checks"][
        "production_boundary_accurate"
    ] = False
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="release review checks",
    ):
        operator.compile_result(**release_review)

    residue = compile_inputs()
    residue["evidence"]["residue"]["secret_files"] = 1
    residue["evidence"]["residue"]["total"] = 1
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="retained residue",
    ):
        operator.compile_result(**residue)


def test_source_and_prerequisite_bindings_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_final_adrs(monkeypatch)
    source = compile_inputs()
    source["evidence"]["source"]["tests_tree_sha256"] = _digest(30)
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="binding",
    ):
        operator.compile_result(**source)

    prerequisite = compile_inputs()
    prerequisite["evidence"]["prerequisites"][
        "kolla_multinode_result_sha256"
    ] = _digest(31)
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="binding",
    ):
        operator.compile_result(**prerequisite)


def test_cli_blocks_before_missing_downstream_inputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    release_path = directory / "release.json"
    output = directory / "result.json"
    _write_private(
        release_path,
        kolla_test.load_test.observability_test.data_test.maintenance_test.release(
            False
        ),
    )

    result = operator.main(
        [
            "--release-readiness",
            str(release_path),
            "--artifact-result",
            str(directory / "missing-artifact.json"),
            "--rgw-kms-result",
            str(directory / "missing-rgw.json"),
            "--maintenance-identity-result",
            str(directory / "missing-maintenance.json"),
            "--data-protection-result",
            str(directory / "missing-data.json"),
            "--observability-result",
            str(directory / "missing-observability.json"),
            "--gc-retention-result",
            str(directory / "missing-gc.json"),
            "--load-soak-result",
            str(directory / "missing-load.json"),
            "--kolla-multinode-result",
            str(directory / "missing-kolla.json"),
            "--evidence",
            str(directory / "missing-evidence.json"),
            "--output",
            str(output),
        ]
    )

    assert result == 3
    assert not output.exists()
    assert "not candidate-qualified" in capsys.readouterr().err


def test_final_result_rejects_source_summary_or_digest_tamper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_final_adrs(monkeypatch)
    result = operator.compile_result(**compile_inputs())

    source = deepcopy(result)
    source["source"]["tests_tree_sha256"] = _digest(40)
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="not qualified",
    ):
        operator.validate_final_result(source)

    summary = deepcopy(result)
    summary["documentation"]["check_count"] = 14
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="documentation summary",
    ):
        operator.validate_final_result(summary)

    digest = deepcopy(result)
    digest["evidence_sha256"]["release_review_sha256"] = "invalid"
    with pytest.raises(
        operator.OperatorReleaseResultError,
        match="invalid",
    ):
        operator.validate_final_result(digest)


def test_private_writer_creates_owner_only_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_final_adrs(monkeypatch)
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    output = directory / "result.json"
    result = operator.compile_result(**compile_inputs())

    operator._write_private(output.resolve(), result)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert operator.validate_final_result(
        json.loads(output.read_text(encoding="utf-8"))
    )["production_candidate"] is True
