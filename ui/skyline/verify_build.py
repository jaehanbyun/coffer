#!/usr/bin/env python3
"""Verify one built and packaged Coffer Skyline Console overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
EXPECTED_VERSION = "8.0.0+coffer.1"
REQUIRED_TRANSLATIONS = {
    "How to connect",
    "Images & Artifacts",
    "Create Repository",
    "Immutable Tags",
    "Repositories",
    "Repository Detail",
    "Repository Name",
    "Registry",
    "Registry Quota",
    "Search by tag or digest",
}


class VerificationError(RuntimeError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise VerificationError(message)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _verify_source(tree: Path) -> None:
    constants = _read(tree / "src/client/client/constants.js")
    routes = _read(tree / "src/pages/basic/routes/index.js")
    menu = _read(tree / "src/layouts/menu.jsx")
    repositories = _read(tree / "src/stores/coffer/repositories.js")
    _require("coffer: 'v1'" in constants, "Coffer endpoint version is missing")
    _require(
        "getOriginEndpoint('coffer') ? getOpenstackEndpoint('coffer') : ''"
        in constants,
        "Coffer endpoint absence does not fail closed",
    )
    _require("'pages/coffer/App'" in routes, "Coffer route module is missing")
    _require("path: `/registry`" in routes, "Registry root route is missing")
    _require("endpoints: 'coffer'" in menu, "Registry menu is not catalog gated")
    _require(
        "routePath: '/registry/repository/detail/:id'" in menu,
        "repository detail route map is missing",
    )
    _require(
        "get listResponseKey()" in repositories
        and "return 'repositories';" in repositories,
        "repository list response envelope is not explicitly pluralized",
    )
    artifacts = _read(tree / "src/stores/coffer/artifacts.js")
    artifact_page = _read(
        tree
        / "src/pages/coffer/containers/Repository/Detail/Artifacts/index.jsx"
    )
    _require(
        "client.artifacts.list" in artifacts
        and "client.endpoint" in artifacts,
        "artifact and endpoint store contracts are missing",
    )
    _require(
        "Search by tag or digest" in artifact_page
        and "How to connect" in artifact_page,
        "artifact discovery UX is missing",
    )

    locale = json.loads(_read(tree / "src/locales/en.json"))
    for key in REQUIRED_TRANSLATIONS:
        _require(locale.get(key) == key, f"generated English locale is missing {key}")

    source_root = tree / "src"
    production_files = []
    for path in source_root.rglob("*"):
        if not path.is_file() or path.name.endswith((".test.js", ".spec.js")):
            continue
        if "coffer" in path.relative_to(source_root).parts:
            production_files.append(path)
    production = "\n".join(_read(path) for path in production_files)
    for forbidden in (
        "http://",
        "https://",
        "keystone_token",
        "localStorage",
        "sessionStorage",
        ".delete(",
    ):
        _require(
            forbidden not in production,
            f"forbidden Coffer source token: {forbidden}",
        )


def _verify_static(tree: Path) -> Path:
    static = tree / "skyline_console/static"
    bundles = list(static.glob("coffer.bundle.*.js"))
    _require(len(bundles) == 1, "expected exactly one Coffer production bundle")
    bundle = _read(bundles[0])
    _require("Registry Quota" in bundle, "Coffer bundle lacks the quota surface")
    _require("cofferRepository" in bundle, "Coffer bundle lacks repository routes")
    _require(
        "Images & Artifacts" in bundle,
        "Coffer bundle lacks artifact discovery",
    )
    _require(
        "How to connect" in bundle,
        "Coffer bundle lacks registry connection guidance",
    )
    _require((static / "index.html").is_file(), "Skyline index is missing")
    return bundles[0]


def _verify_wheel(wheel_dir: Path, bundle: Path) -> None:
    wheels = list(wheel_dir.glob(f"skyline_console-{EXPECTED_VERSION}-*.whl"))
    _require(len(wheels) == 1, "expected exactly one versioned Skyline wheel")
    expected = f"skyline_console/static/{bundle.name}"
    with ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        _require(expected in names, "Coffer bundle is absent from the wheel")
        _require(
            "skyline_console/static/index.html" in names,
            "Skyline index is absent from the wheel",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tree = args.tree.resolve()
    wheel_dir = args.wheel_dir.resolve()
    _require(tree.is_dir(), "built tree is missing")
    _require(wheel_dir.is_dir(), "wheel directory is missing")
    _verify_source(tree)
    bundle = _verify_static(tree)
    _verify_wheel(wheel_dir, bundle)
    print("Coffer Skyline source, production bundle, and wheel verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except VerificationError as error:
        raise SystemExit(f"coffer-skyline-verify: {error}") from None
