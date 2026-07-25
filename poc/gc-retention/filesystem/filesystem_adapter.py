from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import uuid
from typing import Any


MODULE_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIRECTORY))

from collector_output import (  # noqa: E402
    Candidate,
    OUTPUT_SCHEMA,
    normalize_dry_run,
)


AUTHORIZATION_SCHEMA = "coffer.gc-filesystem-authorization/v1"
CONSUMPTION_SCHEMA = "coffer.gc-filesystem-consumption/v1"
FIXTURE_SCHEMA = "coffer.gc-filesystem-fixture/v1"
RECLAIM_SCHEMA = "coffer.gc-filesystem-reclaim/v1"
TREE_SCHEMA = "coffer.gc-filesystem-tree/v1"
VERSION = "v3.1.1"
REVISION = "9a8d98b679740cd514aa7e7d84d23d442a5ef54c"


class FilesystemAdapterError(RuntimeError):
    pass


def _hash(value: object) -> str:
    encoded = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate_private_file(path: Path) -> None:
    details = path.lstat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.getuid()
    ):
        raise FilesystemAdapterError("fixture input ownership is unsafe")


def _read_private_json(path: Path) -> dict[str, Any]:
    _validate_private_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FilesystemAdapterError("fixture input is invalid") from error
    if not isinstance(value, dict):
        raise FilesystemAdapterError("fixture input is invalid")
    return value


def _write_private_json(path: Path, value: object) -> None:
    if path.exists() or path.is_symlink():
        raise FilesystemAdapterError("fixture output already exists")
    parent = path.parent
    parent_details = parent.lstat()
    if (
        not stat.S_ISDIR(parent_details.st_mode)
        or parent_details.st_uid != os.getuid()
        or stat.S_IMODE(parent_details.st_mode) != 0o700
    ):
        raise FilesystemAdapterError("fixture output directory is unsafe")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _replace_private_json(path: Path, value: object) -> None:
    _validate_private_file(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _load_topology(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FilesystemAdapterError("collector topology is invalid")
    return value


def _fixture_candidates(
    fixture: dict[str, Any],
) -> frozenset[Candidate]:
    if fixture.get("schema") != FIXTURE_SCHEMA:
        raise FilesystemAdapterError("fixture schema changed")
    candidates = fixture.get("candidates")
    retained = fixture.get("retained_digests")
    if not isinstance(candidates, list) or not isinstance(retained, list):
        raise FilesystemAdapterError("fixture candidate boundary is invalid")
    try:
        parsed = frozenset(
            Candidate(
                kind=item["kind"],
                repository=item["repository"],
                digest=item["digest"],
            )
            for item in candidates
        )
    except (KeyError, TypeError) as error:
        raise FilesystemAdapterError(
            "fixture candidate boundary is invalid"
        ) from error
    if len(parsed) != len(candidates):
        raise FilesystemAdapterError("fixture candidates are duplicated")
    return parsed


def normalize_command(args: argparse.Namespace) -> None:
    fixture = _read_private_json(args.fixture)
    _validate_private_file(args.raw_output)
    raw_output = args.raw_output.read_text(encoding="utf-8")
    normalized = normalize_dry_run(
        raw_output,
        topology=_load_topology(args.topology),
        distribution_version=VERSION,
        distribution_revision=REVISION,
        expected_candidates=_fixture_candidates(fixture),
        retained_digests=frozenset(fixture["retained_digests"]),
    )
    _write_private_json(args.output, normalized.public)


def authorize_command(args: argparse.Namespace) -> None:
    topology = _load_topology(args.topology)
    first = _read_private_json(args.first)
    second = _read_private_json(args.second)
    if first.get("schema") != OUTPUT_SCHEMA or first != second:
        raise FilesystemAdapterError("dry-run evidence changed")
    maximum_ttl = topology.get("collector", {}).get(
        "authorization_ttl_seconds"
    )
    if (
        isinstance(maximum_ttl, bool)
        or not isinstance(maximum_ttl, int)
        or args.ttl != maximum_ttl
    ):
        raise FilesystemAdapterError("authorization lifetime changed")
    now = int(time.time())
    binding = {
        "candidate_set_hash": first.get("candidate_set_hash"),
        "distribution_revision": first.get("distribution_revision"),
        "distribution_version": first.get("distribution_version"),
        "normalized_output_hash": first.get("normalized_output_hash"),
    }
    if (
        binding["distribution_version"] != VERSION
        or binding["distribution_revision"] != REVISION
        or not all(
            isinstance(binding[key], str) and binding[key]
            for key in binding
        )
    ):
        raise FilesystemAdapterError("authorization binding is invalid")
    _write_private_json(
        args.output,
        {
            "authorization_id": str(uuid.uuid4()),
            "binding": binding,
            "binding_hash": _hash(binding),
            "consumed": False,
            "created_at": now,
            "expires_at": now + args.ttl,
            "schema": AUTHORIZATION_SCHEMA,
        },
    )


def consume_command(args: argparse.Namespace) -> None:
    authorization = _read_private_json(args.authorization)
    if (
        authorization.get("schema") != AUTHORIZATION_SCHEMA
        or authorization.get("consumed") is not False
        or authorization.get("binding_hash")
        != _hash(authorization.get("binding"))
    ):
        raise FilesystemAdapterError("collection authorization is invalid")
    now = int(time.time())
    expires_at = authorization.get("expires_at")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or now >= expires_at
    ):
        raise FilesystemAdapterError("collection authorization expired")
    authorization["consumed"] = True
    authorization["consumed_at"] = now
    _replace_private_json(args.authorization, authorization)
    _write_private_json(
        args.output,
        {
            "authorization_id_hash": _hash(
                authorization["authorization_id"]
            ),
            "binding_hash": authorization["binding_hash"],
            "consumed_at": now,
            "schema": CONSUMPTION_SCHEMA,
        },
    )


def summarize_command(args: argparse.Namespace) -> None:
    root_details = args.root.lstat()
    if (
        not stat.S_ISDIR(root_details.st_mode)
        or args.root.is_symlink()
    ):
        raise FilesystemAdapterError("storage root is unsafe")
    identities: list[tuple[str, str, int]] = []
    logical_bytes = 0
    for path in sorted(args.root.rglob("*")):
        details = path.lstat()
        if stat.S_ISDIR(details.st_mode):
            continue
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
        ):
            raise FilesystemAdapterError("storage tree entry is unsafe")
        relative = path.relative_to(args.root).as_posix()
        content_hash = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                content_hash.update(chunk)
        identities.append(
            (relative, f"sha256:{content_hash.hexdigest()}", details.st_size)
        )
        logical_bytes += details.st_size
    if not identities:
        raise FilesystemAdapterError("storage tree is empty")
    _write_private_json(
        args.output,
        {
            "file_count": len(identities),
            "logical_bytes": logical_bytes,
            "schema": TREE_SCHEMA,
            "tree_hash": _hash(identities),
        },
    )


def verify_reclaim_command(args: argparse.Namespace) -> None:
    before = _read_private_json(args.before)
    after = _read_private_json(args.after)
    restored = _read_private_json(args.restored)
    if any(
        value.get("schema") != TREE_SCHEMA
        for value in (before, after, restored)
    ):
        raise FilesystemAdapterError("storage summary schema changed")
    if before != restored:
        raise FilesystemAdapterError("isolated restore does not match snapshot")
    before_files = before.get("file_count")
    after_files = after.get("file_count")
    before_bytes = before.get("logical_bytes")
    after_bytes = after.get("logical_bytes")
    if (
        isinstance(before_files, bool)
        or not isinstance(before_files, int)
        or isinstance(after_files, bool)
        or not isinstance(after_files, int)
        or isinstance(before_bytes, bool)
        or not isinstance(before_bytes, int)
        or isinstance(after_bytes, bool)
        or not isinstance(after_bytes, int)
        or after_files >= before_files
        or after_bytes >= before_bytes
        or after.get("tree_hash") == before.get("tree_hash")
    ):
        raise FilesystemAdapterError("collection did not reclaim fixture data")
    _write_private_json(
        args.output,
        {
            "logical_bytes_after": after_bytes,
            "logical_bytes_before": before_bytes,
            "logical_bytes_reclaimed": before_bytes - after_bytes,
            "physical_backend": "filesystem",
            "schema": RECLAIM_SCHEMA,
            "tree_files_after": after_files,
            "tree_files_before": before_files,
            "tree_files_reclaimed": before_files - after_files,
        },
    )


def parser() -> argparse.ArgumentParser:
    command_parser = argparse.ArgumentParser()
    subparsers = command_parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize")
    normalize.add_argument("--fixture", type=Path, required=True)
    normalize.add_argument("--raw-output", type=Path, required=True)
    normalize.add_argument("--topology", type=Path, required=True)
    normalize.add_argument("--output", type=Path, required=True)
    normalize.set_defaults(handler=normalize_command)

    authorize = subparsers.add_parser("authorize")
    authorize.add_argument("--first", type=Path, required=True)
    authorize.add_argument("--second", type=Path, required=True)
    authorize.add_argument("--topology", type=Path, required=True)
    authorize.add_argument("--ttl", type=int, required=True)
    authorize.add_argument("--output", type=Path, required=True)
    authorize.set_defaults(handler=authorize_command)

    consume = subparsers.add_parser("consume")
    consume.add_argument("--authorization", type=Path, required=True)
    consume.add_argument("--output", type=Path, required=True)
    consume.set_defaults(handler=consume_command)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--root", type=Path, required=True)
    summarize.add_argument("--output", type=Path, required=True)
    summarize.set_defaults(handler=summarize_command)

    verify_reclaim = subparsers.add_parser("verify-reclaim")
    verify_reclaim.add_argument("--before", type=Path, required=True)
    verify_reclaim.add_argument("--after", type=Path, required=True)
    verify_reclaim.add_argument("--restored", type=Path, required=True)
    verify_reclaim.add_argument("--output", type=Path, required=True)
    verify_reclaim.set_defaults(handler=verify_reclaim_command)
    return command_parser


def main() -> None:
    args = parser().parse_args()
    try:
        args.handler(args)
    except (
        FilesystemAdapterError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"gc filesystem adapter failed: {error}") from None


if __name__ == "__main__":
    main()
