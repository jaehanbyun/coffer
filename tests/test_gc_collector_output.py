from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_DIR = ROOT / "poc" / "gc-retention"
OUTPUT_PATH = ROOT / "tests" / "fixtures" / "gc_v3_1_1_dry_run.txt"
TOPOLOGY_PATH = MODULE_DIR / "topology.json"
VERSION = "v3.1.1"
REVISION = "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"
DELETED_REPOSITORY = "p/33333333-3333-4333-8333-333333333333/deleted"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PARSER = _load_module(
    "coffer_gc_collector_output_tests",
    MODULE_DIR / "collector_output.py",
)
STATE = _load_module(
    "coffer_gc_collector_state_tests",
    MODULE_DIR / "state_machine.py",
)


def topology() -> dict:
    return STATE.load_topology(TOPOLOGY_PATH)


def output() -> str:
    return OUTPUT_PATH.read_text(encoding="utf-8")


def expected_candidates() -> frozenset:
    candidates = {
        PARSER.Candidate("blob", None, f"sha256:{digit * 64}")
        for digit in "1234"
    }
    candidates.update(
        {
            PARSER.Candidate(
                "layer-link",
                DELETED_REPOSITORY,
                f"sha256:{digit * 64}",
            )
            for digit in "23"
        }
    )
    return frozenset(candidates)


def normalize(text: str | None = None, **kwargs):
    return PARSER.normalize_dry_run(
        output() if text is None else text,
        topology=topology(),
        distribution_version=VERSION,
        distribution_revision=REVISION,
        **kwargs,
    )


def test_exact_v3_1_1_output_normalizes_to_bounded_public_evidence() -> None:
    result = normalize(expected_candidates=expected_candidates())

    assert result.candidates == expected_candidates()
    assert result.public == {
        "schema": PARSER.OUTPUT_SCHEMA,
        "distribution_version": VERSION,
        "distribution_revision": REVISION,
        "repository_count": 3,
        "marked_blob_count": 9,
        "observed_mark_line_count": 5,
        "eligible_blob_count": 4,
        "eligible_manifest_count": 0,
        "eligible_link_count": 2,
        "candidate_total": 6,
        "candidate_set_hash": result.public["candidate_set_hash"],
        "normalized_output_hash": result.public["normalized_output_hash"],
    }
    serialized = json.dumps(result.public, sort_keys=True)
    assert "11111111-1111-4111-8111-111111111111" not in serialized
    assert DELETED_REPOSITORY not in serialized
    assert f"sha256:{'1' * 64}" not in serialized


def test_candidate_order_does_not_change_normalized_hashes() -> None:
    lines = output().splitlines()
    prefix = lines[:11]
    candidates = list(reversed(lines[11:]))
    reordered = "\n".join([*prefix, *candidates, ""])

    first = normalize()
    second = normalize(reordered)

    assert first.candidates == second.candidates
    assert (
        first.public["candidate_set_hash"]
        == second.public["candidate_set_hash"]
    )
    assert (
        first.public["normalized_output_hash"]
        == second.public["normalized_output_hash"]
    )


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        (
            lambda text: text.replace(
                "9 blobs marked, 4 blobs",
                "9 blobs marked, 3 blobs",
            ),
            "summary",
        ),
        (
            lambda text: text.replace(
                f"sha256:{'4' * 64}",
                f"sha256:{'1' * 64}",
                1,
            ),
            "duplicated",
        ),
        (
            lambda text: text + "unexpected collector line\n",
            "not recognized",
        ),
        (
            lambda text: text.replace(
                f"sha256:{'4' * 64}",
                "sha256:not-a-digest",
            ),
            "not recognized",
        ),
        (
            lambda text: text
            + "manifest eligible for deletion: "
            + "{p/33333333-3333-4333-8333-333333333333/deleted "
            + f"sha256:{'5' * 64} []"
            + "}\n",
            "untagged",
        ),
        (
            lambda text: text + "Authorization: Bearer do-not-retain-value\n",
            "secret-like",
        ),
    ],
)
def test_malformed_unknown_duplicate_or_secret_output_is_refused(
    changed,
    message,
) -> None:
    with pytest.raises(PARSER.CollectorOutputError, match=message):
        normalize(changed(output()))


@pytest.mark.parametrize(
    ("version", "revision"),
    [
        ("v3.1.0", REVISION),
        (VERSION, "f" * 40),
        (VERSION, "not-a-revision"),
    ],
)
def test_mixed_release_binding_is_refused(version, revision) -> None:
    with pytest.raises(PARSER.CollectorOutputError, match="release"):
        PARSER.normalize_dry_run(
            output(),
            topology=topology(),
            distribution_version=version,
            distribution_revision=revision,
        )


def test_retained_intersection_or_expected_candidate_drift_is_refused() -> None:
    with pytest.raises(PARSER.CollectorOutputError, match="retained"):
        normalize(retained_digests=frozenset({f"sha256:{'2' * 64}"}))

    changed = set(expected_candidates())
    changed.remove(next(iter(changed)))
    with pytest.raises(PARSER.CollectorOutputError, match="candidate set"):
        normalize(expected_candidates=frozenset(changed))


def test_empty_missing_summary_and_oversized_output_are_refused() -> None:
    with pytest.raises(PARSER.CollectorOutputError, match="size"):
        normalize("")
    without_summary = "\n".join(
        line for line in output().splitlines() if "blobs marked" not in line
    )
    with pytest.raises(PARSER.CollectorOutputError, match="summary"):
        normalize(without_summary)
    with pytest.raises(PARSER.CollectorOutputError, match="size"):
        normalize("x" * (PARSER.MAX_OUTPUT_BYTES + 1))


def test_candidate_limit_is_enforced_before_evidence() -> None:
    text = output()
    extra = []
    for index in range(995):
        extra.append(
            "blob eligible for deletion: sha256:"
            + f"{index:064x}"
        )
    text = text.replace(
        "9 blobs marked, 4 blobs",
        "9 blobs marked, 999 blobs",
    )
    text += "\n".join(extra) + "\n"

    with pytest.raises(PARSER.CollectorOutputError, match="limit"):
        normalize(text)


def test_normalizer_has_no_collector_subprocess_or_external_adapter() -> None:
    source = (MODULE_DIR / "collector_output.py").read_text(encoding="utf-8")

    for forbidden in (
        "import boto",
        "import requests",
        "import socket",
        "import sqlalchemy",
        "import subprocess",
        "urllib",
    ):
        assert forbidden not in source
