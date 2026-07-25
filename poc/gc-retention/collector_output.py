from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


OUTPUT_SCHEMA = "coffer.gc-collector-output/v1"
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_LINE_BYTES = 8192
DIGEST_PATTERN = r"sha256:[0-9a-f]{64}"
REPOSITORY_PATTERN = (
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+"
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_LINE = re.compile(rf"^(?P<repository>{REPOSITORY_PATTERN})$")
MARK_LINE = re.compile(
    rf"^(?P<repository>{REPOSITORY_PATTERN}): marking "
    rf"(?P<kind>manifest|blob) (?P<digest>{DIGEST_PATTERN})\s*$"
)
MISSING_TAGS_LINE = re.compile(
    rf"^manifest tags path of repository "
    rf"(?P<repository>{REPOSITORY_PATTERN}) does not exist$"
)
MANIFEST_CANDIDATE_LINE = re.compile(
    rf"^manifest eligible for deletion: "
    rf"\{{(?P<repository>{REPOSITORY_PATTERN}) "
    rf"(?P<digest>{DIGEST_PATTERN}) \[(?P<tags>[^\]]*)\]\}}$"
)
SUMMARY_LINE = re.compile(
    r"^(?P<marked>[0-9]+) blobs marked, "
    r"(?P<blobs>[0-9]+) blobs and "
    r"(?P<manifests>[0-9]+) manifests eligible for deletion$"
)
BLOB_CANDIDATE_LINE = re.compile(
    rf"^blob eligible for deletion: (?P<digest>{DIGEST_PATTERN})$"
)
LAYER_CANDIDATE_LINE = re.compile(
    rf"^(?P<repository>{REPOSITORY_PATTERN}): "
    rf"layer link eligible for deletion: (?P<digest>{DIGEST_PATTERN})$"
)
SECRET_PATTERNS = (
    re.compile(r"(?i)\bauthorization\s*:"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."),
)


class CollectorOutputError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Candidate:
    kind: str
    repository: str | None
    digest: str


@dataclass(frozen=True)
class NormalizedOutput:
    public: Mapping[str, Any]
    candidates: frozenset[Candidate]


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _candidate_hash(candidates: Iterable[Candidate]) -> str:
    identities = sorted(
        _hash(
            {
                "kind": candidate.kind,
                "repository": candidate.repository,
                "digest": candidate.digest,
            }
        )
        for candidate in candidates
    )
    return _hash(identities)


def _validate_release(
    topology: Mapping[str, Any],
    distribution_version: str,
    distribution_revision: str,
) -> None:
    try:
        collector = topology["collector"]
        expected_version = collector["distribution_version"]
        expected_revision = collector["distribution_revision"]
    except (KeyError, TypeError) as error:
        raise CollectorOutputError("collector topology is incomplete") from error
    if (
        distribution_version != expected_version
        or distribution_revision != expected_revision
        or REVISION_PATTERN.fullmatch(distribution_revision) is None
    ):
        raise CollectorOutputError("collector release binding changed")
    if collector.get("allow_delete_untagged") is not False:
        raise CollectorOutputError("untagged deletion must remain disabled")
    limit = collector.get("candidate_limit")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise CollectorOutputError("collector candidate limit is invalid")


def normalize_dry_run(
    output: str,
    *,
    topology: Mapping[str, Any],
    distribution_version: str,
    distribution_revision: str,
    expected_candidates: frozenset[Candidate] | None = None,
    retained_digests: frozenset[str] = frozenset(),
) -> NormalizedOutput:
    _validate_release(
        topology,
        distribution_version,
        distribution_revision,
    )
    if not isinstance(output, str):
        raise CollectorOutputError("collector output must be text")
    try:
        encoded = output.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise CollectorOutputError("collector output is not UTF-8") from error
    if not encoded or len(encoded) > MAX_OUTPUT_BYTES:
        raise CollectorOutputError("collector output size is invalid")
    if "\x00" in output or "\r" in output:
        raise CollectorOutputError("collector output has control characters")
    if any(pattern.search(output) for pattern in SECRET_PATTERNS):
        raise CollectorOutputError("collector output contains secret-like text")

    repositories: set[str] = set()
    marked: set[tuple[str, str, str]] = set()
    candidates: set[Candidate] = set()
    summary: tuple[int, int, int] | None = None

    for line in output.split("\n"):
        if not line:
            continue
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            raise CollectorOutputError("collector output line is too long")
        matched = REPOSITORY_LINE.fullmatch(line)
        if matched:
            repository = matched.group("repository")
            if summary is not None:
                raise CollectorOutputError(
                    "repository output appeared after collector summary"
                )
            if repository in repositories:
                raise CollectorOutputError("collector repository is duplicated")
            repositories.add(repository)
            continue
        matched = MARK_LINE.fullmatch(line)
        if matched:
            if summary is not None:
                raise CollectorOutputError(
                    "mark output appeared after collector summary"
                )
            repository = matched.group("repository")
            if repository not in repositories:
                raise CollectorOutputError(
                    "mark output preceded repository enumeration"
                )
            marked.add(
                (
                    repository,
                    matched.group("kind"),
                    matched.group("digest"),
                )
            )
            continue
        matched = MISSING_TAGS_LINE.fullmatch(line)
        if matched:
            if (
                summary is not None
                or matched.group("repository") not in repositories
            ):
                raise CollectorOutputError(
                    "tag output is outside repository enumeration"
                )
            continue
        if MANIFEST_CANDIDATE_LINE.fullmatch(line):
            raise CollectorOutputError(
                "manifest candidate implies forbidden untagged deletion"
            )
        matched = SUMMARY_LINE.fullmatch(line)
        if matched:
            if summary is not None:
                raise CollectorOutputError("collector summary is duplicated")
            summary = tuple(
                int(matched.group(name))
                for name in ("marked", "blobs", "manifests")
            )
            continue
        matched = BLOB_CANDIDATE_LINE.fullmatch(line)
        if matched:
            if summary is None:
                raise CollectorOutputError(
                    "blob candidate preceded collector summary"
                )
            candidate = Candidate(
                kind="blob",
                repository=None,
                digest=matched.group("digest"),
            )
        else:
            matched = LAYER_CANDIDATE_LINE.fullmatch(line)
            if not matched:
                raise CollectorOutputError(
                    "collector output line is not recognized"
                )
            repository = matched.group("repository")
            if summary is None:
                raise CollectorOutputError(
                    "layer candidate preceded collector summary"
                )
            if repository not in repositories:
                raise CollectorOutputError(
                    "layer candidate has an unknown repository"
                )
            candidate = Candidate(
                kind="layer-link",
                repository=repository,
                digest=matched.group("digest"),
            )
        if candidate in candidates:
            raise CollectorOutputError("collector candidate is duplicated")
        candidates.add(candidate)

    if summary is None:
        raise CollectorOutputError("collector summary is missing")
    marked_count, eligible_blob_count, eligible_manifest_count = summary
    unique_marked_digests = {
        digest for _, _, digest in marked
    }
    if marked_count < 1 or len(unique_marked_digests) > marked_count:
        raise CollectorOutputError("collector marked summary is inconsistent")
    if eligible_manifest_count != 0:
        raise CollectorOutputError(
            "manifest candidates require forbidden untagged deletion"
        )
    actual_blob_count = sum(
        candidate.kind == "blob" for candidate in candidates
    )
    actual_link_count = sum(
        candidate.kind == "layer-link" for candidate in candidates
    )
    if actual_blob_count != eligible_blob_count:
        raise CollectorOutputError("collector blob summary is inconsistent")
    if not repositories:
        raise CollectorOutputError("collector repository set is empty")
    if len(candidates) < 1:
        raise CollectorOutputError("collector candidate set is empty")
    if len(candidates) > topology["collector"]["candidate_limit"]:
        raise CollectorOutputError("collector candidate limit exceeded")
    if any(candidate.digest in retained_digests for candidate in candidates):
        raise CollectorOutputError("collector candidate intersects retained content")
    frozen_candidates = frozenset(candidates)
    if (
        expected_candidates is not None
        and frozen_candidates != expected_candidates
    ):
        raise CollectorOutputError("collector candidate set changed")

    candidate_set_hash = _candidate_hash(frozen_candidates)
    public = {
        "schema": OUTPUT_SCHEMA,
        "distribution_version": distribution_version,
        "distribution_revision": distribution_revision,
        "repository_count": len(repositories),
        "marked_blob_count": marked_count,
        "observed_mark_line_count": len(marked),
        "eligible_blob_count": actual_blob_count,
        "eligible_manifest_count": 0,
        "eligible_link_count": actual_link_count,
        "candidate_total": len(candidates),
        "candidate_set_hash": candidate_set_hash,
        "normalized_output_hash": _hash(
            {
                "release": {
                    "version": distribution_version,
                    "revision": distribution_revision,
                },
                "repository_hashes": sorted(_hash(item) for item in repositories),
                "mark_hashes": sorted(_hash(item) for item in marked),
                "candidate_set_hash": candidate_set_hash,
                "summary": {
                    "marked": marked_count,
                    "blobs": actual_blob_count,
                    "manifests": 0,
                    "links": actual_link_count,
                },
            }
        ),
    }
    serialized = json.dumps(public, sort_keys=True)
    if any(
        repository in serialized for repository in repositories
    ) or any(candidate.digest in serialized for candidate in candidates):
        raise CollectorOutputError("public evidence retained collector identity")
    return NormalizedOutput(
        public=public,
        candidates=frozen_candidates,
    )
