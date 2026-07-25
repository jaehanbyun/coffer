from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Iterator, Mapping


MODULE_PATH = Path(__file__).with_name("state_machine.py")
SPEC = importlib.util.spec_from_file_location(
    "coffer_load_soak_state_machine_runtime",
    MODULE_PATH,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("load/soak state machine is unavailable")
state_machine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = state_machine
SPEC.loader.exec_module(state_machine)

FIXTURE_SCHEMA = "coffer.load-soak-fixture/v1"
OUTPUT_SCHEMA = "coffer.load-soak-lifecycle-output/v1"
FAILURE_SCHEMA = "coffer.load-soak-lifecycle-failure/v1"
DEFAULT_TOPOLOGY = Path(__file__).with_name("topology.json")
INVOCATION = re.compile(r"^01j[a-z0-9]{23}$")
FAILURES = frozenset(
    {
        "contract-refused",
        "fixture-refused",
        "local-state-unavailable",
        "lock-unavailable",
    }
)


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FAILURES:
            raise ValueError("failure category is not fixed")
        super().__init__(category)
        self.category = category


def _hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _validate_directory(path: Path) -> None:
    try:
        details = path.lstat()
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    if (
        not stat.S_ISDIR(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o700
        or details.st_uid != os.getuid()
    ):
        raise CommandError("local-state-unavailable")


def _validate_file(path: Path, *, required: bool = False) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        if required:
            raise CommandError("local-state-unavailable") from None
        return
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.getuid()
        or details.st_nlink != 1
    ):
        raise CommandError("local-state-unavailable")


def _atomic_json(path: Path, value: object) -> None:
    state_machine.validate_retained_evidence(value)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_directory(path.parent)
    _validate_file(path)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise CommandError("local-state-unavailable") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _validate_file(path, required=True)


class Store:
    def __init__(
        self,
        repo_root: Path,
        topology: Mapping[str, Any],
        invocation_id: str,
    ):
        if INVOCATION.fullmatch(invocation_id) is None:
            raise CommandError("contract-refused")
        root = repo_root.resolve()
        work_root = (root / topology["work_root"]).resolve()
        if work_root != root / "work" / "load-soak":
            raise CommandError("local-state-unavailable")
        self.work_root = work_root
        self.root = work_root / invocation_id
        self.state_path = self.root / "state.json"
        self.lock_path = self.root / "lock"

    def prepare(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_directory(self.root)

    @contextmanager
    def lock(self, *, create: bool) -> Iterator[None]:
        if create:
            self.prepare()
        else:
            _validate_directory(self.root)
        descriptor: int | None = None
        try:
            flags = os.O_RDWR | (os.O_CREAT if create else 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.lock_path, flags, 0o600)
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o600
                or details.st_uid != os.getuid()
                or details.st_nlink != 1
            ):
                raise CommandError("local-state-unavailable")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            if descriptor is not None:
                os.close(descriptor)
            raise CommandError("lock-unavailable") from error
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            raise CommandError("local-state-unavailable") from error
        try:
            yield
        finally:
            assert descriptor is not None
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def load(self, topology: Mapping[str, Any]) -> dict[str, Any]:
        _validate_file(self.state_path, required=True)
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            state_machine._validate_state(topology, state)
        except (OSError, json.JSONDecodeError) as error:
            raise CommandError("local-state-unavailable") from error
        except state_machine.LoadSoakError as error:
            raise CommandError("contract-refused") from error
        return state

    def write(
        self,
        topology: Mapping[str, Any],
        state: Mapping[str, Any],
    ) -> None:
        try:
            state_machine._validate_state(topology, state)
            _atomic_json(self.state_path, state)
        except state_machine.LoadSoakError as error:
            raise CommandError("contract-refused") from error

    def cleanup(self) -> None:
        if not self.root.exists():
            return
        with self.lock(create=False):
            _validate_file(self.state_path)
            _validate_file(self.lock_path, required=True)
            self.state_path.unlink(missing_ok=True)
            self.lock_path.unlink(missing_ok=True)
            try:
                self.root.rmdir()
                self.work_root.rmdir()
                self.work_root.parent.rmdir()
            except OSError:
                pass


def load_fixture(
    path: Path,
    topology: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CommandError("fixture-refused") from error
    if not isinstance(fixture, Mapping) or set(fixture) != {
        "dependency_mode",
        "failure_outcomes",
        "residue",
        "schema",
        "seed",
    }:
        raise CommandError("fixture-refused")
    if (
        fixture["schema"] != FIXTURE_SCHEMA
        or fixture["dependency_mode"] != "synthetic-qualified"
        or not isinstance(fixture["seed"], str)
        or not 8 <= len(fixture["seed"]) <= 64
        or fixture["failure_outcomes"]
        != {name: "refused" for name in topology["failure_cases"]}
        or fixture["residue"]
        != {name: 0 for name in topology["residue_keys"]}
    ):
        raise CommandError("fixture-refused")
    try:
        state_machine.validate_retained_evidence(fixture)
    except state_machine.LoadSoakError as error:
        raise CommandError("fixture-refused") from error
    return dict(fixture)


def _latency(topology: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "p95": limits["p95"] / 2,
            "p99": limits["p99"] / 2,
        }
        for name, limits in topology["latency_milliseconds"].items()
    }


def _profile(
    topology: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    profile = topology["profiles"][name]
    return {
        "availability": {
            item: 100.0
            for item in topology["availability_percent"]
        },
        "burst_clients": profile["burst_clients"],
        "digest_mismatches": 0,
        "duration_seconds": profile["duration_seconds"],
        "latency_milliseconds": _latency(topology),
        "operation_counts": {
            operation: 1
            for operation in topology["operations"]
        },
        "profile": name,
        "steady_clients": profile["steady_clients"],
        "transfer_bytes": profile["transfer_ceiling_bytes"] // 2,
        "unexpected_errors": 0,
    }


def fixture_evidence(
    phase: str,
    topology: Mapping[str, Any],
    state: Mapping[str, Any],
    fixture: Mapping[str, Any],
    unrelated_signature: str,
) -> dict[str, Any]:
    seed = fixture["seed"]
    if phase == "preflighted":
        return {
            "invocation_hash": _hash(f"{seed}:invocation"),
            "ownership_hash": _hash(f"{seed}:ownership"),
            "target_class": topology["target_class"],
            "transfer_ceiling_bytes": topology["profiles"]["soak"][
                "transfer_ceiling_bytes"
            ],
            "unrelated_before_hash": unrelated_signature,
            "writer_scope_exact": True,
        }
    if phase == "dependencies-qualified":
        return {
            "architectures": {
                item: True
                for item in topology["required_architectures"]
            },
            "ceph_evidence_hash": _hash(f"{seed}:ceph"),
            "distribution_evidence_hash": _hash(f"{seed}:distribution"),
            "status": "qualified",
        }
    if phase == "topology-verified":
        return {
            "configuration_hash": _hash(f"{seed}:configuration"),
            "edge_only_ingress": True,
            "observability_direct": True,
            "private_tls": True,
            "replicas": topology["replicas"],
            "shared_rgw": True,
            "shared_sql": True,
        }
    if phase == "clients-qualified":
        return {
            "ca_verified": True,
            "clients": {item: True for item in topology["clients"]},
            "insecure_mode": False,
            "versions_hash": _hash(f"{seed}:clients"),
        }
    if phase == "seed-loaded":
        return {
            "active_uploads": 0,
            "inventory_before_hash": _hash(f"{seed}:inventory"),
            "logical_bytes": 1024,
            "payload_retained": False,
            "quota_limit_bytes": 10240,
            "seed_hash": _hash(seed),
        }
    if phase == "smoke-complete":
        return _profile(topology, "smoke")
    if phase == "ramp-complete":
        return {
            "accepted_clients": 32,
            "levels": [
                {
                    "clients": clients,
                    "completed": clients <= 32,
                    "maximum_limit_usage_percent": 60 if clients <= 32 else 80,
                    "minimum_headroom_percent": 40 if clients <= 32 else 20,
                    "queue_growth": clients > 32,
                }
                for clients in topology["ramp_clients"]
            ],
            "steady_backlog_growth": False,
        }
    if phase == "baseline-complete":
        return _profile(topology, "qualification")
    if phase == "faults-complete":
        return {
            name: {
                "data_integrity": True,
                "injected": True,
                "recovered": True,
                "recovery_seconds": limits["recovery_seconds"] / 2,
                "security_boundary": True,
                "unexpected_errors": 0,
                "window_seconds": limits["window_seconds"] / 2,
            }
            for name, limits in topology["faults"].items()
        }
    if phase == "soak-complete":
        return _profile(topology, "soak")
    if phase == "data-verified":
        return {
            "active_uploads": 0,
            "claims_exact": True,
            "digest_checks": 1000,
            "digest_checks_passed": 1000,
            "galera_nodes_converged": topology["replicas"]["galera"],
            "inventory_after_hash": state["facts"]["inventory_before_hash"],
            "multipart_uploads": 0,
            "quota_invariant": True,
        }
    if phase == "metrics-verified":
        return {
            "alerts": topology["required_alerts"],
            "direct_targets": {
                item: topology["replicas"][item]
                for item in ("api", "edge", "reconcile", "registry")
            },
            "recording_rules": topology["required_recording_rules"],
            "restart_resets": True,
            "schema_mismatches": 0,
            "secret_leaks": 0,
            "stale_series": True,
        }
    if phase == "torn-down":
        return {
            "audit_complete": True,
            "residue": fixture["residue"],
            "unrelated_after_hash": unrelated_signature,
        }
    raise CommandError("contract-refused")


def public_output(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "adapter": "fixture",
        "complete": state["complete"],
        "facts_hash": _hash(json.dumps(state["facts"], sort_keys=True)),
        "history_entries": len(state["history"]),
        "history_hash": _hash(json.dumps(state["history"], sort_keys=True)),
        "phase": state["phase"],
        "schema": OUTPUT_SCHEMA,
        "synthetic": True,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("action", choices=("run", "status", "cleanup"))
    result.add_argument("--invocation-id", required=True)
    result.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY)
    result.add_argument("--adapter")
    result.add_argument("--fixture", type=Path)
    result.add_argument("--unrelated-signature", required=True)
    return result


def run(
    arguments: list[str] | None = None,
    *,
    repo_root: Path | None = None,
) -> int:
    args = parser().parse_args(arguments)
    try:
        topology = state_machine.load_topology(args.topology)
        unrelated = args.unrelated_signature
        if state_machine.HASH.fullmatch(unrelated) is None:
            raise CommandError("contract-refused")
        store = Store(
            repo_root or Path(__file__).resolve().parents[2],
            topology,
            args.invocation_id,
        )
        if args.action == "cleanup":
            if args.adapter is not None or args.fixture is not None:
                raise CommandError("contract-refused")
            store.cleanup()
            output = {
                "adapter": "fixture",
                "complete": True,
                "phase": "cleaned",
                "residue": 0,
                "schema": OUTPUT_SCHEMA,
                "synthetic": True,
            }
        elif args.action == "status":
            if args.adapter is not None or args.fixture is not None:
                raise CommandError("contract-refused")
            with store.lock(create=False):
                output = public_output(store.load(topology))
        else:
            if args.adapter != "fixture" or args.fixture is None:
                raise CommandError("fixture-refused")
            fixture = load_fixture(args.fixture, topology)
            with store.lock(create=True):
                if store.state_path.exists():
                    state = store.load(topology)
                else:
                    state = state_machine.new_state(topology)
                while not state["complete"]:
                    phase = topology["phases"][len(state["history"])]
                    state = state_machine.advance(
                        topology,
                        state,
                        phase,
                        fixture_evidence(
                            phase,
                            topology,
                            state,
                            fixture,
                            unrelated,
                        ),
                    )
                    store.write(topology, state)
                output = public_output(state)
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        return 0
    except (
        CommandError,
        state_machine.LoadSoakError,
    ) as error:
        category = (
            error.category
            if isinstance(error, CommandError)
            else "contract-refused"
        )
        failure = {
            "action": args.action,
            "category": category,
            "schema": FAILURE_SCHEMA,
        }
        print(json.dumps(failure, separators=(",", ":"), sort_keys=True), file=sys.stderr)
        return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
