from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Iterator, Mapping, Sequence


MODULE_PATH = Path(__file__).with_name("state_machine.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_data_protection_state_machine_runtime",
    MODULE_PATH,
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("data-protection state machine is unavailable")
state_machine = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = state_machine
MODULE_SPEC.loader.exec_module(state_machine)

FIXTURE_SCHEMA = "coffer.data-protection-fixture/v1"
FAILURE_SCHEMA = "coffer.data-protection-failure/v1"
DEFAULT_TOPOLOGY = Path(__file__).with_name("topology.json")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
MUTATING_ACTIONS = frozenset(
    {
        "create-source",
        "populate-fixture",
        "exclude-writers",
        "verify-backups",
        "verify-inventory",
        "import-baseline",
        "verify-live",
        "cutover",
        "verify-cutover",
        "verify-rollback",
        "verify-restore",
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
FIXTURE_EVIDENCE_KEYS = frozenset(
    {
        "fixture",
        "writer_fence",
        "sql_backup",
        "rgw_backup",
        "inventory",
        "baseline_import",
        "live_comparison",
        "admission_cutover",
        "cutover_verification",
        "rollback",
        "restore",
    }
)


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURE_CATEGORIES:
            raise ValueError("failure category is not fixed")
        super().__init__(category)
        self.category = category


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
        topology: state_machine.Topology,
        invocation_id: str,
    ):
        root = repo_root.resolve()
        expected = (root / topology.work_root).resolve()
        if expected != root / "work" / "data-protection":
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

    def load(self, topology: state_machine.Topology) -> dict[str, object]:
        _validate_existing_file(self.state_path, required=True)
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError("local-state-unavailable") from error
        try:
            state_machine.validate_state(topology, value)
        except state_machine.DataProtectionError as error:
            raise CommandError("contract-refused") from error
        return dict(value)

    def write(
        self,
        topology: state_machine.Topology,
        state: Mapping[str, object],
    ) -> None:
        try:
            state_machine.validate_state(topology, state)
        except state_machine.DataProtectionError as error:
            raise CommandError("contract-refused") from error
        _atomic_json(self.state_path, state)


def load_fixture(
    path: Path,
    topology: state_machine.Topology,
    target_signature: str,
    unrelated_signature: str,
) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CommandError("fixture-refused") from error
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "target_signature",
        "unrelated_signature",
        "seed",
        "evidence",
        "failure_outcomes",
        "residue_counts",
    }:
        raise CommandError("fixture-refused")
    if (
        value.get("schema") != FIXTURE_SCHEMA
        or value.get("target_signature") != target_signature
        or value.get("unrelated_signature") != unrelated_signature
    ):
        raise CommandError("fixture-refused")
    seed = value.get("seed")
    if (
        not isinstance(seed, str)
        or len(seed) < 8
        or len(seed) > 64
        or not seed.replace("-", "").isalnum()
    ):
        raise CommandError("fixture-refused")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping) or set(evidence) != FIXTURE_EVIDENCE_KEYS:
        raise CommandError("fixture-refused")
    failures = value.get("failure_outcomes")
    if (
        not isinstance(failures, Mapping)
        or set(failures) != set(topology.failure_cases)
        or any(outcome != "passed" for outcome in failures.values())
    ):
        raise CommandError("fixture-refused")
    residue = value.get("residue_counts")
    if (
        not isinstance(residue, Mapping)
        or set(residue) != set(topology.residue_keys)
        or any(
            not isinstance(count, int)
            or isinstance(count, bool)
            or count != 0
            for count in residue.values()
        )
    ):
        raise CommandError("fixture-refused")
    try:
        state_machine.validate_retained_payload(value)
    except state_machine.DataProtectionError as error:
        raise CommandError("fixture-refused") from error
    return dict(value)


def _fixture_resources(
    topology: state_machine.Topology,
    invocation_id: str,
    seed: str,
) -> dict[str, dict[str, object]]:
    resources: dict[str, dict[str, object]] = {}
    specs = state_machine.expected_resource_specs(topology, invocation_id)
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
    unrelated_signature: str | None,
) -> None:
    if (
        target_signature is not None
        and state.get("target_signature") != target_signature
    ):
        raise CommandError("contract-refused")
    if (
        unrelated_signature is not None
        and state.get("unrelated_signature") != unrelated_signature
    ):
        raise CommandError("contract-refused")


def _phase_evidence(
    fixture: Mapping[str, object],
    key: str,
) -> Mapping[str, object]:
    evidence = fixture["evidence"]
    assert isinstance(evidence, Mapping)
    selected = evidence[key]
    if not isinstance(selected, Mapping):
        raise CommandError("fixture-refused")
    return selected


def _run_action(
    args: argparse.Namespace,
    topology: state_machine.Topology,
    store: LifecycleStore,
    fixture: Mapping[str, object] | None,
) -> dict[str, object] | list[dict[str, str]]:
    action = args.action
    if action == "preflight":
        if (
            args.target_signature is None
            or args.unrelated_signature is None
        ):
            raise CommandError("contract-refused")
        if store.exists():
            existing = store.load(topology)
            expected = state_machine.create_preflight_state(
                topology,
                args.invocation_id,
                args.target_signature,
                args.unrelated_signature,
            )
            for field in (
                "schema",
                "topology_digest",
                "invocation_id",
                "target_signature",
                "unrelated_signature",
            ):
                if existing.get(field) != expected.get(field):
                    raise CommandError("contract-refused")
            return state_machine.redacted_evidence(topology, existing)
        state = state_machine.create_preflight_state(
            topology,
            args.invocation_id,
            args.target_signature,
            args.unrelated_signature,
        )
        store.write(topology, state)
        return state_machine.redacted_evidence(topology, state)

    state = _load_required_state(store, topology)
    _assert_target(
        state,
        args.target_signature,
        args.unrelated_signature,
    )
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
        if action == "create-source":
            state = state_machine.register_source_resources(
                topology,
                state,
                _fixture_resources(
                    topology,
                    str(state["invocation_id"]),
                    str(fixture["seed"]),
                ),
            )
        elif action == "populate-fixture":
            state = state_machine.mark_fixture_populated(
                topology,
                state,
                _phase_evidence(fixture, "fixture"),
            )
        elif action == "exclude-writers":
            state = state_machine.mark_writers_excluded(
                topology,
                state,
                _phase_evidence(fixture, "writer_fence"),
            )
        elif action == "verify-backups":
            state = state_machine.mark_backups_verified(
                topology,
                state,
                _phase_evidence(fixture, "sql_backup"),
                _phase_evidence(fixture, "rgw_backup"),
            )
        elif action == "verify-inventory":
            state = state_machine.mark_inventory_verified(
                topology,
                state,
                _phase_evidence(fixture, "inventory"),
            )
        elif action == "import-baseline":
            state = state_machine.mark_baseline_imported(
                topology,
                state,
                _phase_evidence(fixture, "baseline_import"),
            )
        elif action == "verify-live":
            state = state_machine.mark_live_comparison_verified(
                topology,
                state,
                _phase_evidence(fixture, "live_comparison"),
            )
        elif action == "cutover":
            cutover = dict(_phase_evidence(fixture, "admission_cutover"))
            cutover["marker_sha256"] = state_machine.cutover_marker_digest(
                topology,
                state,
                str(cutover["routing_sha256"]),
                str(cutover["database_sha256"]),
            )
            state = state_machine.mark_admission_cutover(
                topology,
                state,
                cutover,
            )
        elif action == "verify-cutover":
            state = state_machine.mark_cutover_verified(
                topology,
                state,
                _phase_evidence(fixture, "cutover_verification"),
            )
        elif action == "verify-rollback":
            state = state_machine.mark_rollback_verified(
                topology,
                state,
                _phase_evidence(fixture, "rollback"),
            )
        elif action == "verify-restore":
            state = state_machine.mark_restore_verified(
                topology,
                state,
                _phase_evidence(fixture, "restore"),
            )
        elif action == "verify-failures":
            failures = fixture["failure_outcomes"]
            assert isinstance(failures, Mapping)
            state = state_machine.mark_failures_verified(
                topology,
                state,
                failures,
            )
        elif action == "teardown":
            residue = fixture["residue_counts"]
            assert isinstance(residue, Mapping)
            state = state_machine.finalize_teardown(
                topology,
                state,
                state_machine.cleanup_plan(topology, state),
                residue,
                str(fixture["unrelated_signature"]),
            )
        else:
            raise CommandError("contract-refused")
    except (KeyError, state_machine.DataProtectionError) as error:
        raise CommandError("contract-refused") from error

    store.write(topology, state)
    return state_machine.redacted_evidence(topology, state)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Coffer fixture-only data-protection lifecycle model",
    )
    result.add_argument(
        "action",
        choices=(
            "preflight",
            "status",
            "create-source",
            "populate-fixture",
            "exclude-writers",
            "verify-backups",
            "verify-inventory",
            "import-baseline",
            "verify-live",
            "cutover",
            "verify-cutover",
            "verify-rollback",
            "verify-restore",
            "verify-failures",
            "cleanup-plan",
            "teardown",
        ),
    )
    result.add_argument("--invocation-id", required=True)
    result.add_argument("--target-signature")
    result.add_argument("--unrelated-signature")
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
            if (
                args.adapter != "fixture"
                or args.fixture is None
                or args.target_signature is None
                or args.unrelated_signature is None
            ):
                raise CommandError("fixture-refused")
            fixture = load_fixture(
                args.fixture,
                topology,
                args.target_signature,
                args.unrelated_signature,
            )
        elif args.adapter is not None or args.fixture is not None:
            raise CommandError("fixture-refused")

        with store.lock(create=args.action == "preflight"):
            result = _run_action(args, topology, store, fixture)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except state_machine.DataProtectionError:
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
