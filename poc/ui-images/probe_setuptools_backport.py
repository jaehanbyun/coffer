from __future__ import annotations

import ast
import inspect
import json
import platform
import subprocess
import sys
import textwrap
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

SCHEMA = "coffer.ui-setuptools-backport-runtime/v1"
EXPECTED_EXECUTABLE = "/usr/bin/python3"
EXPECTED_DPKG_VERSION = "68.1.2-2ubuntu1.2"
EXPECTED_UPSTREAM_VERSION = "68.1.2"
SYSTEM_SITE = Path("/usr/lib/python3/dist-packages")


class ProbeError(RuntimeError):
    pass


def architecture() -> str:
    value = platform.machine().lower()
    if value in {"aarch64", "arm64"}:
        return "arm64"
    if value in {"amd64", "x86_64"}:
        return "amd64"
    raise ProbeError("system architecture is unsupported")


def dpkg_version(
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    process = run(
        [
            "dpkg-query",
            "--show",
            "--showformat=${Version}\\n",
            "python3-setuptools",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if (
        process.returncode != 0
        or process.stderr
        or process.stdout != f"{EXPECTED_DPKG_VERSION}\n"
    ):
        raise ProbeError("system setuptools dpkg revision is not exact")
    return process.stdout.strip()


def module_path(package_index: ModuleType) -> str:
    raw_path = getattr(package_index, "__file__", None)
    if not isinstance(raw_path, str):
        raise ProbeError("setuptools package_index path is unavailable")
    resolved = Path(raw_path).resolve()
    try:
        relative = resolved.relative_to(SYSTEM_SITE)
    except ValueError as error:
        raise ProbeError("setuptools module is outside the system site") from error
    if not relative.parts or relative.parts[0] != "setuptools":
        raise ProbeError("setuptools module path is not exact")
    return resolved.as_posix()


def _qualified_call(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        return f"{function.value.id}.{function.attr}"
    return None


def verify_vcs_source(source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError as error:
        raise ProbeError("setuptools VCS source is not parseable") from error
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    qualified = [_qualified_call(call) for call in calls]
    if qualified.count("subprocess.check_call") != 2 or "os.system" in qualified:
        raise ProbeError("setuptools VCS source does not contain the safe backport")
    if any(
        keyword.arg == "shell"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for call in calls
        for keyword in call.keywords
    ):
        raise ProbeError("setuptools VCS source enables a shell")
    return {
        "check_call_sites": 2,
        "os_system_sites": 0,
        "shell_true_sites": 0,
    }


def verify_vcs_runtime(package_index: ModuleType) -> dict[str, Any]:
    index_type = getattr(package_index, "PackageIndex", None)
    if index_type is None or not hasattr(index_type, "_download_vcs"):
        raise ProbeError("setuptools VCS backport is unavailable")
    calls: list[list[str]] = []

    def record(argv: object, *args: object, **kwargs: object) -> int:
        if (
            args
            or kwargs
            or not isinstance(argv, list)
            or not argv
            or any(not isinstance(value, str) for value in argv)
        ):
            raise ProbeError("setuptools VCS subprocess invocation is unsafe")
        calls.append(argv)
        return 0

    def reject_shell(*args: object, **kwargs: object) -> int:
        raise ProbeError("setuptools VCS path invoked os.system")

    subprocess_module = getattr(package_index, "subprocess", None)
    os_module = getattr(package_index, "os", None)
    if subprocess_module is None or os_module is None:
        raise ProbeError("setuptools VCS dependencies are unavailable")
    original_check_call = subprocess_module.check_call
    original_system = os_module.system
    destination = "/tmp/coffer-probe-checkout;touch-Coffer"
    try:
        subprocess_module.check_call = record
        os_module.system = reject_shell
        result = index_type()._download_vcs(
            (
                "git+https://example.invalid/group/project;touch-Coffer"
                "@rev;whoami#egg=fixture"
            ),
            destination,
        )
    finally:
        subprocess_module.check_call = original_check_call
        os_module.system = original_system
    expected = [
        [
            "git",
            "clone",
            "--quiet",
            "https://example.invalid/group/project;touch-Coffer",
            destination,
        ],
        [
            "git",
            "-C",
            destination,
            "checkout",
            "--quiet",
            "rev;whoami",
        ],
    ]
    if result != destination or calls != expected:
        raise ProbeError("setuptools VCS argv behavior is not exact")
    return {
        "argv_is_list": True,
        "calls": [
            ["git", "clone", "--quiet", "<url-with-metacharacters>", "<destination>"],
            [
                "git",
                "-C",
                "<destination>",
                "checkout",
                "--quiet",
                "<revision-with-metacharacters>",
            ],
        ],
        "subprocess_count": 2,
    }


def verify_path_containment(package_index: ModuleType) -> dict[str, Any]:
    index_type = getattr(package_index, "PackageIndex", None)
    resolver = getattr(index_type, "_resolve_download_filename", None)
    if resolver is None:
        raise ProbeError("setuptools download filename backport is unavailable")
    root = Path("/tmp/coffer-setuptools-backport-root")
    malicious = "https://anyhost/%2fhome%2fuser%2f.ssh%2fauthorized_keys"
    try:
        resolver(malicious, root)
    except ValueError as error:
        if not str(error).startswith("Invalid filename "):
            raise ProbeError("setuptools path rejection is not exact") from error
    else:
        raise ProbeError("setuptools accepted an encoded absolute path")
    benign = "https://files.pythonhosted.org/packages/fixture/setuptools-78.1.0.tar.gz"
    resolved = Path(resolver(benign, root))
    if resolved != root / "setuptools-78.1.0.tar.gz":
        raise ProbeError("setuptools benign path resolution is not exact")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ProbeError("setuptools benign path escaped the root") from error
    return {
        "benign_relative_path": "setuptools-78.1.0.tar.gz",
        "encoded_absolute_path_rejected": True,
    }


def collect(
    package_index: ModuleType,
    *,
    metadata_version: Callable[[str], str] = metadata.version,
    executable: str = sys.executable,
) -> dict[str, Any]:
    if executable != EXPECTED_EXECUTABLE:
        raise ProbeError("probe is not running under system Python")
    installed_version = metadata_version("setuptools")
    if installed_version != EXPECTED_UPSTREAM_VERSION:
        raise ProbeError("system setuptools metadata version is not exact")
    source = inspect.getsource(package_index.PackageIndex._download_vcs)
    return {
        "architecture": architecture(),
        "decision": {
            "backported_behaviors_verified": True,
            "findings": {
                "CVE-2024-6345": "not_affected",
                "CVE-2025-47273": "not_affected",
            },
            "vex_generation_allowed": True,
        },
        "package": {
            "dpkg_name": "python3-setuptools",
            "dpkg_version": dpkg_version(),
            "metadata_name": "setuptools",
            "metadata_version": installed_version,
            "module_path": module_path(package_index),
            "python": executable,
        },
        "path_containment": verify_path_containment(package_index),
        "schema": SCHEMA,
        "vcs": {
            "runtime": verify_vcs_runtime(package_index),
            "source": verify_vcs_source(source),
        },
    }


def main() -> int:
    try:
        import setuptools.package_index as package_index

        result = collect(package_index)
    except (OSError, ProbeError, subprocess.SubprocessError) as error:
        print(f"coffer-ui-setuptools-backport-probe: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
