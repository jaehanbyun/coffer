from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from python_target import (
    DIGEST,
    KEY,
    SCANNERS,
    SURFACES,
    PackageComponent,
    Target,
    TargetError,
    load_targets,
)

SCHEMA = "coffer.ui-python-overlay-matrices/v1"
LABEL = re.compile(r"^coffer-ui-python-[a-z0-9.-]+-v1$")


class MatrixError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatrixSurface:
    name: str
    target_keys: tuple[str, ...]
    targets: tuple[Target, ...]

    @property
    def components(self) -> tuple[PackageComponent, ...]:
        return tuple(
            component for target in self.targets for component in target.components
        )

    @property
    def probes(self) -> tuple[tuple[str, str], ...]:
        return tuple((target.key, target.probe) for target in self.targets)

    @property
    def result_name(self) -> str:
        return " + ".join(
            f"{component.display_name}=={component.to_version}"
            for component in self.components
        )

    def finding_ids_for(self, scanner: str) -> tuple[str, ...]:
        if scanner not in SCANNERS:
            raise MatrixError("matrix scanner is unsupported")
        return tuple(
            sorted(
                {
                    finding
                    for target in self.targets
                    for finding in target.finding_ids_for(scanner)
                }
            )
        )

    @property
    def scanner_finding_ids(self) -> dict[str, list[str]]:
        return {scanner: list(self.finding_ids_for(scanner)) for scanner in SCANNERS}


@dataclass(frozen=True)
class Matrix:
    key: str
    trial_label: str
    target_manifest_sha256: str
    surfaces: tuple[MatrixSurface, ...]

    def for_surface(self, surface: str) -> MatrixSurface:
        try:
            return {item.name: item for item in self.surfaces}[surface]
        except KeyError as error:
            raise MatrixError("matrix surface is unsupported") from error

    @property
    def target_keys(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    target_key
                    for surface in self.surfaces
                    for target_key in surface.target_keys
                }
            )
        )

    @property
    def targets(self) -> tuple[Target, ...]:
        by_key = {
            target.key: target
            for surface in self.surfaces
            for target in surface.targets
        }
        return tuple(by_key[key] for key in sorted(by_key))

    @property
    def components(self) -> tuple[PackageComponent, ...]:
        by_name = {
            component.normalized_name: component
            for target in self.targets
            for component in target.components
        }
        return tuple(by_name[name] for name in sorted(by_name))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise MatrixError("target manifest is unreadable") from error
    return digest.hexdigest()


def _target_keys(value: object, surface: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not KEY.fullmatch(item) for item in value)
        or value != sorted(set(value))
    ):
        raise MatrixError(f"{surface} matrix target keys are invalid")
    return tuple(value)


def _validate_surface(
    *,
    name: str,
    target_keys: tuple[str, ...],
    targets: dict[str, Target],
) -> MatrixSurface:
    expected_keys = tuple(
        key for key, target in targets.items() if name in target.surfaces
    )
    if target_keys != expected_keys:
        raise MatrixError(f"{name} matrix target set is not exact")
    selected = tuple(targets[key] for key in target_keys)
    components = tuple(
        component for target in selected for component in target.components
    )
    component_names = tuple(component.normalized_name for component in components)
    wheel_names = tuple(component.wheel_filename for component in components)
    if len(set(component_names)) != len(component_names) or len(
        set(wheel_names)
    ) != len(wheel_names):
        raise MatrixError(f"{name} matrix components overlap")
    for scanner in SCANNERS:
        findings = [
            finding
            for target in selected
            for finding in target.finding_ids_for(scanner)
        ]
        if len(set(findings)) != len(findings):
            raise MatrixError(f"{name} matrix findings overlap")
    return MatrixSurface(
        name=name,
        target_keys=target_keys,
        targets=selected,
    )


def load_matrices(
    matrix_path: Path,
    target_manifest_path: Path,
) -> dict[str, Matrix]:
    if not matrix_path.is_file() or matrix_path.is_symlink():
        raise MatrixError("matrix manifest is missing or linked")
    if not target_manifest_path.is_file() or target_manifest_path.is_symlink():
        raise MatrixError("target manifest is missing or linked")
    try:
        document = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixError("matrix manifest is unreadable") from error
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "target_manifest_sha256", "matrices"}
        or document.get("schema") != SCHEMA
    ):
        raise MatrixError("matrix manifest schema is unsupported")
    target_manifest_sha256 = document.get("target_manifest_sha256")
    if (
        not isinstance(target_manifest_sha256, str)
        or not DIGEST.fullmatch(target_manifest_sha256)
        or target_manifest_sha256 != _sha256_file(target_manifest_path)
    ):
        raise MatrixError("matrix target manifest hash is invalid")
    try:
        targets = load_targets(target_manifest_path)
    except TargetError as error:
        raise MatrixError("matrix target manifest is invalid") from error
    raw_matrices = document.get("matrices")
    if not isinstance(raw_matrices, dict) or not raw_matrices:
        raise MatrixError("matrix manifest is empty")
    matrices: dict[str, Matrix] = {}
    for key, raw in sorted(raw_matrices.items()):
        if (
            not isinstance(key, str)
            or not KEY.fullmatch(key)
            or not isinstance(raw, dict)
            or set(raw) != {"trial_label", "surfaces"}
        ):
            raise MatrixError("matrix entry is invalid")
        trial_label = raw.get("trial_label")
        raw_surfaces = raw.get("surfaces")
        if (
            not isinstance(trial_label, str)
            or not LABEL.fullmatch(trial_label)
            or not isinstance(raw_surfaces, dict)
            or set(raw_surfaces) != SURFACES
        ):
            raise MatrixError("matrix value is invalid")
        surfaces = tuple(
            _validate_surface(
                name=surface,
                target_keys=_target_keys(raw_surfaces[surface], surface),
                targets=targets,
            )
            for surface in sorted(SURFACES)
        )
        matrices[key] = Matrix(
            key=key,
            trial_label=trial_label,
            target_manifest_sha256=target_manifest_sha256,
            surfaces=surfaces,
        )
    return matrices


def load_matrix(
    matrix_path: Path,
    target_manifest_path: Path,
    key: str,
) -> Matrix:
    try:
        return load_matrices(matrix_path, target_manifest_path)[key]
    except KeyError as error:
        raise MatrixError("matrix key is unsupported") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target-manifest", type=Path, required=True)
    parser.add_argument("--matrix", required=True)
    arguments = parser.parse_args()
    try:
        load_matrix(
            arguments.manifest,
            arguments.target_manifest,
            arguments.matrix,
        )
    except MatrixError as error:
        print(f"coffer-ui-python-matrix: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
