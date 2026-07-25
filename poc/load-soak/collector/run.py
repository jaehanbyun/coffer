from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
from typing import Any, Iterator, Mapping, Protocol, Sequence
from urllib.parse import urlsplit


DIRECTORY = Path(__file__).resolve().parent
LOAD_DIRECTORY = DIRECTORY.parent


def _module(name: str, path: Path) -> Any:
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"{name} is unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


orchestrator = _module(
    "coffer_load_collector_orchestrator",
    LOAD_DIRECTORY / "orchestrator.py",
)
telemetry = _module(
    "coffer_load_collector_telemetry",
    LOAD_DIRECTORY / "telemetry.py",
)
native_surfaces = _module(
    "coffer_load_collector_native_surfaces",
    DIRECTORY / "native_surfaces.py",
)

INVOCATION_SCHEMA = "coffer.load-telemetry-collection/v1"
TARGET_SCHEMA = "coffer.load-telemetry-target/v1"
SURFACE_SCHEMA = "coffer.load-telemetry-surface/v1"
STATE_SCHEMA = "coffer.load-telemetry-collection-state/v1"
RESULT_SCHEMA = "coffer.load-telemetry-collection-result/v1"
TARGET_CLASS = "disposable-stage6-pilot"
ADAPTER = "stage6-telemetry-surface-adapter"
SURFACES = (
    "prometheus",
    "haproxy",
    "galera",
    "rgw",
    "quota",
    "reconciliation",
    "hosts",
)
PHASES = telemetry.PHASES
SHA256 = orchestrator.plan_contract.SHA256
PATH_PATTERN = re.compile(r"^/[A-Za-z0-9/_-]{1,127}$")
HOST_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")
MAX_SURFACE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 12
MAX_OBJECT_KEYS = 64
MAX_ARRAY_ITEMS = 256
MAX_STRING_LENGTH = 256
FIXED_FAILURES = frozenset(
    {
        "collection-unavailable",
        "contract-refused",
        "invalid-arguments",
        "local-file-unavailable",
        "lock-unavailable",
        "output-unavailable",
    }
)


class CollectorError(RuntimeError):
    pass


class CommandError(RuntimeError):
    def __init__(self, category: str):
        if category not in FIXED_FAILURES:
            raise ValueError("collector failure category is not fixed")
        super().__init__(category)
        self.category = category


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def wall_time(self) -> float: ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall_time(self) -> float:
        return time.time()


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    path: str


class SourceClient(Protocol):
    def fetch(
        self,
        endpoint: Endpoint,
        *,
        ca_file: Path,
        phase: str,
        surface: str,
        timeout_seconds: float,
    ) -> tuple[object, int]: ...


def _exact(value: object, keys: set[str], category: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CollectorError(f"{category} boundary changed")
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)[:-1]).hexdigest()


def _file_hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _source_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(
        (
            DIRECTORY / "native_surfaces.py",
            DIRECTORY / "run.py",
            LOAD_DIRECTORY / "telemetry.py",
        ),
        key=lambda item: str(item),
    ):
        payload = path.read_bytes()
        relative = str(path.relative_to(LOAD_DIRECTORY)).encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return "sha256:" + digest.hexdigest()


def _bounded_json(value: object, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise CollectorError("telemetry surface nesting exceeded")
    if isinstance(value, Mapping):
        if len(value) > MAX_OBJECT_KEYS:
            raise CollectorError("telemetry surface object exceeded")
        for key, nested in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > MAX_STRING_LENGTH
            ):
                raise CollectorError("telemetry surface key is invalid")
            _bounded_json(nested, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ARRAY_ITEMS:
            raise CollectorError("telemetry surface array exceeded")
        for nested in value:
            _bounded_json(nested, depth=depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH or "\x00" in value:
            raise CollectorError("telemetry surface string exceeded")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise CollectorError("telemetry surface value is invalid")


class HTTPSJSONSourceClient:
    def fetch(
        self,
        endpoint: Endpoint,
        *,
        ca_file: Path,
        phase: str,
        surface: str,
        timeout_seconds: float,
    ) -> tuple[object, int]:
        if timeout_seconds <= 0:
            raise CollectorError("telemetry collection deadline expired")
        try:
            context = ssl.create_default_context(cafile=str(ca_file))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            connection = http.client.HTTPSConnection(
                endpoint.host,
                endpoint.port,
                context=context,
                timeout=timeout_seconds,
            )
            connection.request(
                "GET",
                f"{endpoint.path}?phase={phase}",
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "coffer-load-telemetry/1",
                },
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "")
            content_encoding = response.getheader("Content-Encoding")
            length_value = response.getheader("Content-Length")
            if (
                response.status != 200
                or content_type.split(";", 1)[0].strip()
                != "application/json"
                or content_encoding not in (None, "identity")
            ):
                raise CollectorError("telemetry surface response failed")
            if length_value is not None:
                try:
                    content_length = int(length_value)
                except ValueError as error:
                    raise CollectorError(
                        "telemetry surface length is invalid"
                    ) from error
                if not 1 <= content_length <= MAX_SURFACE_BYTES:
                    raise CollectorError("telemetry surface response exceeded")
            payload = response.read(MAX_SURFACE_BYTES + 1)
            if not payload or len(payload) > MAX_SURFACE_BYTES:
                raise CollectorError("telemetry surface response exceeded")
        except CollectorError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException) as error:
            raise CollectorError("telemetry surface transport failed") from error
        finally:
            try:
                connection.close()
            except (NameError, OSError):
                pass
        try:
            value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise CollectorError("telemetry surface response is invalid") from error
        if payload != _canonical(value):
            raise CollectorError("telemetry surface response is not canonical")
        wrapper = _exact(
            value,
            {"payload", "phase", "schema", "surface"},
            "telemetry surface response",
        )
        if (
            wrapper["schema"] != SURFACE_SCHEMA
            or wrapper["phase"] != phase
            or wrapper["surface"] != surface
        ):
            raise CollectorError("telemetry surface binding changed")
        _bounded_json(wrapper["payload"])
        return wrapper["payload"], len(payload)


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    try:
        with orchestrator._lock(path):
            yield
    except orchestrator.CommandError as error:
        category = (
            error.category
            if error.category in FIXED_FAILURES
            else "collection-unavailable"
        )
        raise CommandError(category) from error


def _endpoints(
    value: object,
    *,
    topology_sha256: str,
) -> tuple[dict[str, Endpoint], str]:
    target = _exact(
        value,
        {
            "adapter",
            "adapter_contract_sha256",
            "schema",
            "surface_urls",
            "target_class",
            "target_sha256",
            "topology_sha256",
        },
        "telemetry target",
    )
    urls = _exact(
        target["surface_urls"],
        set(SURFACES),
        "telemetry surface URLs",
    )
    if (
        target["schema"] != TARGET_SCHEMA
        or target["adapter"] != ADAPTER
        or target["target_class"] != TARGET_CLASS
        or target["topology_sha256"] != topology_sha256
        or not isinstance(target["adapter_contract_sha256"], str)
        or SHA256.fullmatch(target["adapter_contract_sha256"]) is None
    ):
        raise CollectorError("telemetry target binding changed")
    endpoints: dict[str, Endpoint] = {}
    for surface in SURFACES:
        url = urls[surface]
        if not isinstance(url, str) or len(url) > 512:
            raise CollectorError("telemetry target URL is invalid")
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as error:
            raise CollectorError("telemetry target URL is invalid") from error
        host = parsed.hostname
        try:
            valid_ip = host is not None and bool(ipaddress.ip_address(host))
        except ValueError:
            valid_ip = False
        if (
            parsed.scheme != "https"
            or host is None
            or (
                not valid_ip
                and HOST_PATTERN.fullmatch(host) is None
            )
            or parsed.username is not None
            or parsed.password is not None
            or PATH_PATTERN.fullmatch(parsed.path) is None
            or parsed.query
            or parsed.fragment
            or port is None
            or not 1 <= port <= 65535
        ):
            raise CollectorError("telemetry target URL is invalid")
        endpoints[surface] = Endpoint(
            host=host,
            port=port,
            path=parsed.path,
        )
    if len(set(str(urls[surface]) for surface in SURFACES)) != len(SURFACES):
        raise CollectorError("telemetry surface URL is repeated")
    unsigned = {
        "adapter": target["adapter"],
        "adapter_contract_sha256": target["adapter_contract_sha256"],
        "surface_urls": dict(urls),
        "target_class": target["target_class"],
        "topology_sha256": target["topology_sha256"],
    }
    if target["target_sha256"] != _hash(unsigned):
        raise CollectorError("telemetry target hash changed")
    return (
        endpoints,
        str(target["target_sha256"]),
    )


def _binding(
    *,
    ca_sha256: str,
    collector_source_sha256: str,
    execution_source: str,
    plan_sha256: str,
    session_paths_sha256: str,
    target_sha256: str,
) -> str:
    return _hash(
        {
            "ca_sha256": ca_sha256,
            "collector_source_sha256": collector_source_sha256,
            "execution_source": execution_source,
            "plan_sha256": plan_sha256,
            "session_paths_sha256": session_paths_sha256,
            "target_sha256": target_sha256,
        }
    )


def _new_state(
    *,
    binding_sha256: str,
    execution_source: str,
    plan_sha256: str,
    target_sha256: str,
) -> dict[str, Any]:
    return {
        "binding_sha256": binding_sha256,
        "complete": False,
        "execution_source": execution_source,
        "history": [],
        "last_entry_sha256": binding_sha256,
        "plan_sha256": plan_sha256,
        "schema": STATE_SCHEMA,
        "snapshots": [],
        "synthetic": execution_source == "fixture",
        "target_sha256": target_sha256,
    }


def _validate_state(
    value: object,
    *,
    binding_sha256: str,
    execution_source: str,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
    plan_sha256: str,
    target_sha256: str,
) -> dict[str, Any]:
    state = dict(
        _exact(
            value,
            {
                "binding_sha256",
                "complete",
                "execution_source",
                "history",
                "last_entry_sha256",
                "plan_sha256",
                "schema",
                "snapshots",
                "synthetic",
                "target_sha256",
            },
            "telemetry collector state",
        )
    )
    snapshots = state["snapshots"]
    history = state["history"]
    if (
        state["schema"] != STATE_SCHEMA
        or state["binding_sha256"] != binding_sha256
        or state["execution_source"] != execution_source
        or state["synthetic"] != (execution_source == "fixture")
        or state["plan_sha256"] != plan_sha256
        or state["target_sha256"] != target_sha256
        or not isinstance(state["complete"], bool)
        or not isinstance(snapshots, list)
        or not isinstance(history, list)
        or len(history) != len(snapshots)
        or len(snapshots) > len(PHASES)
        or state["complete"] != (len(snapshots) == len(PHASES))
    ):
        raise CollectorError("telemetry collector state is invalid")
    previous_targets: dict[str, tuple[float, float]] = {}
    previous_observed = -1.0
    previous_sha256 = binding_sha256
    for sequence, (phase, snapshot, entry_value) in enumerate(
        zip(PHASES, snapshots, history),
        1,
    ):
        entry = _exact(
            entry_value,
            {
                "entry_sha256",
                "phase",
                "previous_sha256",
                "sequence",
                "snapshot_sha256",
            },
            "telemetry collector history",
        )
        unsigned = {
            key: entry[key] for key in entry if key != "entry_sha256"
        }
        if (
            entry["sequence"] != sequence
            or entry["phase"] != phase
            or entry["previous_sha256"] != previous_sha256
            or entry["snapshot_sha256"] != _hash(snapshot)
            or entry["entry_sha256"] != _hash(unsigned)
        ):
            raise CollectorError("telemetry collector history is invalid")
        previous_sha256 = str(entry["entry_sha256"])
        previous_targets, _, observed_at = telemetry.validate_snapshot(
            snapshot,
            expected_phase=phase,
            load_topology=load_topology,
            observability_topology=observability_topology,
            previous_targets=previous_targets,
        )
        if observed_at <= previous_observed:
            raise CollectorError("telemetry collector time regressed")
        previous_observed = observed_at
    if state["last_entry_sha256"] != previous_sha256:
        raise CollectorError("telemetry collector history is invalid")
    return state


def _bundle(
    state: Mapping[str, Any],
    *,
    load_topology: Mapping[str, Any],
    observability_topology: Any,
) -> dict[str, Any]:
    if state["complete"] is not True:
        raise CollectorError("telemetry collection is incomplete")
    bundle = {
        "load_topology_sha256": telemetry._hash(load_topology),
        "observability_topology_sha256": observability_topology.digest,
        "schema": telemetry.BUNDLE_SCHEMA,
        "snapshots": state["snapshots"],
        "source": (
            "fixture"
            if state["execution_source"] == "fixture"
            else "prometheus-export"
        ),
        "synthetic": state["synthetic"],
    }
    telemetry.verify_document(
        bundle,
        load_topology=load_topology,
        observability_topology=observability_topology,
        allow_live=state["synthetic"] is False,
    )
    return bundle


def _result(
    state: Mapping[str, Any],
    *,
    phase: str,
    bundle: Mapping[str, Any] | None,
    collector_source_sha256: str,
) -> dict[str, Any]:
    phase_index = PHASES.index(phase)
    snapshots = state["snapshots"][: phase_index + 1]
    if len(snapshots) != phase_index + 1:
        raise CollectorError("telemetry phase is incomplete")
    result = {
        "bundle_sha256": _hash(bundle) if bundle is not None else None,
        "collector_source_sha256": collector_source_sha256,
        "complete": phase == "after",
        "execution_source": state["execution_source"],
        "history_sha256": _hash(
            state["history"][: phase_index + 1]
        ),
        "phase": phase,
        "plan_sha256": state["plan_sha256"],
        "schema": RESULT_SCHEMA,
        "snapshot_count": len(snapshots),
        "snapshots_sha256": _hash(snapshots),
        "synthetic": state["synthetic"],
        "target_sha256": state["target_sha256"],
        "unexpected_errors": 0,
    }
    telemetry.load_contract.validate_retained_evidence(result)
    telemetry.observability_contract.validate_retained_payload(result)
    return result


def _collect_snapshot(
    endpoints: Mapping[str, Endpoint],
    *,
    ca_file: Path,
    client: SourceClient,
    clock: Clock,
    phase: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = clock.monotonic()
    collected: dict[str, object] = {}
    total_bytes = 0
    for surface in SURFACES:
        remaining = timeout_seconds - (clock.monotonic() - started)
        payload, payload_size = client.fetch(
            endpoints[surface],
            ca_file=ca_file,
            phase=phase,
            surface=surface,
            timeout_seconds=remaining,
        )
        total_bytes += payload_size
        if total_bytes > MAX_TOTAL_BYTES:
            raise CollectorError("telemetry collection size exceeded")
        collected[surface] = payload
    snapshot = {
        "galera": collected["galera"],
        "haproxy": collected["haproxy"],
        "hosts": collected["hosts"],
        "observed_at_seconds": clock.wall_time(),
        "phase": phase,
        "prometheus": collected["prometheus"],
        "quota": collected["quota"],
        "reconciliation": collected["reconciliation"],
        "rgw": collected["rgw"],
    }
    _bounded_json(snapshot)
    return snapshot


def execute_invocation(
    invocation_path: Path,
    *,
    client: SourceClient | None = None,
    clock: Clock | None = None,
) -> bool:
    try:
        invocation_payload = orchestrator._read_owner_file(invocation_path)
        if invocation_payload is None:
            raise CollectorError("telemetry invocation disappeared")
        invocation = _exact(
            orchestrator._canonical_document(
                invocation_payload,
                "telemetry invocation",
            ),
            {
                "bundle_file",
                "ca_file",
                "ca_sha256",
                "collector_source_sha256",
                "execution_source",
                "lock_file",
                "output_file",
                "plan_file",
                "plan_file_sha256",
                "schema",
                "state_file",
                "step",
                "target_class",
                "target_file",
                "target_file_sha256",
                "timeout_seconds",
            },
            "telemetry invocation",
        )
        if (
            invocation["schema"] != INVOCATION_SCHEMA
            or invocation["target_class"] != TARGET_CLASS
            or invocation["execution_source"] not in ("fixture", "pilot")
            or invocation["collector_source_sha256"] != _source_hash()
            or not isinstance(invocation["timeout_seconds"], int)
            or isinstance(invocation["timeout_seconds"], bool)
            or not 1 <= invocation["timeout_seconds"] <= 300
        ):
            raise CollectorError("telemetry invocation is invalid")
        for key in (
            "ca_sha256",
            "collector_source_sha256",
            "plan_file_sha256",
            "target_file_sha256",
        ):
            if (
                not isinstance(invocation[key], str)
                or SHA256.fullmatch(invocation[key]) is None
            ):
                raise CollectorError("telemetry invocation hash is invalid")
        step = _exact(
            invocation["step"],
            {"kind", "name", "order"},
            "telemetry step",
        )
        if (
            step["kind"] != "telemetry"
            or step["name"] not in PHASES
            or not isinstance(step["order"], int)
            or isinstance(step["order"], bool)
        ):
            raise CollectorError("telemetry step is invalid")
        path_keys = (
            "bundle_file",
            "ca_file",
            "lock_file",
            "output_file",
            "plan_file",
            "state_file",
            "target_file",
        )
        if any(
            not isinstance(invocation[key], str)
            or not Path(invocation[key]).is_absolute()
            for key in path_keys
        ):
            raise CollectorError("telemetry path is invalid")
        resolved = [
            invocation_path.resolve(strict=False),
            *[
                Path(invocation[key]).resolve(strict=False)
                for key in path_keys
            ],
        ]
        if len(resolved) != len(set(resolved)):
            raise CollectorError("telemetry paths overlap")
        ca_file = Path(invocation["ca_file"])
        ca_payload = orchestrator._read_owner_file(ca_file)
        if (
            ca_payload is None
            or _file_hash(ca_payload) != invocation["ca_sha256"]
        ):
            raise CollectorError("telemetry CA changed")
        plan_payload = orchestrator._read_owner_file(
            Path(invocation["plan_file"])
        )
        if (
            plan_payload is None
            or _file_hash(plan_payload) != invocation["plan_file_sha256"]
        ):
            raise CollectorError("telemetry plan changed")
        envelope = orchestrator._canonical_document(
            plan_payload,
            "telemetry plan",
        )
        load_topology = (
            orchestrator.plan_contract.state_machine.load_topology(
                LOAD_DIRECTORY / "topology.json"
            )
        )
        plan = orchestrator._validate_envelope(envelope, load_topology)
        schedule = orchestrator.build_schedule(plan)
        matches = [
            candidate
            for candidate in schedule
            if candidate.kind == "telemetry"
            and candidate.name == step["name"]
            and candidate.order == step["order"]
        ]
        if len(matches) != 1:
            raise CollectorError("telemetry step does not match plan")
        target_payload = orchestrator._read_owner_file(
            Path(invocation["target_file"])
        )
        if (
            target_payload is None
            or _file_hash(target_payload)
            != invocation["target_file_sha256"]
        ):
            raise CollectorError("telemetry target changed")
        target_value = orchestrator._canonical_document(
            target_payload,
            "telemetry target",
        )
        endpoints, target_sha256 = _endpoints(
            target_value,
            topology_sha256=plan["topology_sha256"],
        )
        observability_topology = (
            telemetry.observability_contract.load_topology(
                LOAD_DIRECTORY.parent / "observability" / "topology.json"
            )
        )
        session_paths_sha256 = _hash(
            {
                key: invocation[key]
                for key in ("bundle_file", "lock_file", "state_file")
            }
        )
        binding_sha256 = _binding(
            ca_sha256=invocation["ca_sha256"],
            collector_source_sha256=invocation[
                "collector_source_sha256"
            ],
            execution_source=invocation["execution_source"],
            plan_sha256=envelope["plan_sha256"],
            session_paths_sha256=session_paths_sha256,
            target_sha256=target_sha256,
        )
    except (
        CollectorError,
        OSError,
        orchestrator.CommandError,
        orchestrator.OrchestratorError,
        orchestrator.plan_contract.PlanError,
        orchestrator.plan_contract.state_machine.LoadSoakError,
        telemetry.observability_contract.ContractError,
    ) as error:
        raise CommandError("contract-refused") from error

    state_path = Path(invocation["state_file"])
    output_path = Path(invocation["output_file"])
    bundle_path = Path(invocation["bundle_file"])
    lock_path = Path(invocation["lock_file"])
    try:
        orchestrator._validate_owner_path(state_path)
        orchestrator._validate_owner_path(output_path, output=True)
        orchestrator._validate_owner_path(bundle_path, output=True)
    except orchestrator.CommandError as error:
        category = (
            error.category
            if error.category in FIXED_FAILURES
            else "output-unavailable"
        )
        raise CommandError(category) from error
    chosen_clock = clock or RealClock()
    chosen_client = client or HTTPSJSONSourceClient()

    with _lock(lock_path):
        state_payload = orchestrator._read_owner_file(
            state_path,
            required=False,
        )
        try:
            state = (
                _new_state(
                    binding_sha256=binding_sha256,
                    execution_source=invocation["execution_source"],
                    plan_sha256=envelope["plan_sha256"],
                    target_sha256=target_sha256,
                )
                if state_payload is None
                else _validate_state(
                    orchestrator._canonical_document(
                        state_payload,
                        "telemetry collector state",
                    ),
                    binding_sha256=binding_sha256,
                    execution_source=invocation["execution_source"],
                    load_topology=load_topology,
                    observability_topology=observability_topology,
                    plan_sha256=envelope["plan_sha256"],
                    target_sha256=target_sha256,
                )
            )
        except (
            CollectorError,
            telemetry.TelemetryError,
            telemetry.observability_contract.ContractError,
        ) as error:
            raise CommandError("contract-refused") from error

        phase = str(step["name"])
        phase_index = PHASES.index(phase)
        if len(state["snapshots"]) < phase_index:
            raise CommandError("contract-refused")
        if len(state["snapshots"]) == phase_index:
            try:
                snapshot = _collect_snapshot(
                    endpoints,
                    ca_file=ca_file,
                    client=chosen_client,
                    clock=chosen_clock,
                    phase=phase,
                    timeout_seconds=invocation["timeout_seconds"],
                )
                previous_targets: dict[str, tuple[float, float]] = {}
                previous_observed = -1.0
                for previous_phase, previous in zip(
                    PHASES,
                    state["snapshots"],
                ):
                    previous_targets, _, previous_observed = (
                        telemetry.validate_snapshot(
                            previous,
                            expected_phase=previous_phase,
                            load_topology=load_topology,
                            observability_topology=observability_topology,
                            previous_targets=previous_targets,
                        )
                    )
                _, _, observed_at = telemetry.validate_snapshot(
                    snapshot,
                    expected_phase=phase,
                    load_topology=load_topology,
                    observability_topology=observability_topology,
                    previous_targets=previous_targets,
                )
                if observed_at <= previous_observed:
                    raise CollectorError("telemetry collector time regressed")
                state["snapshots"].append(snapshot)
                unsigned = {
                    "phase": phase,
                    "previous_sha256": state["last_entry_sha256"],
                    "sequence": len(state["snapshots"]),
                    "snapshot_sha256": _hash(snapshot),
                }
                entry = {**unsigned, "entry_sha256": _hash(unsigned)}
                state["history"].append(entry)
                state["last_entry_sha256"] = entry["entry_sha256"]
                state["complete"] = len(state["snapshots"]) == len(PHASES)
                state = _validate_state(
                    state,
                    binding_sha256=binding_sha256,
                    execution_source=invocation["execution_source"],
                    load_topology=load_topology,
                    observability_topology=observability_topology,
                    plan_sha256=envelope["plan_sha256"],
                    target_sha256=target_sha256,
                )
                orchestrator._atomic_json(state_path, state)
            except (
                CollectorError,
                OSError,
                telemetry.TelemetryError,
                telemetry.observability_contract.ContractError,
            ) as error:
                raise CommandError("collection-unavailable") from error

        complete_bundle: Mapping[str, Any] | None = None
        if state["complete"]:
            try:
                complete_bundle = _bundle(
                    state,
                    load_topology=load_topology,
                    observability_topology=observability_topology,
                )
                orchestrator._atomic_json(
                    bundle_path,
                    complete_bundle,
                    output=True,
                )
            except (
                CollectorError,
                telemetry.TelemetryError,
                telemetry.observability_contract.ContractError,
            ) as error:
                raise CommandError("collection-unavailable") from error
        elif orchestrator._read_owner_file(
            bundle_path,
            required=False,
        ) is not None:
            raise CommandError("contract-refused")

        expected_result = _result(
            state,
            phase=phase,
            bundle=complete_bundle if phase == "after" else None,
            collector_source_sha256=invocation[
                "collector_source_sha256"
            ],
        )
        result_payload = orchestrator._read_owner_file(
            output_path,
            required=False,
        )
        if result_payload is not None:
            try:
                existing = orchestrator._canonical_document(
                    result_payload,
                    "telemetry collector output",
                )
            except orchestrator.OrchestratorError as error:
                raise CommandError("output-unavailable") from error
            if existing != expected_result:
                raise CommandError("output-unavailable")
        else:
            try:
                orchestrator._atomic_json(
                    output_path,
                    expected_result,
                    output=True,
                )
            except orchestrator.CommandError as error:
                raise CommandError("output-unavailable") from error
        return state["complete"]


def run(
    arguments: Sequence[str],
    *,
    stdout: Any = sys.stdout,
    stderr: Any = sys.stderr,
) -> int:
    if (
        len(arguments) != 2
        or arguments[0] != "--invocation"
        or not arguments[1]
    ):
        print("load telemetry failed: invalid-arguments", file=stderr)
        return 2
    try:
        complete = execute_invocation(Path(arguments[1]))
        invocation_payload = orchestrator._read_owner_file(Path(arguments[1]))
        if invocation_payload is None:
            raise CollectorError("telemetry invocation disappeared")
        invocation = orchestrator._canonical_document(
            invocation_payload,
            "telemetry invocation",
        )
        synthetic = invocation.get("execution_source") == "fixture"
    except CommandError as error:
        print(f"load telemetry failed: {error.category}", file=stderr)
        return 1
    except (
        CollectorError,
        orchestrator.CommandError,
        orchestrator.OrchestratorError,
    ):
        print("load telemetry failed: collection-unavailable", file=stderr)
        return 1
    if synthetic:
        print(
            (
                "load telemetry fixture completed"
                if complete
                else "load telemetry fixture window collected"
            ),
            file=stdout,
        )
        return 3
    print(
        (
            "load telemetry completed"
            if complete
            else "load telemetry window collected"
        ),
        file=stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
