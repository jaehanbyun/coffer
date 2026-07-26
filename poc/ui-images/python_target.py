from __future__ import annotations

import argparse
import importlib
import json
import re
from dataclasses import dataclass
from importlib.machinery import EXTENSION_SUFFIXES
from io import BytesIO
from pathlib import Path
from typing import Any

SCHEMA = "coffer.ui-python-overlay-targets/v4"
KEY = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
VERSION = re.compile(r"^[0-9][A-Za-z0-9.+!-]{0,31}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINDING = re.compile(
    r"^(?:CVE-[0-9]{4}-[0-9]{4,}|"
    r"GHSA(?:-[23456789cfghjmpqrvwx]{4}){3})$"
)
WHEEL = re.compile(
    r"^[A-Za-z0-9._+-]+-(?:py3-none-any|"
    r"cp[0-9]{2,3}-(?:cp[0-9]{2,3}|abi3)-[A-Za-z0-9._]+)\.whl$"
)
URL = re.compile(r"^https://files\.pythonhosted\.org/packages/[A-Za-z0-9/_.+-]+$")
PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9_]*[/.]$")
LABEL = re.compile(r"^coffer-ui-python-[a-z0-9.-]+-v1$")
PROBES = {
    "click-cli",
    "django-template",
    "lxml-xxe",
    "mako-render",
    "msgpack-binary",
    "module-import",
    "pillow-png",
    "pyca-pair",
    "pyjwt-hs256",
    "ujson-binary",
    "urllib3-pool",
}
SURFACES = frozenset({"horizon", "skyline"})
SCANNERS = ("trivy", "scout")
WHEEL_ARCHITECTURES = frozenset({"any", "arm64", "amd64"})


class TargetError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageComponent:
    display_name: str
    normalized_name: str
    package_prefix: str
    from_version: str
    to_version: str
    wheel_filename: str
    wheel_url: str
    wheel_sha256: str
    wheel_architecture: str
    finding_ids_by_scanner: tuple[tuple[str, tuple[str, ...]], ...]
    requires_dist: tuple[str, ...]

    @property
    def module_name(self) -> str:
        return self.package_prefix.rstrip("/.")

    @property
    def finding_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    finding
                    for _, findings in self.finding_ids_by_scanner
                    for finding in findings
                }
            )
        )

    def finding_ids_for(self, scanner: str) -> tuple[str, ...]:
        try:
            return dict(self.finding_ids_by_scanner)[scanner]
        except KeyError as error:
            raise TargetError("target scanner is unsupported") from error

    @property
    def scanner_finding_ids(self) -> dict[str, list[str]]:
        return {
            scanner: list(findings)
            for scanner, findings in self.finding_ids_by_scanner
        }


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
    wheel_architecture: str
    finding_ids_by_scanner: tuple[tuple[str, tuple[str, ...]], ...]
    requires_dist: tuple[str, ...]
    surfaces: tuple[str, ...]
    probe: str
    trial_label: str
    companions: tuple[PackageComponent, ...]

    @property
    def primary(self) -> PackageComponent:
        return PackageComponent(
            display_name=self.display_name,
            normalized_name=self.normalized_name,
            package_prefix=self.package_prefix,
            from_version=self.from_version,
            to_version=self.to_version,
            wheel_filename=self.wheel_filename,
            wheel_url=self.wheel_url,
            wheel_sha256=self.wheel_sha256,
            wheel_architecture=self.wheel_architecture,
            finding_ids_by_scanner=self.finding_ids_by_scanner,
            requires_dist=self.requires_dist,
        )

    @property
    def components(self) -> tuple[PackageComponent, ...]:
        return (self.primary, *self.companions)

    @property
    def result_name(self) -> str:
        return " + ".join(
            f"{component.display_name}=={component.to_version}"
            for component in self.components
        )

    @property
    def module_name(self) -> str:
        return self.package_prefix.rstrip("/.")

    @property
    def finding_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    finding
                    for component in self.components
                    for finding in component.finding_ids
                }
            )
        )

    def finding_ids_for(self, scanner: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    finding
                    for component in self.components
                    for finding in component.finding_ids_for(scanner)
                }
            )
        )

    @property
    def scanner_finding_ids(self) -> dict[str, list[str]]:
        return {
            scanner: list(self.finding_ids_for(scanner))
            for scanner in SCANNERS
        }

    @property
    def expected_probe_result(self) -> str:
        if self.probe in {
            "click-cli",
            "django-template",
            "lxml-xxe",
            "mako-render",
            "msgpack-binary",
            "pillow-png",
            "pyca-pair",
            "pyjwt-hs256",
            "ujson-binary",
        }:
            return "coffer"
        if self.probe == "urllib3-pool":
            return "https://registry.example"
        return self.key


def _string(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise TargetError(f"target {key} is invalid")
    return value


def _strings(
    document: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = document.get(key)
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        raise TargetError(f"target {key} is invalid")
    return tuple(value)


def _wheel_matches_architecture(filename: str, architecture: str) -> bool:
    try:
        _, python_tag, abi_tag, platform_tag = filename.removesuffix(
            ".whl"
        ).rsplit("-", 3)
    except ValueError:
        return False
    if architecture == "any":
        return (python_tag, abi_tag, platform_tag) == ("py3", "none", "any")
    python_match = re.fullmatch(r"cp([0-9]{2,3})", python_tag)
    if (
        python_match is None
        or abi_tag not in {python_tag, "abi3"}
        or not platform_tag
    ):
        return False
    architecture_suffix = {
        "arm64": "_aarch64",
        "amd64": "_x86_64",
    }.get(architecture)
    return architecture_suffix is not None and all(
        platform.endswith(architecture_suffix)
        for platform in platform_tag.split(".")
    )


def _scanner_findings(
    document: dict[str, Any],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    value = document.get("finding_ids_by_scanner")
    if not isinstance(value, dict) or set(value) != set(SCANNERS):
        raise TargetError("target finding_ids_by_scanner is invalid")
    result: list[tuple[str, tuple[str, ...]]] = []
    union: set[str] = set()
    for scanner in SCANNERS:
        findings = value[scanner]
        if (
            not isinstance(findings, list)
            or any(
                not isinstance(item, str) or not FINDING.fullmatch(item)
                for item in findings
            )
            or findings != sorted(set(findings))
        ):
            raise TargetError("target finding_ids_by_scanner is invalid")
        union.update(findings)
        result.append((scanner, tuple(findings)))
    if not union:
        raise TargetError("target finding_ids_by_scanner is empty")
    return tuple(result)


def _component(document: dict[str, Any]) -> PackageComponent:
    expected_fields = {
        "display_name",
        "finding_ids_by_scanner",
        "from_version",
        "normalized_name",
        "package_prefix",
        "requires_dist",
        "to_version",
        "wheel_filename",
        "wheel_architecture",
        "wheel_sha256",
        "wheel_url",
    }
    if set(document) != expected_fields:
        raise TargetError("target component entry is invalid")
    component = PackageComponent(
        display_name=_string(document, "display_name"),
        normalized_name=_string(document, "normalized_name"),
        package_prefix=_string(document, "package_prefix"),
        from_version=_string(document, "from_version"),
        to_version=_string(document, "to_version"),
        wheel_filename=_string(document, "wheel_filename"),
        wheel_url=_string(document, "wheel_url"),
        wheel_sha256=_string(document, "wheel_sha256"),
        wheel_architecture=_string(document, "wheel_architecture"),
        finding_ids_by_scanner=_scanner_findings(document),
        requires_dist=_strings(document, "requires_dist", allow_empty=True),
    )
    if (
        not NAME.fullmatch(component.display_name)
        or not KEY.fullmatch(component.normalized_name)
        or not PREFIX.fullmatch(component.package_prefix)
        or not VERSION.fullmatch(component.from_version)
        or not VERSION.fullmatch(component.to_version)
        or component.from_version == component.to_version
        or not WHEEL.fullmatch(component.wheel_filename)
        or component.wheel_architecture not in WHEEL_ARCHITECTURES
        or not _wheel_matches_architecture(
            component.wheel_filename,
            component.wheel_architecture,
        )
        or not URL.fullmatch(component.wheel_url)
        or not DIGEST.fullmatch(component.wheel_sha256)
    ):
        raise TargetError("target component value is invalid")
    return component


def _companions(document: dict[str, Any]) -> tuple[PackageComponent, ...]:
    value = document.get("companions", [])
    if (
        not isinstance(value, list)
        or len(value) > 3
        or any(not isinstance(item, dict) for item in value)
    ):
        raise TargetError("target companions are invalid")
    result = tuple(_component(item) for item in value)
    if tuple(item.normalized_name for item in result) != tuple(
        sorted(item.normalized_name for item in result)
    ):
        raise TargetError("target companions are not sorted")
    return result


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
        "finding_ids_by_scanner",
        "from_version",
        "normalized_name",
        "package_prefix",
        "probe",
        "requires_dist",
        "surfaces",
        "to_version",
        "trial_label",
        "wheel_filename",
        "wheel_architecture",
        "wheel_sha256",
        "wheel_url",
    }
    for key, raw in sorted(raw_targets.items()):
        raw_fields = frozenset(raw) if isinstance(raw, dict) else frozenset()
        if (
            not isinstance(key, str)
            or not KEY.fullmatch(key)
            or not isinstance(raw, dict)
            or raw_fields
            not in {
                frozenset(expected_fields),
                frozenset({*expected_fields, "companions"}),
            }
        ):
            raise TargetError("target entry is invalid")
        companions = _companions(raw)
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
            wheel_architecture=_string(raw, "wheel_architecture"),
            finding_ids_by_scanner=_scanner_findings(raw),
            requires_dist=_strings(raw, "requires_dist", allow_empty=True),
            surfaces=_strings(raw, "surfaces"),
            probe=_string(raw, "probe"),
            trial_label=_string(raw, "trial_label"),
            companions=companions,
        )
        component_names = tuple(
            component.normalized_name for component in target.components
        )
        finding_sets = [
            set(component.finding_ids) for component in target.components
        ]
        if (
            not NAME.fullmatch(target.display_name)
            or not PREFIX.fullmatch(target.package_prefix)
            or not VERSION.fullmatch(target.from_version)
            or not VERSION.fullmatch(target.to_version)
            or target.from_version == target.to_version
            or not WHEEL.fullmatch(target.wheel_filename)
            or target.wheel_architecture not in WHEEL_ARCHITECTURES
            or not _wheel_matches_architecture(
                target.wheel_filename,
                target.wheel_architecture,
            )
            or not URL.fullmatch(target.wheel_url)
            or not DIGEST.fullmatch(target.wheel_sha256)
            or not set(target.surfaces) <= SURFACES
            or target.probe not in PROBES
            or not LABEL.fullmatch(target.trial_label)
            or len(set(component_names)) != len(component_names)
            or len(
                {
                    component.wheel_filename
                    for component in target.components
                }
            )
            != len(target.components)
            or any(
                left & right
                for index, left in enumerate(finding_sets)
                for right in finding_sets[index + 1 :]
            )
            or (
                not companions
                and target.normalized_name != key
            )
            or (
                companions
                and "-".join(component_names) != key
            )
        ):
            raise TargetError("target value is invalid")
        targets[key] = target
    return targets


def load_target(path: Path, key: str) -> Target:
    try:
        return load_targets(path)[key]
    except KeyError as error:
        raise TargetError("target key is unsupported") from error


def probe_target(target: Target, *, enforce_security: bool = True) -> str:
    module = importlib.import_module(target.module_name)
    if target.probe == "click-cli":
        runner_type = importlib.import_module("click.testing").CliRunner

        @module.command()
        @module.option("--value", required=True)
        def command(value: str) -> None:
            module.echo(value)

        invocation = runner_type().invoke(command, ["--value", "coffer"])
        if invocation.exit_code != 0 or invocation.exception is not None:
            raise TargetError("Click CLI invocation failed")
        result = invocation.output.strip()
    elif target.probe == "msgpack-binary":
        if module.Packer.__module__ != "msgpack._cmsgpack":
            raise TargetError("msgpack native extension is not active")
        first = {"scope": "coffer", "values": [1, 2, 3]}
        second = {"scope": "next"}
        unpacker = module.Unpacker(raw=False)
        unpacker.feed(module.packb(first, use_bin_type=True))
        unpacker.feed(module.packb(second, use_bin_type=True))
        decoded = list(unpacker)
        if decoded != [first, second]:
            raise TargetError("msgpack streaming round trip failed")
        result = decoded[0]["scope"]
    elif target.probe == "ujson-binary":
        module_path = str(getattr(module, "__file__", ""))
        if not any(module_path.endswith(suffix) for suffix in EXTENSION_SUFFIXES):
            raise TargetError("ujson native extension is not active")
        payload = {
            "items": [1, 2.5, True, None],
            "nested": {"utf8": "장독"},
            "scope": "coffer",
        }
        encoded = module.dumps(payload, ensure_ascii=False, sort_keys=True)
        decoded = module.loads(encoded)
        if decoded != payload:
            raise TargetError("ujson round trip failed")
        result = decoded["scope"]
    elif target.probe == "lxml-xxe":
        etree = importlib.import_module("lxml.etree")
        module_path = str(getattr(etree, "__file__", ""))
        if not any(module_path.endswith(suffix) for suffix in EXTENSION_SUFFIXES):
            raise TargetError("lxml native extension is not active")
        root = etree.fromstring(
            b'<registry><repository name="coffer"/></registry>'
        )
        result = root.xpath("string(repository/@name)")
        if enforce_security:
            external_entity = (
                b"<!DOCTYPE root ["
                b'<!ENTITY ext SYSTEM "file:///etc/os-release">'
                b"]><root>&ext;</root>"
            )
            parsers = (
                lambda: etree.fromstring(
                    external_entity,
                    etree.ETCompatXMLParser(),
                ),
                lambda: list(
                    etree.iterparse(
                        BytesIO(external_entity),
                        events=("end",),
                    )
                ),
            )
            for parse in parsers:
                try:
                    parse()
                except etree.XMLSyntaxError:
                    continue
                raise TargetError("lxml external entity default is unsafe")
    elif target.probe == "pillow-png":
        image_module = importlib.import_module("PIL.Image")
        native_module = importlib.import_module("PIL._imaging")
        module_path = str(getattr(native_module, "__file__", ""))
        if not any(module_path.endswith(suffix) for suffix in EXTENSION_SUFFIXES):
            raise TargetError("Pillow native extension is not active")
        payload = image_module.new("RGB", (2, 2), (12, 34, 56))
        payload.putpixel((1, 1), (78, 90, 123))
        encoded = BytesIO()
        payload.save(encoded, format="PNG")
        if not encoded.getvalue().startswith(b"\x89PNG\r\n\x1a\n"):
            raise TargetError("Pillow PNG encoding failed")
        encoded.seek(0)
        with image_module.open(encoded) as decoded:
            decoded.load()
            if (
                decoded.format != "PNG"
                or decoded.mode != "RGB"
                or decoded.size != (2, 2)
                or decoded.getpixel((0, 0)) != (12, 34, 56)
                or decoded.getpixel((1, 1)) != (78, 90, 123)
            ):
                raise TargetError("Pillow PNG round trip failed")
        result = "coffer"
    elif target.probe == "pyca-pair":
        native_module = importlib.import_module(
            "cryptography.hazmat.bindings._rust"
        )
        module_path = str(getattr(native_module, "__file__", ""))
        if not any(module_path.endswith(suffix) for suffix in EXTENSION_SUFFIXES):
            raise TargetError("cryptography native extension is not active")
        aesgcm_type = importlib.import_module(
            "cryptography.hazmat.primitives.ciphers.aead"
        ).AESGCM
        key = bytes(range(32))
        nonce = bytes(range(12))
        plaintext = b"coffer"
        associated_data = b"coffer-fixture-only"
        cipher = aesgcm_type(key)
        ciphertext = cipher.encrypt(nonce, plaintext, associated_data)
        if (
            not ciphertext
            or cipher.decrypt(nonce, ciphertext, associated_data) != plaintext
        ):
            raise TargetError("cryptography AEAD round trip failed")
        ssl_module = importlib.import_module("OpenSSL.SSL")
        context = ssl_module.Context(ssl_module.TLS_METHOD)
        context.set_min_proto_version(ssl_module.TLS1_2_VERSION)
        context.set_cipher_list(b"ECDHE+AESGCM")
        context.set_options(ssl_module.OP_NO_COMPRESSION)
        result = plaintext.decode("ascii")
    elif target.probe == "django-template":
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
