from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence


MODULE_PATH = Path(__file__).with_name("state_machine.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_gc_retention_state_machine_runtime",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("GC/retention state machine is unavailable")
state_machine = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = state_machine
MODULE_SPEC.loader.exec_module(state_machine)

FIXTURE_SCHEMA = "coffer.gc-retention-fixture/v1"
FAILURE_SCHEMA = "coffer.gc-retention-failure/v1"
DEFAULT_TOPOLOGY = Path(__file__).with_name("topology.json")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_ACTIONS = frozenset({"status", "cleanup-plan"})
MUTATING_ACTIONS = frozenset(state_machine.EXPECTED_ACTIONS[1:])
FIXED_FAILURE_CATEGORIES = frozenset(
    {
        "contract-refused",
        "fixture-refused",
        "lock-unavailable",
        "local-state-unavailable",
    }
)


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURE_CATEGORIES:
            raise ValueError("failure category is not fixed")
        super().__init__(category)
        self.category = category


def _hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink < 1
    ):
        raise CommandError("local-state-unavailable")


def _validate_existing_file(path: Path, *, required: bool = False) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise CommandError("local-state-unavailable") from None
        return
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise CommandError("local-state-unavailable")


def _atomic_json(path: Path, value: object) -> None:
    state_machine.validate_retained_payload(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_directory(path.parent)
    _validate_existing_file(path)
    payload = (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    _validate_existing_file(path, required=True)


class LifecycleStore:
    def __init__(
        self,
        repo_root: Path,
        topology: Mapping[str, Any],
        invocation_id: str,
    ):
        root = repo_root.resolve()
        expected = (root / topology["work_root"]).resolve()
        if expected != root / "work" / "gc-retention":
            raise CommandError("local-state-unavailable")
        if state_machine.INVOCATION_PATTERN.fullmatch(invocation_id) is None:
            raise CommandError("contract-refused")
        self.root = expected / invocation_id
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "lock"

    def prepare(self) -> None:
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise CommandError("local-state-unavailable") from error
        _validate_directory(self.root)

    @contextmanager
    def lock(self, *, create: bool) -> Iterator[None]:
        if create:
            self.prepare()
            _validate_existing_file(self.lock_path)
        else:
            _validate_directory(self.root)
            _validate_existing_file(self.lock_path, required=True)
        descriptor: int | None = None
        try:
            flags = os.O_RDWR
            if create:
                flags |= os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.lock_path, flags, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise CommandError("local-state-unavailable")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CommandError("lock-unavailable") from error
        except CommandError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            raise CommandError("local-state-unavailable") from error
        try:
            yield
        finally:
            assert descriptor is not None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self, topology: Mapping[str, Any]) -> dict[str, Any]:
        _validate_existing_file(self.state_path, required=True)
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            state_machine.validate_state(topology, value)
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError("local-state-unavailable") from error
        except state_machine.GCRetentionError as error:
            raise CommandError("contract-refused") from error
        return dict(value)

    def write(
        self,
        topology: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> None:
        try:
            state_machine.validate_state(topology, state)
        except state_machine.GCRetentionError as error:
            raise CommandError("contract-refused") from error
        _atomic_json(self.state_path, state)


def load_fixture(
    path: Path,
    topology: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CommandError("fixture-refused") from error
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "seed",
        "distribution_version",
        "distribution_revision",
        "failure_outcomes",
        "residue",
    }:
        raise CommandError("fixture-refused")
    if (
        value["schema"] != FIXTURE_SCHEMA
        or value["distribution_version"]
        != topology["collector"]["distribution_version"]
        or value["distribution_revision"]
        != topology["collector"]["distribution_revision"]
    ):
        raise CommandError("fixture-refused")
    seed = value["seed"]
    if (
        not isinstance(seed, str)
        or len(seed) < 8
        or len(seed) > 64
        or not seed.replace("-", "").isalnum()
    ):
        raise CommandError("fixture-refused")
    failures = value["failure_outcomes"]
    if (
        not isinstance(failures, Mapping)
        or set(failures) != set(state_machine.EXPECTED_FAILURE_CASES)
        or any(result != "refused" for result in failures.values())
    ):
        raise CommandError("fixture-refused")
    residue = value["residue"]
    if (
        not isinstance(residue, Mapping)
        or set(residue) != set(state_machine.EXPECTED_RESIDUE_KEYS)
        or any(
            isinstance(count, bool)
            or not isinstance(count, int)
            or count != 0
            for count in residue.values()
        )
    ):
        raise CommandError("fixture-refused")
    try:
        state_machine.validate_retained_payload(value)
    except state_machine.GCRetentionError as error:
        raise CommandError("fixture-refused") from error
    return dict(value)


def _resources(invocation_id: str) -> dict[str, str]:
    return {
        key: f"coffer-gc-{invocation_id}-{key}"
        for key in state_machine.EXPECTED_RESOURCE_KEYS
    }


def _next_time(state: Mapping[str, Any]) -> str:
    previous = _parse_time(state["history"][-1]["at"])
    return _format_time(previous + timedelta(minutes=1))


def _fixture_evidence(
    action: str,
    state: Mapping[str, Any],
    fixture: Mapping[str, Any],
    at: str,
) -> dict[str, Any]:
    seed = fixture["seed"]
    if action == "create-source":
        return {
            "owned_signature": _hash(f"{seed}:owned"),
            "unrelated_signature": state["unrelated_signature"],
        }
    if action == "populate-fixture":
        return {
            "fixture_hash": _hash(f"{seed}:fixture"),
            "retained_set_hash": _hash(f"{seed}:retained"),
            "deleted_set_hash": _hash(f"{seed}:deleted"),
            "counts": {
                "manifest": 6,
                "shared_blob": 1,
                "index": 1,
                "digest_only": 1,
                "referrer": 1,
            },
        }
    if action == "apply-logical-delete":
        return {
            "policy_hash": _hash(f"{seed}:delete-policy"),
            "deleted_set_hash": state["evidence"]["fixture-populated"][
                "deleted_set_hash"
            ],
            "deleted_manifest_count": 1,
        }
    if action == "exclude-writers":
        return {
            "fence_hash": _hash(f"{seed}:fence"),
            "fence_epoch": "fixture-writer-fence-0001",
            "replica_count": 2,
            "write_probe_count": 8,
            "active_upload_count": 0,
            "multipart_upload_count": 0,
            "background_mutator_count": 0,
            "all_read_only": True,
        }
    if action == "verify-backups":
        return {
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "sql_backup_hash": _hash(f"{seed}:sql-backup"),
            "rgw_backup_hash": _hash(f"{seed}:rgw-backup"),
            "isolated_restore_hash": _hash(f"{seed}:isolated-restore"),
            "object_version_count": 60,
            "delete_marker_count": 2,
            "multipart_upload_count": 0,
            "kms_verified": True,
        }
    if action == "verify-baseline":
        return {
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "inventory_hash": _hash(f"{seed}:inventory"),
            "sql_hash": _hash(f"{seed}:sql-state"),
            "retained_set_hash": state["evidence"]["fixture-populated"][
                "retained_set_hash"
            ],
            "expected_candidate_set_hash": state["evidence"][
                "fixture-populated"
            ]["deleted_set_hash"],
            "current_object_count": 50,
            "object_version_count": 60,
            "delete_marker_count": 2,
        }
    if action in {"verify-dry-run-one", "verify-dry-run-two"}:
        preflight = state["evidence"]["preflighted"]
        baseline = state["evidence"]["baseline-verified"]
        return {
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "image_digest": preflight["image_digest"],
            "distribution_revision": preflight["distribution_revision"],
            "config_hash": preflight["config_hash"],
            "backend_hash": preflight["backend_hash"],
            "baseline_hash": baseline["inventory_hash"],
            "candidate_set_hash": baseline["expected_candidate_set_hash"],
            "summary_hash": _hash(f"{seed}:dry-run-summary"),
            "eligible_blob_count": 3,
            "eligible_manifest_count": 1,
            "eligible_link_count": 2,
            "candidate_total": 6,
        }
    if action == "authorize-collection":
        issued = _parse_time(at)
        return {
            "authorization_id": "coffer-gc-authority-fixture-0001",
            "issued_at": at,
            "expires_at": _format_time(issued + timedelta(minutes=10)),
            "binding_hash": state_machine.collection_binding(state),
            "command_hash": _hash(f"{seed}:collector-command"),
            "candidate_set_hash": state["evidence"]["dry-run-two-verified"][
                "candidate_set_hash"
            ],
            "delete_untagged": False,
        }
    if action == "execute-collection":
        authority = state["collection_authority"]
        return {
            "authorization_id": authority["authorization_id"],
            "binding_hash": authority["binding_hash"],
            "candidate_set_hash": authority["candidate_set_hash"],
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "exit_code": 0,
            "collector_result_hash": _hash(f"{seed}:collector-result"),
        }
    if action == "verify-survivors":
        baseline = state["evidence"]["baseline-verified"]
        return {
            "fence_hash": state["evidence"]["writers-excluded"]["fence_hash"],
            "retained_set_hash": baseline["retained_set_hash"],
            "sql_hash": baseline["sql_hash"],
            "missing_survivor_count": 0,
            "deleted_readable_count": 0,
            "survivor_classes": {
                name: True
                for name in state_machine.EXPECTED_SURVIVOR_CLASSES
            },
        }
    if action == "verify-reclaim":
        return {
            "current_object_count_before": 50,
            "current_object_count_after": 45,
            "current_bytes_before": 1000,
            "current_bytes_after": 700,
            "object_version_count_before": 60,
            "object_version_count_after": 63,
            "delete_marker_count_before": 2,
            "delete_marker_count_after": 5,
            "logical_reclaimed_bytes": 300,
            "physical_reclaimed_bytes_observed": 0,
            "rgw_lifecycle_ran": False,
            "orphan_delete_ran": False,
        }
    if action == "verify-restore":
        return {
            "isolated": True,
            "kms_verified": True,
            "restore_inventory_hash": state["evidence"]["baseline-verified"][
                "inventory_hash"
            ],
            "restored_digest_count": 9,
            "mismatch_count": 0,
        }
    if action == "verify-failures":
        return {"outcomes": dict(fixture["failure_outcomes"])}
    if action == "teardown":
        return {
            "residue": dict(fixture["residue"]),
            "unrelated_signature": state["unrelated_signature"],
        }
    raise CommandError("contract-refused")


def _cleanup_plan(
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
) -> list[dict[str, str]]:
    kind_by_key = {
        "gc-job": "gc_job",
        "registry-replica-a": "registry",
        "registry-replica-b": "registry",
        "database-source": "database",
        "database-restore": "database",
        "bucket-source": "bucket",
        "bucket-backup": "bucket",
        "bucket-restore": "bucket",
        "config-tree": "config_tree",
        "evidence-file": "evidence_file",
        "network": "network",
    }
    output: list[dict[str, str]] = []
    for kind in topology["cleanup_order"]:
        for key in state_machine.EXPECTED_RESOURCE_KEYS:
            if kind_by_key[key] != kind:
                continue
            output.append(
                {
                    "kind": kind,
                    "name": key,
                    "id_sha256": hashlib.sha256(
                        state["resources"][key].encode("utf-8")
                    ).hexdigest(),
                }
            )
    if len(output) != len(state_machine.EXPECTED_RESOURCE_KEYS):
        raise CommandError("contract-refused")
    return output


def _emit(value: object, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(json.dumps(value, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fixture-only coordinated GC lifecycle"
    )
    parser.add_argument(
        "action",
        choices=(
            "status",
            "cleanup-plan",
            *state_machine.EXPECTED_ACTIONS,
        ),
    )
    parser.add_argument("--invocation-id", required=True)
    parser.add_argument("--unrelated-signature", required=True)
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY)
    parser.add_argument("--adapter", choices=("fixture",))
    parser.add_argument("--fixture", type=Path)
    return parser


def run(
    arguments: Sequence[str] | None = None,
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> int:
    parsed = _parser().parse_args(arguments)
    action = parsed.action
    try:
        topology = state_machine.load_topology(parsed.topology)
        store = LifecycleStore(repo_root, topology, parsed.invocation_id)
        if action in READ_ONLY_ACTIONS:
            if parsed.adapter is not None or parsed.fixture is not None:
                raise CommandError("fixture-refused")
            with store.lock(create=False):
                state = store.load(topology)
                output = (
                    state_machine.public_evidence(topology, state)
                    if action == "status"
                    else _cleanup_plan(topology, state)
                )
            _emit(output)
            return 0

        if action == "preflight":
            if parsed.adapter is not None or parsed.fixture is not None:
                raise CommandError("fixture-refused")
            with store.lock(create=True):
                if store.exists():
                    state = store.load(topology)
                    if (
                        state["invocation_id"] != parsed.invocation_id
                        or state["unrelated_signature"]
                        != parsed.unrelated_signature
                    ):
                        raise CommandError("contract-refused")
                    if state["phase"] != "preflighted":
                        raise CommandError("contract-refused")
                else:
                    created = datetime.now(timezone.utc)
                    state = state_machine.create_state(
                        topology,
                        invocation_id=parsed.invocation_id,
                        resources=_resources(parsed.invocation_id),
                        unrelated_signature=parsed.unrelated_signature,
                        created_at=_format_time(created),
                    )
                    evidence = {
                        "target_class": "disposable-fixture",
                        "distribution_version": topology["collector"][
                            "distribution_version"
                        ],
                        "distribution_revision": topology["collector"][
                            "distribution_revision"
                        ],
                        "image_digest": _hash(
                            f"{parsed.invocation_id}:fixture-image"
                        ),
                        "config_hash": _hash(
                            f"{parsed.invocation_id}:fixture-config"
                        ),
                        "backend_hash": _hash(
                            f"{parsed.invocation_id}:fixture-backend"
                        ),
                        "delete_untagged": False,
                        "candidate_limit": topology["collector"][
                            "candidate_limit"
                        ],
                    }
                    state = state_machine.advance(
                        topology,
                        state,
                        action="preflight",
                        evidence=evidence,
                        at=_format_time(created + timedelta(seconds=1)),
                    )
                    store.write(topology, state)
            _emit(state_machine.public_evidence(topology, state))
            return 0

        if action not in MUTATING_ACTIONS:
            raise CommandError("contract-refused")
        if parsed.adapter != "fixture" or parsed.fixture is None:
            raise CommandError("fixture-refused")
        fixture = load_fixture(parsed.fixture, topology)
        with store.lock(create=False):
            state = store.load(topology)
            target_phase = state_machine.PHASE_BY_ACTION[action]
            if state["phase"] == target_phase:
                _emit(state_machine.public_evidence(topology, state))
                return 0
            current_index = state_machine.EXPECTED_PHASES.index(state["phase"])
            if current_index + 1 >= len(state_machine.EXPECTED_ACTIONS):
                raise CommandError("contract-refused")
            expected_action = state_machine.EXPECTED_ACTIONS[
                current_index + 1
            ]
            if action != expected_action:
                raise CommandError("contract-refused")
            at = _next_time(state)
            evidence = _fixture_evidence(
                action,
                state,
                fixture,
                at,
            )
            state = state_machine.advance(
                topology,
                state,
                action=action,
                evidence=evidence,
                at=at,
            )
            store.write(topology, state)
        _emit(state_machine.public_evidence(topology, state))
        return 0
    except CommandError as error:
        _emit(
            {
                "schema": FAILURE_SCHEMA,
                "action": action,
                "category": error.category,
            },
            error=True,
        )
        return 2
    except (
        state_machine.GCRetentionError,
        OSError,
        json.JSONDecodeError,
    ):
        _emit(
            {
                "schema": FAILURE_SCHEMA,
                "action": action,
                "category": "contract-refused",
            },
            error=True,
        )
        return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
