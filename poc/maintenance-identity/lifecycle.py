from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Iterator, Mapping, Sequence

import state_machine


FIXTURE_SCHEMA = "coffer.maintenance-identity-fixture/v1"
FAILURE_SCHEMA = "coffer.maintenance-identity-failure/v1"
DEFAULT_TOPOLOGY = Path(__file__).with_name("topology.json")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
MUTATING_ACTIONS = frozenset(
    {
        "create",
        "verify",
        "rotate",
        "revoke-old",
        "verify-failures",
        "teardown",
    }
)
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


def _atomic_json(path: Path, value: object) -> None:
    state_machine.validate_retained_payload(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_directory(path.parent)
    _validate_existing_file(path)
    payload = (
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
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


class LifecycleStore:
    def __init__(
        self,
        repo_root: Path,
        topology: state_machine.Topology,
        invocation_id: str,
    ):
        root = repo_root.resolve()
        expected = (root / topology.work_root).resolve()
        if expected != root / "work" / "maintenance-identity":
            raise CommandError("local-state-unavailable")
        if state_machine.INVOCATION_PATTERN.fullmatch(invocation_id) is None:
            raise CommandError("contract-refused")
        self.root = expected / invocation_id
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "lock"

    def prepare(self) -> None:
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
        except OSError as error:
            raise CommandError("local-state-unavailable") from error
        _validate_directory(self.root)

    @contextmanager
    def lock(self, *, create: bool) -> Iterator[None]:
        if create:
            self.prepare()
        else:
            _validate_directory(self.root)
            _validate_existing_file(self.lock_path, required=True)
        try:
            flags = os.O_RDWR
            if create:
                flags |= os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(
                self.lock_path,
                flags,
                0o600,
            )
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise CommandError("local-state-unavailable")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CommandError("lock-unavailable") from error
        except CommandError:
            raise
        except OSError as error:
            raise CommandError("local-state-unavailable") from error
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self, topology: state_machine.Topology) -> dict[str, object]:
        _validate_existing_file(self.state_path, required=True)
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError("local-state-unavailable") from error
        try:
            state_machine.validate_state(topology, value)
        except state_machine.LifecycleError as error:
            raise CommandError("contract-refused") from error
        return dict(value)

    def write(
        self,
        topology: state_machine.Topology,
        state: Mapping[str, object],
    ) -> None:
        try:
            state_machine.validate_state(topology, state)
        except state_machine.LifecycleError as error:
            raise CommandError("contract-refused") from error
        _atomic_json(self.state_path, state)


def load_fixture(
    path: Path,
    target_signature: str,
) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CommandError("fixture-refused") from error
    if not isinstance(value, Mapping) or value.get("schema") != FIXTURE_SCHEMA:
        raise CommandError("fixture-refused")
    if value.get("target_signature") != target_signature:
        raise CommandError("fixture-refused")
    allowed_fields = {
        "schema",
        "target_signature",
        "seed",
        "maintenance_role_owned",
        "rotation",
        "residue_counts",
    }
    if set(value) != allowed_fields:
        raise CommandError("fixture-refused")
    seed = value.get("seed")
    if (
        not isinstance(seed, str)
        or len(seed) < 8
        or len(seed) > 64
        or not seed.replace("-", "").isalnum()
    ):
        raise CommandError("fixture-refused")
    if not isinstance(value.get("maintenance_role_owned"), bool):
        raise CommandError("fixture-refused")
    rotation = value.get("rotation")
    if not isinstance(rotation, Mapping) or set(rotation) != {
        "elapsed_seconds",
        "keystone_cache_seconds",
        "registry_token_seconds",
    }:
        raise CommandError("fixture-refused")
    if any(
        not isinstance(item, int)
        or isinstance(item, bool)
        or item < 0
        or item > 7200
        for item in rotation.values()
    ):
        raise CommandError("fixture-refused")
    residue = value.get("residue_counts")
    if (
        not isinstance(residue, Mapping)
        or not residue
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item != 0
            for item in residue.values()
        )
    ):
        raise CommandError("fixture-refused")
    try:
        state_machine.validate_retained_payload(value)
    except state_machine.LifecycleError as error:
        raise CommandError("fixture-refused") from error
    return dict(value)


def _fixture_resources(
    specs: Mapping[str, Mapping[str, object]],
    seed: str,
) -> dict[str, dict[str, object]]:
    resources: dict[str, dict[str, object]] = {}
    for key, spec in specs.items():
        digest = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()
        resources[key] = {
            "id": f"fixture-{digest[:48]}",
            **dict(spec),
        }
    return resources


def _load_required_state(
    store: LifecycleStore,
    topology: state_machine.Topology,
) -> dict[str, object]:
    if not store.exists():
        raise CommandError("local-state-unavailable")
    return store.load(topology)


def _assert_target(
    state: Mapping[str, object],
    target_signature: str | None,
) -> None:
    if target_signature is not None and state.get("target_signature") != target_signature:
        raise CommandError("contract-refused")


def _run_action(
    args: argparse.Namespace,
    topology: state_machine.Topology,
    store: LifecycleStore,
    fixture: Mapping[str, object] | None,
) -> dict[str, object] | list[dict[str, str]]:
    action = args.action
    if action == "preflight":
        if args.target_signature is None:
            raise CommandError("contract-refused")
        selected = tuple(args.workload or ())
        if store.exists():
            existing = store.load(topology)
            expected = state_machine.create_preflight_state(
                topology,
                args.invocation_id,
                args.target_signature,
                selected,
            )
            comparable_fields = (
                "schema",
                "topology_digest",
                "invocation_id",
                "target_signature",
                "selected_workloads",
            )
            if any(
                existing.get(field) != expected.get(field)
                for field in comparable_fields
            ):
                raise CommandError("contract-refused")
            return state_machine.redacted_evidence(topology, existing)
        state = state_machine.create_preflight_state(
            topology,
            args.invocation_id,
            args.target_signature,
            selected,
        )
        store.write(topology, state)
        return state_machine.redacted_evidence(topology, state)

    state = _load_required_state(store, topology)
    _assert_target(state, args.target_signature)
    if action == "status":
        return state_machine.redacted_evidence(topology, state)
    if action == "cleanup-plan":
        return [
            {
                "kind": item["kind"],
                "name": item["name"],
                "id_sha256": hashlib.sha256(
                    item["id"].encode("utf-8")
                ).hexdigest(),
            }
            for item in state_machine.cleanup_plan(topology, state)
        ]
    if fixture is None:
        raise CommandError("fixture-refused")

    try:
        if action == "create":
            specs = state_machine.expected_resource_specs(
                topology,
                state,
                1,
                maintenance_role_owned=bool(
                    fixture["maintenance_role_owned"]
                ),
            )
            state = state_machine.register_generation(
                topology,
                state,
                1,
                _fixture_resources(specs, str(fixture["seed"])),
            )
        elif action == "verify":
            phase = state["phase"]
            generation = (
                1
                if phase == "generation1_created"
                else 2
                if phase == "generation2_created"
                else 0
            )
            if generation == 0:
                raise state_machine.LifecycleError(
                    "no generation awaits verification"
                )
            state = state_machine.verify_generation(
                topology,
                state,
                generation,
            )
        elif action == "rotate":
            specs = state_machine.expected_resource_specs(topology, state, 2)
            state = state_machine.register_generation(
                topology,
                state,
                2,
                _fixture_resources(specs, str(fixture["seed"])),
            )
        elif action == "revoke-old":
            rotation = fixture["rotation"]
            assert isinstance(rotation, Mapping)
            state = state_machine.mark_rotation_drained(
                topology,
                state,
                elapsed_seconds=int(rotation["elapsed_seconds"]),
                keystone_cache_seconds=int(rotation["keystone_cache_seconds"]),
                registry_token_seconds=int(rotation["registry_token_seconds"]),
            )
            state = state_machine.revoke_old_generation(topology, state)
        elif action == "verify-failures":
            state = state_machine.mark_failure_matrix_verified(topology, state)
        elif action == "teardown":
            residue = fixture["residue_counts"]
            assert isinstance(residue, Mapping)
            state = state_machine.finalize_teardown(
                topology,
                state,
                state_machine.cleanup_plan(topology, state),
                residue,
            )
        else:
            raise CommandError("contract-refused")
    except state_machine.LifecycleError as error:
        raise CommandError("contract-refused") from error

    store.write(topology, state)
    return state_machine.redacted_evidence(topology, state)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Coffer disposable maintenance identity lifecycle model",
    )
    result.add_argument(
        "action",
        choices=(
            "preflight",
            "status",
            "create",
            "verify",
            "rotate",
            "revoke-old",
            "verify-failures",
            "cleanup-plan",
            "teardown",
        ),
    )
    result.add_argument("--invocation-id", required=True)
    result.add_argument("--target-signature")
    result.add_argument("--workload", action="append")
    result.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY)
    result.add_argument("--adapter", choices=("fixture",))
    result.add_argument("--fixture", type=Path)
    return result


def run(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> int:
    args = parser().parse_args(argv)
    try:
        topology = state_machine.load_topology(args.topology)
        store = LifecycleStore(repo_root, topology, args.invocation_id)
        fixture: Mapping[str, object] | None = None
        if args.action in MUTATING_ACTIONS:
            if args.adapter != "fixture" or args.fixture is None:
                raise CommandError("fixture-refused")
            if args.target_signature is None:
                raise CommandError("contract-refused")
            fixture = load_fixture(args.fixture, args.target_signature)
        elif args.adapter is not None or args.fixture is not None:
            raise CommandError("fixture-refused")

        with store.lock(create=args.action == "preflight"):
            result = _run_action(args, topology, store, fixture)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except state_machine.LifecycleError:
        failure = CommandError("contract-refused")
    except CommandError as error:
        failure = error
    payload = {
        "schema": FAILURE_SCHEMA,
        "action": args.action,
        "category": failure.category,
    }
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr,
    )
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
