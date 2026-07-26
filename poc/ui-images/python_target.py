from __future__ import annotations

import argparse
import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "coffer.ui-python-overlay-targets/v1"
KEY = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
VERSION = re.compile(r"^[0-9][A-Za-z0-9.+!-]{0,31}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINDING = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
WHEEL = re.compile(r"^[A-Za-z0-9._+-]+-py3-none-any\.whl$")
URL = re.compile(r"^https://files\.pythonhosted\.org/packages/[A-Za-z0-9/_.+-]+$")
PREFIX = re.compile(r"^[a-z][a-z0-9_]*/$")
LABEL = re.compile(r"^coffer-ui-python-[a-z0-9.-]+-v1$")
PROBES = {
    "django-template",
    "mako-render",
    "module-import",
    "pyjwt-hs256",
    "urllib3-pool",
}
SURFACES = frozenset({"horizon", "skyline"})


class TargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    key: str
    display_name: str
    normalized_name: str
    package_prefix: str
    from_version: str
    to_version: str
    wheel_filename: str
    wheel_url: str
    wheel_sha256: str
    finding_ids: tuple[str, ...]
    requires_dist: tuple[str, ...]
    surfaces: tuple[str, ...]
    probe: str
    trial_label: str

    @property
    def result_name(self) -> str:
        return f"{self.display_name}=={self.to_version}"

    @property
    def module_name(self) -> str:
        return self.package_prefix.removesuffix("/")

    @property
    def expected_probe_result(self) -> str:
        if self.probe in {"django-template", "mako-render", "pyjwt-hs256"}:
            return "coffer"
        if self.probe == "urllib3-pool":
            return "https://registry.example"
        return self.key


def _string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise TargetError(f"target {key} is invalid")
    return value


def _strings(document: dict[str, Any], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise TargetError(f"target {key} is invalid")
    return tuple(value)


def load_targets(path: Path) -> dict[str, Target]:
    if not path.is_file() or path.is_symlink():
        raise TargetError("target manifest is missing or linked")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TargetError("target manifest is unreadable") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise TargetError("target manifest schema is unsupported")
    raw_targets = document.get("targets")
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise TargetError("target manifest is empty")
    targets: dict[str, Target] = {}
    expected_fields = {
        "display_name",
        "finding_ids",
        "from_version",
        "normalized_name",
        "package_prefix",
        "probe",
        "requires_dist",
        "surfaces",
        "to_version",
        "trial_label",
        "wheel_filename",
        "wheel_sha256",
        "wheel_url",
    }
    for key, raw in sorted(raw_targets.items()):
        if (
            not isinstance(key, str)
            or not KEY.fullmatch(key)
            or not isinstance(raw, dict)
            or set(raw) != expected_fields
        ):
            raise TargetError("target entry is invalid")
        target = Target(
            key=key,
            display_name=_string(raw, "display_name"),
            normalized_name=_string(raw, "normalized_name"),
            package_prefix=_string(raw, "package_prefix"),
            from_version=_string(raw, "from_version"),
            to_version=_string(raw, "to_version"),
            wheel_filename=_string(raw, "wheel_filename"),
            wheel_url=_string(raw, "wheel_url"),
            wheel_sha256=_string(raw, "wheel_sha256"),
            finding_ids=_strings(raw, "finding_ids"),
            requires_dist=_strings(raw, "requires_dist"),
            surfaces=_strings(raw, "surfaces"),
            probe=_string(raw, "probe"),
            trial_label=_string(raw, "trial_label"),
        )
        if (
            not NAME.fullmatch(target.display_name)
            or target.normalized_name != key
            or not PREFIX.fullmatch(target.package_prefix)
            or not VERSION.fullmatch(target.from_version)
            or not VERSION.fullmatch(target.to_version)
            or target.from_version == target.to_version
            or not WHEEL.fullmatch(target.wheel_filename)
            or not URL.fullmatch(target.wheel_url)
            or not DIGEST.fullmatch(target.wheel_sha256)
            or not all(FINDING.fullmatch(item) for item in target.finding_ids)
            or not set(target.surfaces) <= SURFACES
            or target.probe not in PROBES
            or not LABEL.fullmatch(target.trial_label)
        ):
            raise TargetError("target value is invalid")
        targets[key] = target
    return targets


def load_target(path: Path, key: str) -> Target:
    try:
        return load_targets(path)[key]
    except KeyError as error:
        raise TargetError("target key is unsupported") from error


def probe_target(target: Target) -> str:
    module = importlib.import_module(target.module_name)
    if target.probe == "django-template":
        settings = importlib.import_module("django.conf").settings
        if settings.configured:
            raise TargetError("Django settings are already configured")
        settings.configure(
            INSTALLED_APPS=[],
            SECRET_KEY="coffer-fixture-only",
            TEMPLATES=[
                {
                    "BACKEND": (
                        "django.template.backends.django.DjangoTemplates"
                    ),
                }
            ],
            USE_I18N=False,
        )
        module.setup()
        engines = importlib.import_module("django.template").engines
        result = engines["django"].from_string("{{ value }}").render(
            {"value": "coffer"}
        )
    elif target.probe == "mako-render":
        template = importlib.import_module("mako.template").Template
        result = template("${value}").render(value="coffer")
    elif target.probe == "pyjwt-hs256":
        fixture_key = b"coffer-fixture-key-material-only-0001"
        token = module.encode(
            {"scope": "coffer"},
            fixture_key,
            algorithm="HS256",
        )
        payload = module.decode(
            token,
            fixture_key,
            algorithms=["HS256"],
        )
        result = payload.get("scope")
    elif target.probe == "urllib3-pool":
        manager = module.PoolManager()
        pool = manager.connection_from_url("https://registry.example")
        result = f"{pool.scheme}://{pool.host}"
        manager.clear()
    else:
        result = module.__name__
    if result != target.expected_probe_result:
        raise TargetError("target compatibility probe failed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target", required=True)
    arguments = parser.parse_args()
    try:
        target = load_target(arguments.manifest, arguments.target)
        result = probe_target(target)
    except (TargetError, ImportError):
        print("coffer-ui-python-target: compatibility probe failed")
        return 2
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "target": target.key,
                "version": target.to_version,
                "probe": target.probe,
                "result": result,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
