from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Mapping, Sequence


LOAD_MODULE_PATH = Path(__file__).with_name("state_machine.py")
LOAD_MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_telemetry_state_machine",
    LOAD_MODULE_PATH,
)
if LOAD_MODULE_SPEC is None or LOAD_MODULE_SPEC.loader is None:
    raise RuntimeError("load state contract is unavailable")
load_contract = importlib.util.module_from_spec(LOAD_MODULE_SPEC)
sys.modules[LOAD_MODULE_SPEC.name] = load_contract
LOAD_MODULE_SPEC.loader.exec_module(load_contract)

OBSERVABILITY_MODULE_PATH = (
    Path(__file__).parents[1] / "observability" / "contract.py"
)
OBSERVABILITY_MODULE_SPEC = importlib.util.spec_from_file_location(
    "coffer_load_telemetry_observability_contract",
    OBSERVABILITY_MODULE_PATH,
)
if (
    OBSERVABILITY_MODULE_SPEC is None
    or OBSERVABILITY_MODULE_SPEC.loader is None
):
    raise RuntimeError("observability contract is unavailable")
observability_contract = importlib.util.module_from_spec(
    OBSERVABILITY_MODULE_SPEC
)
sys.modules[OBSERVABILITY_MODULE_SPEC.name] = observability_contract
OBSERVABILITY_MODULE_SPEC.loader.exec_module(observability_contract)

BUNDLE_SCHEMA = "coffer.load-telemetry-bundle/v1"
VERIFIED_SCHEMA = "coffer.load-telemetry-verified/v1"
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
PHASES = ("before", "during", "after")
DIRECT_COMPONENTS = ("api", "edge", "reconcile", "registry")
HOST_ROLES = ("controller", "storage")
FIXED_FAILURES = frozenset(
    {
        "contract-refused",
        "invalid-arguments",
        "local-file-unavailable",
        "output-unavailable",
    }
)


class TelemetryError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("telemetry failure category is not fixed")
        super().__init__(category)
        self.category = category


def _exact(
    value: object,
    keys: set[str],
    category: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise TelemetryError(f"{category} boundary changed")
    return value


def _array(value: object, length: int | None, category: str) -> list[Any]:
    if not isinstance(value, list) or (
        length is not None and len(value) != length
    ):
        raise TelemetryError(f"{category} boundary changed")
    return value


def _integer(
    value: object,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    category: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or (maximum is not None and value > maximum)
    ):
        raise TelemetryError(f"{category} is invalid")
    return value


def _number(
    value: object,
    *,
    minimum: float = 0,
    maximum: float | None = None,
    category: str,
) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or (maximum is not None and float(value) > maximum)
    ):
        raise TelemetryError(f"{category} is invalid")
    return float(value)


def _hash(value: object) -> str:
    payload = json.dumps(
        value,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_direct_targets(
    value: object,
    *,
    observed_at: float,
    phase: str,
    load_topology: Mapping[str, Any],
    previous: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, tuple[float, float]], int]:
    targets = _exact(
        value,
        set(DIRECT_COMPONENTS),
        "direct telemetry target",
    )
    current: dict[str, tuple[float, float]] = {}
    reset_count = 0
    for component in DIRECT_COMPONENTS:
        required = load_topology["replicas"][component]
        samples = _array(
            targets[component],
            required,
            f"{component} target sample",
        )
        seen: set[str] = set()
        up_count = 0
        for sample_value in samples:
            sample = _exact(
                sample_value,
                {
                    "counter",
                    "instance",
                    "process_start_seconds",
                    "up",
                },
                "target sample",
            )
            instance = sample["instance"]
            if (
                not isinstance(instance, str)
                or observability_contract.HOST_PATTERN.fullmatch(instance)
                is None
                or instance in seen
            ):
                raise TelemetryError("target instance is invalid")
            seen.add(instance)
            up = _integer(
                sample["up"],
                minimum=0,
                maximum=1,
                category="target up",
            )
            up_count += up
            process_start = _number(
                sample["process_start_seconds"],
                maximum=observed_at,
                category="process start",
            )
            counter = _number(sample["counter"], category="target counter")
            identity = f"{component}:{instance}"
            prior = previous.get(identity)
            if prior is not None:
                old_start, old_counter = prior
                if process_start < old_start:
                    raise TelemetryError("process start regressed")
                if process_start == old_start and counter < old_counter:
                    raise TelemetryError("counter reset lacks process restart")
                if process_start > old_start:
                    reset_count += 1
            current[identity] = (process_start, counter)
        minimum_up = required if phase != "during" else required - 1
        if up_count < minimum_up:
            raise TelemetryError("direct target availability is below gate")
    return current, reset_count


def _validate_prometheus(
    value: object,
    *,
    observed_at: float,
    phase: str,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
    previous: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, tuple[float, float]], int]:
    prometheus = _exact(
        value,
        {
            "alerts_loaded",
            "direct_targets",
            "firing_alerts",
            "recording_rules_loaded",
            "schema_mismatches",
            "scrape_interval_seconds",
            "secret_leaks",
            "stale_series",
        },
        "Prometheus snapshot",
    )
    expected_rules = load_topology["required_recording_rules"]
    expected_alerts = load_topology["required_alerts"]
    if (
        prometheus["recording_rules_loaded"] != expected_rules
        or prometheus["alerts_loaded"] != expected_alerts
        or prometheus["scrape_interval_seconds"]
        != observability_topology.raw["scrape_interval_seconds"]
        or prometheus["schema_mismatches"] != 0
        or prometheus["secret_leaks"] != 0
    ):
        raise TelemetryError("Prometheus contract is incomplete")
    firing = _array(
        prometheus["firing_alerts"],
        None,
        "firing alerts",
    )
    if (
        any(not isinstance(item, str) for item in firing)
        or len(set(firing)) != len(firing)
        or any(item not in expected_alerts for item in firing)
        or (phase == "during" and not firing)
        or (phase != "during" and firing)
    ):
        raise TelemetryError("alert transition is invalid")
    stale = _integer(
        prometheus["stale_series"],
        category="stale series",
    )
    if (phase == "during" and stale < 1) or (
        phase != "during" and stale != 0
    ):
        raise TelemetryError("stale-series transition is invalid")
    return _validate_direct_targets(
        prometheus["direct_targets"],
        observed_at=observed_at,
        phase=phase,
        load_topology=load_topology,
        previous=previous,
    )


def _validate_galera(
    value: object,
    *,
    phase: str,
    load_topology: Mapping[str, Any],
) -> None:
    galera = _exact(
        value,
        {
            "max_transaction_attempts",
            "nodes_primary",
            "nodes_ready",
            "nodes_synced",
            "nodes_total",
            "unexpected_errors",
        },
        "Galera snapshot",
    )
    total = load_topology["replicas"]["galera"]
    minimum = total if phase != "during" else total - 1
    primary = _integer(
        galera["nodes_primary"],
        maximum=total,
        category="primary nodes",
    )
    ready = _integer(
        galera["nodes_ready"],
        maximum=total,
        category="ready nodes",
    )
    synced = _integer(
        galera["nodes_synced"],
        maximum=total,
        category="synced nodes",
    )
    if (
        galera["nodes_total"] != total
        or primary < minimum
        or ready < minimum
        or synced < minimum
        or _integer(
            galera["max_transaction_attempts"],
            minimum=1,
            maximum=load_topology["resource_gates"][
                "maximum_transaction_attempts"
            ],
            category="transaction attempts",
        )
        < 1
        or galera["unexpected_errors"] != 0
    ):
        raise TelemetryError("Galera gate failed")


def _validate_rgw(
    value: object,
    *,
    phase: str,
    load_topology: Mapping[str, Any],
) -> None:
    rgw = _exact(
        value,
        {
            "daemons_total",
            "daemons_up",
            "ingress_total",
            "ingress_up",
            "kms_errors",
            "multipart_uploads",
            "unexpected_errors",
        },
        "RGW snapshot",
    )
    daemons = load_topology["replicas"]["rgw"]
    ingress = load_topology["replicas"]["rgw-ingress"]
    minimum_daemons = daemons if phase != "during" else daemons - 1
    minimum_ingress = ingress if phase != "during" else ingress - 1
    daemons_up = _integer(
        rgw["daemons_up"],
        maximum=daemons,
        category="RGW daemons",
    )
    ingress_up = _integer(
        rgw["ingress_up"],
        maximum=ingress,
        category="RGW ingress",
    )
    multipart_uploads = _integer(
        rgw["multipart_uploads"],
        category="multipart uploads",
    )
    if (
        rgw["daemons_total"] != daemons
        or daemons_up < minimum_daemons
        or rgw["ingress_total"] != ingress
        or ingress_up < minimum_ingress
        or rgw["kms_errors"] != 0
        or rgw["unexpected_errors"] != 0
        or (phase == "after" and multipart_uploads != 0)
    ):
        raise TelemetryError("RGW gate failed")


def _validate_quota(
    value: object,
    *,
    load_topology: Mapping[str, Any],
) -> None:
    quota = _exact(
        value,
        {
            "headroom_percent",
            "invariant",
            "limit_usage_percent",
            "max_transaction_attempts",
            "stale_claims",
            "unexpected_errors",
        },
        "quota snapshot",
    )
    usage = _number(
        quota["limit_usage_percent"],
        maximum=load_topology["resource_gates"][
            "maximum_limit_usage_percent"
        ],
        category="quota limit usage",
    )
    headroom = _number(
        quota["headroom_percent"],
        minimum=load_topology["resource_gates"][
            "minimum_headroom_percent"
        ],
        maximum=100,
        category="quota headroom",
    )
    if (
        abs(usage + headroom - 100) > 0.001
        or quota["invariant"] is not True
        or quota["stale_claims"] != 0
        or quota["unexpected_errors"] != 0
    ):
        raise TelemetryError("quota invariant failed")
    _integer(
        quota["max_transaction_attempts"],
        minimum=1,
        maximum=load_topology["resource_gates"][
            "maximum_transaction_attempts"
        ],
        category="quota transaction attempts",
    )


def _validate_reconciliation(
    value: object,
    *,
    phase: str,
    load_topology: Mapping[str, Any],
) -> None:
    reconciliation = _exact(
        value,
        {
            "claims_exact",
            "fencing_violations",
            "fresh",
            "last_success_age_seconds",
            "stale_claims",
            "workers_total",
            "workers_up",
        },
        "reconciliation snapshot",
    )
    workers = load_topology["replicas"]["reconcile"]
    minimum = workers if phase != "during" else workers - 1
    workers_up = _integer(
        reconciliation["workers_up"],
        maximum=workers,
        category="reconciliation workers",
    )
    if (
        reconciliation["workers_total"] != workers
        or workers_up < minimum
        or reconciliation["claims_exact"] is not True
        or reconciliation["fresh"] is not True
        or reconciliation["fencing_violations"] != 0
        or reconciliation["stale_claims"] != 0
    ):
        raise TelemetryError("reconciliation gate failed")
    _number(
        reconciliation["last_success_age_seconds"],
        maximum=180,
        category="reconciliation freshness",
    )


def _validate_haproxy(
    value: object,
    *,
    phase: str,
    load_topology: Mapping[str, Any],
) -> None:
    haproxy = _exact(
        value,
        {"backends", "unexpected_errors"},
        "HAProxy snapshot",
    )
    backends = _exact(
        haproxy["backends"],
        {"api", "edge", "registry"},
        "HAProxy backends",
    )
    for component, backend_value in backends.items():
        backend = _exact(
            backend_value,
            {"healthy", "total"},
            "HAProxy backend",
        )
        total = load_topology["replicas"][component]
        minimum = total if phase != "during" else total - 1
        healthy = _integer(
            backend["healthy"],
            maximum=total,
            category="healthy backend",
        )
        if (
            backend["total"] != total
            or healthy < minimum
        ):
            raise TelemetryError("HAProxy backend gate failed")
    if haproxy["unexpected_errors"] != 0:
        raise TelemetryError("HAProxy gate failed")


def _validate_hosts(value: object) -> None:
    hosts = _array(value, 6, "host resources")
    counts = {role: 0 for role in HOST_ROLES}
    seen: set[str] = set()
    for item_value in hosts:
        item = _exact(
            item_value,
            {
                "clock_offset_milliseconds",
                "cpu_usage_percent",
                "disk_usage_percent",
                "file_descriptor_usage_percent",
                "instance",
                "memory_usage_percent",
                "oom_kills",
                "role",
            },
            "host resource",
        )
        instance = item["instance"]
        role = item["role"]
        if (
            role not in HOST_ROLES
            or not isinstance(instance, str)
            or observability_contract.HOST_PATTERN.fullmatch(instance) is None
            or instance in seen
        ):
            raise TelemetryError("host identity is invalid")
        seen.add(instance)
        counts[role] += 1
        for key in (
            "cpu_usage_percent",
            "disk_usage_percent",
            "file_descriptor_usage_percent",
            "memory_usage_percent",
        ):
            _number(
                item[key],
                maximum=70,
                category="host resource usage",
            )
        _number(
            abs(item["clock_offset_milliseconds"])
            if isinstance(item["clock_offset_milliseconds"], (int, float))
            and not isinstance(item["clock_offset_milliseconds"], bool)
            else item["clock_offset_milliseconds"],
            maximum=1000,
            category="host clock offset",
        )
        if item["oom_kills"] != 0:
            raise TelemetryError("host OOM gate failed")
    if counts != {"controller": 3, "storage": 3}:
        raise TelemetryError("host role topology changed")


def verify_document(
    document: object,
    *,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
) -> dict[str, Any]:
    checked = _exact(
        document,
        {
            "load_topology_sha256",
            "observability_topology_sha256",
            "schema",
            "snapshots",
            "source",
            "synthetic",
        },
        "telemetry bundle",
    )
    expected_load_hash = _hash(load_topology)
    if (
        checked["schema"] != BUNDLE_SCHEMA
        or checked["load_topology_sha256"] != expected_load_hash
        or checked["observability_topology_sha256"]
        != observability_topology.digest
        or checked["source"] != "fixture"
        or checked["synthetic"] is not True
    ):
        raise TelemetryError("telemetry binding changed")
    snapshots = _array(checked["snapshots"], len(PHASES), "telemetry snapshots")
    previous_observed = -1.0
    previous_targets: dict[str, tuple[float, float]] = {}
    reset_count = 0
    for expected_phase, snapshot_value in zip(PHASES, snapshots):
        snapshot = _exact(
            snapshot_value,
            {
                "galera",
                "haproxy",
                "hosts",
                "observed_at_seconds",
                "phase",
                "prometheus",
                "quota",
                "reconciliation",
                "rgw",
            },
            "telemetry snapshot",
        )
        observed_at = _number(
            snapshot["observed_at_seconds"],
            category="observation time",
        )
        if snapshot["phase"] != expected_phase or observed_at <= previous_observed:
            raise TelemetryError("telemetry window order changed")
        previous_observed = observed_at
        current_targets, resets = _validate_prometheus(
            snapshot["prometheus"],
            observed_at=observed_at,
            phase=expected_phase,
            load_topology=load_topology,
            observability_topology=observability_topology,
            previous=previous_targets,
        )
        previous_targets = current_targets
        reset_count += resets
        _validate_galera(
            snapshot["galera"],
            phase=expected_phase,
            load_topology=load_topology,
        )
        _validate_rgw(
            snapshot["rgw"],
            phase=expected_phase,
            load_topology=load_topology,
        )
        _validate_quota(snapshot["quota"], load_topology=load_topology)
        _validate_reconciliation(
            snapshot["reconciliation"],
            phase=expected_phase,
            load_topology=load_topology,
        )
        _validate_haproxy(
            snapshot["haproxy"],
            phase=expected_phase,
            load_topology=load_topology,
        )
        _validate_hosts(snapshot["hosts"])
    if reset_count < 1:
        raise TelemetryError("restart transition is missing")
    metrics_phase = {
        "alerts": list(load_topology["required_alerts"]),
        "direct_targets": {
            component: load_topology["replicas"][component]
            for component in DIRECT_COMPONENTS
        },
        "recording_rules": list(load_topology["required_recording_rules"]),
        "restart_resets": True,
        "schema_mismatches": 0,
        "secret_leaks": 0,
        "stale_series": True,
    }
    result = {
        "bundle_sha256": _hash(checked),
        "load_topology_sha256": expected_load_hash,
        "metrics_phase": metrics_phase,
        "observability_topology_sha256": observability_topology.digest,
        "restart_count": reset_count,
        "schema": VERIFIED_SCHEMA,
        "snapshot_count": len(snapshots),
        "source": checked["source"],
        "synthetic": checked["synthetic"],
    }
    load_contract.validate_retained_evidence(result)
    observability_contract.validate_retained_payload(result)
    return result


def _read_owner_file(path: Path) -> bytes:
    if not path.is_absolute():
        raise CommandError("local-file-unavailable")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.geteuid()
            or details.st_nlink != 1
            or details.st_size < 1
            or details.st_size > MAX_BUNDLE_BYTES
        ):
            raise CommandError("local-file-unavailable")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(MAX_BUNDLE_BYTES + 1)
    except CommandError:
        raise
    except OSError as error:
        raise CommandError("local-file-unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if len(payload) != details.st_size or b"\x00" in payload:
        raise CommandError("local-file-unavailable")
    return payload


def _validate_output(path: Path) -> None:
    if not path.is_absolute():
        raise CommandError("output-unavailable")
    try:
        parent = path.parent.lstat()
    except OSError as error:
        raise CommandError("output-unavailable") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or stat.S_IMODE(parent.st_mode) != 0o700
        or parent.st_uid != os.geteuid()
    ):
        raise CommandError("output-unavailable")
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise CommandError("output-unavailable") from error
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) != 0o600
        or details.st_uid != os.geteuid()
        or details.st_nlink != 1
    ):
        raise CommandError("output-unavailable")


def _atomic_output(path: Path, result: object) -> None:
    _validate_output(path)
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temporary = Path(name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(result, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise CommandError("output-unavailable") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _validate_output(path)


def verify_file(
    input_path: Path,
    output_path: Path,
    *,
    load_topology_path: Path,
    observability_topology_path: Path,
) -> None:
    resolved = [
        path.resolve(strict=False)
        for path in (
            input_path,
            output_path,
            load_topology_path,
            observability_topology_path,
        )
    ]
    if len(resolved) != len(set(resolved)):
        raise CommandError("contract-refused")
    _validate_output(output_path)
    payload = _read_owner_file(input_path)
    try:
        document = json.loads(payload)
        canonical = (
            json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        if payload != canonical:
            raise TelemetryError("telemetry bundle is not canonical")
        load_topology = load_contract.load_topology(load_topology_path)
        observability_topology = observability_contract.load_topology(
            observability_topology_path
        )
        result = verify_document(
            document,
            load_topology=load_topology,
            observability_topology=observability_topology,
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        load_contract.LoadSoakError,
        observability_contract.ContractError,
        TelemetryError,
    ) as error:
        raise CommandError("contract-refused") from error
    _atomic_output(output_path, result)


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 8
        or arguments[0] != "--input"
        or arguments[2] != "--output"
        or arguments[4] != "--load-topology"
        or arguments[6] != "--observability-topology"
        or any(not arguments[index] for index in (1, 3, 5, 7))
    ):
        print("load telemetry failed: invalid-arguments", file=stderr)
        return 2
    try:
        verify_file(
            Path(arguments[1]),
            Path(arguments[3]),
            load_topology_path=Path(arguments[5]),
            observability_topology_path=Path(arguments[7]),
        )
    except CommandError as error:
        print(f"load telemetry failed: {error.category}", file=stderr)
        return 1
    print("load telemetry verified", file=stdout)
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
