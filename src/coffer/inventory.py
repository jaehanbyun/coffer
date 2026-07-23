from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from coffer.quota import (
    IMAGE_MEDIA_TYPES,
    INDEX_MEDIA_TYPES,
    MAX_DESCRIPTOR_COUNT,
    MAX_LOGICAL_BYTES,
    MAX_MANIFEST_BYTES,
    SHA256_DIGEST,
)
from coffer.tokens import PROJECT_ID, REPOSITORY_NAME, REPOSITORY_SUFFIX


EVIDENCE_SCHEMA = "coffer.distribution-storage-scan/v1"
AUTHORITY_SCHEMA = "coffer.repository-authority/v1"
INVENTORY_SCHEMA = "coffer.inventory/v1"
PINNED_DISTRIBUTION_VERSION = "v3.1.1"
PINNED_ENUMERATOR = (
    "distribution.storage.RepositoryEnumerator+ManifestEnumerator"
)
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PAGE_SIZE = 1000
MAX_PAGE_COUNT = 100_000
MAX_RECORD_COUNT = 10_000_000
MAX_MEDIA_TYPE_BYTES = 255
MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")


class InvalidInventoryEvidence(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ReferenceFact:
    digest: str
    media_type: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "media_type": self.media_type,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class ManifestFact:
    repository: str
    enumerated_digest: str
    content_digest: str
    media_type: str
    size: int
    tagged: bool
    references: tuple[ReferenceFact, ...]

    @property
    def key(self) -> str:
        return f"{self.repository}@{self.enumerated_digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "content_digest": self.content_digest,
            "enumerated_digest": self.enumerated_digest,
            "media_type": self.media_type,
            "references": [reference.to_dict() for reference in self.references],
            "repository": self.repository,
            "size": self.size,
            "tagged": self.tagged,
        }


@dataclass(frozen=True, slots=True)
class RepositoryAuthority:
    id: str
    project_id: str
    name: str

    @property
    def canonical_name(self) -> str:
        return f"p/{self.project_id}/{self.name}"


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    repositories: tuple[str, ...]
    records: tuple[ManifestFact, ...]


def _fail(message: str) -> InvalidInventoryEvidence:
    return InvalidInventoryEvidence(message)


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise _fail(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail(f"{label} must be an array")
    return value


def _exact_keys(
    value: dict[str, object], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise _fail(f"{label} fields are invalid")


def _integer(
    value: object,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_LOGICAL_BYTES,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise _fail(f"{label} is outside its allowed integer range")
    return value


def _string(value: object, label: str, *, maximum_bytes: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode()) > maximum_bytes
    ):
        raise _fail(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    digest = _string(value, label, maximum_bytes=71)
    if SHA256_DIGEST.fullmatch(digest) is None:
        raise _fail(f"{label} must be canonical sha256")
    return digest


def _media_type(value: object, label: str) -> str:
    media_type = _string(value, label, maximum_bytes=MAX_MEDIA_TYPE_BYTES)
    if MEDIA_TYPE.fullmatch(media_type) is None:
        raise _fail(f"{label} is invalid")
    return media_type


def _parse_reference(value: object, label: str) -> ReferenceFact:
    raw = _object(value, label)
    _exact_keys(raw, {"digest", "media_type", "size"}, label)
    return ReferenceFact(
        digest=_digest(raw["digest"], f"{label}.digest"),
        media_type=_media_type(raw["media_type"], f"{label}.media_type"),
        size=_integer(raw["size"], f"{label}.size"),
    )


def _parse_manifest(value: object, label: str) -> ManifestFact:
    raw = _object(value, label)
    _exact_keys(
        raw,
        {
            "content_digest",
            "enumerated_digest",
            "media_type",
            "references",
            "repository",
            "size",
            "tagged",
        },
        label,
    )
    repository = _string(raw["repository"], f"{label}.repository")
    if REPOSITORY_NAME.fullmatch(repository) is None:
        raise _fail(f"{label}.repository is not canonical")
    enumerated_digest = _digest(
        raw["enumerated_digest"], f"{label}.enumerated_digest"
    )
    content_digest = _digest(raw["content_digest"], f"{label}.content_digest")
    if content_digest != enumerated_digest:
        raise _fail(f"{label} payload digest does not match its revision link")
    media_type = _media_type(raw["media_type"], f"{label}.media_type")
    if media_type not in IMAGE_MEDIA_TYPES | INDEX_MEDIA_TYPES:
        raise _fail(f"{label}.media_type is not supported")
    size = _integer(
        raw["size"], f"{label}.size", minimum=1, maximum=MAX_MANIFEST_BYTES
    )
    tagged = raw["tagged"]
    if not isinstance(tagged, bool):
        raise _fail(f"{label}.tagged must be a boolean")
    references = _array(raw["references"], f"{label}.references")
    if len(references) >= MAX_DESCRIPTOR_COUNT:
        raise _fail(f"{label} has too many references")
    parsed_references = tuple(
        _parse_reference(reference, f"{label}.references[{index}]")
        for index, reference in enumerate(references)
    )
    reference_digests = [reference.digest for reference in parsed_references]
    if reference_digests != sorted(set(reference_digests)):
        raise _fail(f"{label}.references must be unique and digest-sorted")
    if media_type in INDEX_MEDIA_TYPES:
        if not parsed_references:
            raise _fail(f"{label} index has no child manifests")
        if any(
            reference.media_type not in IMAGE_MEDIA_TYPES | INDEX_MEDIA_TYPES
            for reference in parsed_references
        ):
            raise _fail(f"{label} index has an unsupported child media type")
    return ManifestFact(
        repository=repository,
        enumerated_digest=enumerated_digest,
        content_digest=content_digest,
        media_type=media_type,
        size=size,
        tagged=tagged,
        references=parsed_references,
    )


def _canonical_record_bytes(record: ManifestFact) -> bytes:
    return (
        json.dumps(record.to_dict(), separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _record_hash(records: tuple[ManifestFact, ...]) -> str:
    checksum = hashlib.sha256()
    for record in records:
        checksum.update(_canonical_record_bytes(record))
    return f"sha256:{checksum.hexdigest()}"


def _repository_hash(repositories: tuple[str, ...]) -> str:
    checksum = hashlib.sha256()
    for repository in repositories:
        checksum.update(f"{repository}\n".encode())
    return f"sha256:{checksum.hexdigest()}"


def _parse_scan(
    value: object, *, expected_phase: str, page_size: int
) -> StorageSnapshot:
    scan = _object(value, f"{expected_phase} scan")
    _exact_keys(
        scan,
        {"pages", "phase", "repositories", "summary"},
        f"{expected_phase} scan",
    )
    if scan["phase"] != expected_phase:
        raise _fail("evidence scans must be ordered start then end")
    raw_repositories = _array(
        scan["repositories"], f"{expected_phase} scan repositories"
    )
    if len(raw_repositories) > MAX_RECORD_COUNT:
        raise _fail(f"{expected_phase} scan has too many repositories")
    repositories = tuple(
        _string(repository, f"{expected_phase} scan repository {index}")
        for index, repository in enumerate(raw_repositories)
    )
    if repositories != tuple(sorted(set(repositories))) or any(
        REPOSITORY_NAME.fullmatch(repository) is None
        for repository in repositories
    ):
        raise _fail(
            f"{expected_phase} scan repositories must be canonical, unique, and sorted"
        )
    pages = _array(scan["pages"], f"{expected_phase} scan pages")
    if len(pages) > MAX_PAGE_COUNT:
        raise _fail(f"{expected_phase} scan has too many pages")

    records: list[ManifestFact] = []
    previous_key: str | None = None
    for page_index, page_value in enumerate(pages):
        label = f"{expected_phase} scan page {page_index}"
        page = _object(page_value, label)
        _exact_keys(page, {"after", "items", "next", "sequence"}, label)
        sequence = _integer(
            page["sequence"], f"{label}.sequence", maximum=MAX_PAGE_COUNT
        )
        if sequence != page_index:
            raise _fail(f"{label} sequence is not contiguous")
        after = page["after"]
        if after is not None and not isinstance(after, str):
            raise _fail(f"{label}.after is invalid")
        if after != previous_key:
            raise _fail(f"{label}.after does not continue the prior page")
        items = _array(page["items"], f"{label}.items")
        if not items or len(items) > page_size:
            raise _fail(f"{label} item count is invalid")
        if page_index < len(pages) - 1 and len(items) != page_size:
            raise _fail(f"{label} is short before the final page")
        page_records = [
            _parse_manifest(item, f"{label}.items[{index}]")
            for index, item in enumerate(items)
        ]
        page_keys = [record.key for record in page_records]
        if page_keys != sorted(set(page_keys)):
            raise _fail(f"{label} records must be unique and key-sorted")
        if previous_key is not None and page_keys[0] <= previous_key:
            raise _fail(f"{label} overlaps or reorders the prior page")
        previous_key = page_keys[-1]
        next_value = page["next"]
        if page_index < len(pages) - 1:
            if next_value != previous_key:
                raise _fail(f"{label}.next does not identify its final record")
        elif next_value is not None:
            raise _fail(f"{label}.next must be null on the final page")
        records.extend(page_records)
        if len(records) > MAX_RECORD_COUNT:
            raise _fail(f"{expected_phase} scan has too many records")

    parsed_records = tuple(records)
    if any(record.repository not in repositories for record in parsed_records):
        raise _fail(f"{expected_phase} scan manifest has no repository record")
    summary = _object(scan["summary"], f"{expected_phase} scan summary")
    _exact_keys(
        summary,
        {
            "page_count",
            "record_count",
            "repository_count",
            "repository_sha256",
            "sha256",
        },
        f"{expected_phase} scan summary",
    )
    if _integer(
        summary["page_count"],
        f"{expected_phase} summary.page_count",
        maximum=MAX_PAGE_COUNT,
    ) != len(pages):
        raise _fail(f"{expected_phase} summary page count does not match")
    if _integer(
        summary["record_count"],
        f"{expected_phase} summary.record_count",
        maximum=MAX_RECORD_COUNT,
    ) != len(parsed_records):
        raise _fail(f"{expected_phase} summary record count does not match")
    if _integer(
        summary["repository_count"],
        f"{expected_phase} summary.repository_count",
        maximum=MAX_RECORD_COUNT,
    ) != len(repositories):
        raise _fail(f"{expected_phase} summary repository count does not match")
    repository_summary_hash = _digest(
        summary["repository_sha256"],
        f"{expected_phase} summary.repository_sha256",
    )
    if repository_summary_hash != _repository_hash(repositories):
        raise _fail(f"{expected_phase} repository summary hash does not match")
    summary_hash = _digest(
        summary["sha256"], f"{expected_phase} summary.sha256"
    )
    if summary_hash != _record_hash(parsed_records):
        raise _fail(f"{expected_phase} summary hash does not match")
    return StorageSnapshot(repositories=repositories, records=parsed_records)


def parse_evidence(value: object) -> StorageSnapshot:
    evidence = _object(value, "evidence")
    _exact_keys(
        evidence,
        {
            "distribution_version",
            "enumerator",
            "page_size",
            "scans",
            "schema",
        },
        "evidence",
    )
    if evidence["schema"] != EVIDENCE_SCHEMA:
        raise _fail("evidence schema is unsupported")
    if evidence["distribution_version"] != PINNED_DISTRIBUTION_VERSION:
        raise _fail("evidence Distribution version is not pinned")
    if evidence["enumerator"] != PINNED_ENUMERATOR:
        raise _fail("evidence enumerator is unsupported")
    page_size = _integer(
        evidence["page_size"], "evidence.page_size", minimum=1, maximum=MAX_PAGE_SIZE
    )
    scans = _array(evidence["scans"], "evidence.scans")
    if len(scans) != 2:
        raise _fail("evidence requires exactly two scans")
    start = _parse_scan(scans[0], expected_phase="start", page_size=page_size)
    end = _parse_scan(scans[1], expected_phase="end", page_size=page_size)
    if start != end:
        raise _fail("start and end scans differ")
    return start


def parse_authority(value: object) -> dict[str, RepositoryAuthority]:
    authority = _object(value, "authority")
    _exact_keys(authority, {"repositories", "schema"}, "authority")
    if authority["schema"] != AUTHORITY_SCHEMA:
        raise _fail("authority schema is unsupported")
    repositories = _array(authority["repositories"], "authority.repositories")
    result: dict[str, RepositoryAuthority] = {}
    repository_ids: set[str] = set()
    for index, repository_value in enumerate(repositories):
        label = f"authority.repositories[{index}]"
        raw = _object(repository_value, label)
        _exact_keys(raw, {"id", "name", "project_id"}, label)
        repository_id = _string(raw["id"], f"{label}.id", maximum_bytes=36)
        try:
            if str(uuid.UUID(repository_id)) != repository_id:
                raise ValueError
        except ValueError as exc:
            raise _fail(f"{label}.id is not a canonical UUID") from exc
        project_id = _string(
            raw["project_id"], f"{label}.project_id", maximum_bytes=36
        )
        if PROJECT_ID.fullmatch(project_id) is None:
            raise _fail(f"{label}.project_id is not a canonical project UUID")
        name = _string(raw["name"], f"{label}.name")
        if REPOSITORY_SUFFIX.fullmatch(name) is None:
            raise _fail(f"{label}.name is not a canonical repository suffix")
        record = RepositoryAuthority(repository_id, project_id, name)
        if record.canonical_name in result or repository_id in repository_ids:
            raise _fail("authority contains duplicate repository identity")
        result[record.canonical_name] = record
        repository_ids.add(repository_id)
    return result


def _descriptor(
    descriptors: dict[str, tuple[str, int]],
    *,
    digest: str,
    media_type: str,
    size: int,
    project_id: str,
) -> None:
    existing = descriptors.get(digest)
    if existing is not None and existing != (media_type, size):
        raise _fail(
            f"project {project_id} has conflicting facts for descriptor {digest}"
        )
    descriptors[digest] = (media_type, size)


def build_inventory(evidence: object, authority: object) -> dict[str, object]:
    snapshot = parse_evidence(evidence)
    records = snapshot.records
    authority_by_name = parse_authority(authority)
    by_repository: dict[str, list[ManifestFact]] = {
        repository: [] for repository in snapshot.repositories
    }
    for repository in snapshot.repositories:
        if repository not in authority_by_name:
            raise _fail("backend repository has no exact Coffer authority")
    for record in records:
        by_repository[record.repository].append(record)

    records_by_key = {record.key: record for record in records}
    project_descriptors: dict[str, dict[str, tuple[str, int]]] = {}
    final_repositories: list[dict[str, object]] = []
    for canonical_name in sorted(by_repository):
        authority_record = authority_by_name[canonical_name]
        manifests: list[dict[str, object]] = []
        descriptors = project_descriptors.setdefault(
            authority_record.project_id, {}
        )
        for record in by_repository[canonical_name]:
            _descriptor(
                descriptors,
                digest=record.enumerated_digest,
                media_type=record.media_type,
                size=record.size,
                project_id=authority_record.project_id,
            )
            references = []
            for reference in record.references:
                if record.media_type in INDEX_MEDIA_TYPES:
                    child = records_by_key.get(
                        f"{canonical_name}@{reference.digest}"
                    )
                    if child is None:
                        raise _fail("index child is not an enumerated repository manifest")
                    if (
                        child.media_type != reference.media_type
                        or child.size != reference.size
                    ):
                        raise _fail("index child descriptor facts do not match")
                _descriptor(
                    descriptors,
                    digest=reference.digest,
                    media_type=reference.media_type,
                    size=reference.size,
                    project_id=authority_record.project_id,
                )
                references.append(reference.to_dict())
            manifests.append(
                {
                    "digest": record.enumerated_digest,
                    "media_type": record.media_type,
                    "references": references,
                    "size": record.size,
                }
            )
        final_repositories.append(
            {
                "manifests": manifests,
                "project_id": authority_record.project_id,
                "repository_id": authority_record.id,
            }
        )
    final_repositories.sort(
        key=lambda repository: (
            repository["project_id"],
            repository["repository_id"],
        )
    )

    projects = []
    for project_id in sorted(project_descriptors):
        descriptors = project_descriptors[project_id]
        descriptor_facts = [
            {
                "digest": digest,
                "media_type": facts[0],
                "size": facts[1],
            }
            for digest, facts in sorted(descriptors.items())
        ]
        logical_bytes = sum(item["size"] for item in descriptor_facts)
        if logical_bytes > MAX_LOGICAL_BYTES:
            raise _fail(f"project {project_id} logical bytes exceed the SQL bound")
        projects.append(
            {
                "descriptor_count": len(descriptor_facts),
                "descriptors": descriptor_facts,
                "logical_bytes": logical_bytes,
                "project_id": project_id,
            }
        )

    return {
        "projects": projects,
        "repositories": final_repositories,
        "schema": INVENTORY_SCHEMA,
        "source": {
            "distribution_version": PINNED_DISTRIBUTION_VERSION,
            "enumerator": PINNED_ENUMERATOR,
            "snapshot_scans": 2,
        },
        "summary": {
            "descriptor_count": sum(
                project["descriptor_count"] for project in projects
            ),
            "logical_bytes": sum(project["logical_bytes"] for project in projects),
            "manifest_count": len(records),
            "project_count": len(projects),
            "repository_count": len(final_repositories),
        },
    }


def load_bounded_json(path: Path) -> object:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise _fail(f"cannot stat input {path.name}") from exc
    if not 0 < size <= MAX_INPUT_BYTES:
        raise _fail(f"input {path.name} is empty or too large")
    try:
        payload = path.read_bytes()
        if len(payload) != size or not 0 < len(payload) <= MAX_INPUT_BYTES:
            raise _fail(f"input {path.name} changed size or is too large")
        return json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"input {path.name} is not valid JSON") from exc


def inventory_bytes(evidence: object, authority: object) -> bytes:
    inventory = build_inventory(evidence, authority)
    return (
        json.dumps(inventory, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _write_new_output(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify read-only Distribution storage inventory evidence"
    )
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="create this deterministic inventory file; stdout when omitted",
    )
    args = parser.parse_args(argv)
    try:
        payload = inventory_bytes(
            load_bounded_json(args.evidence), load_bounded_json(args.authority)
        )
        if args.output is None:
            sys.stdout.buffer.write(payload)
        else:
            _write_new_output(args.output, payload)
    except (InvalidInventoryEvidence, OSError) as exc:
        print(f"inventory verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
