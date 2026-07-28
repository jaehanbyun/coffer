from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from calendar import monthrange
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DIRECTORY = Path(__file__).resolve().parent
TRUST_SOURCE = DIRECTORY / "trust_policy.py"
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"

SCHEMA = "coffer.production-input-lineage/v2"
QUALIFICATION_PREDICATE_SCHEMA = "coffer.production-input-qualification-predicate/v2"
BUILDER_PREDICATE_SCHEMA = "coffer.production-build-predicate/v2"
INPUT_EVIDENCE_PREDICATE_SCHEMA = "coffer.production-input-evidence-predicate/v2"
RELEASE_VERIFICATION_PREDICATE_SCHEMA = (
    "coffer.production-release-verification-predicate/v2"
)
VEX_PREDICATE_SCHEMA = "coffer.production-openvex-predicate/v2"
PATCH_REVIEW_PREDICATE_SCHEMA = "coffer.production-patch-review-predicate/v2"
LIFECYCLE_OBSERVATION_PREDICATE_SCHEMA = (
    "coffer.production-lifecycle-observation-predicate/v2"
)
RESULT_SCHEMA = "coffer.production-input-result/v2"
LINEAGE_MANIFEST_MAX_BYTES = 1024 * 1024
QUALIFICATION_MAX_BYTES = 4 * 1024 * 1024
INPUT_RESULT_MAX_BYTES = 8 * 1024 * 1024

COMPONENTS = ("ceph", "distribution", "oslo_messaging")
INPUT_CLASSES = (
    "approved-vendor-backport",
    "coffer-minimal-patch",
    "official-upstream",
)
ARCHITECTURES = ("amd64", "arm64")
SCANNERS = ("scout", "trivy")
PRODUCT_KINDS = ("artifact", "image")
VEX_STATUSES = ("fixed", "not_affected", "under_investigation")

CHECKS = {
    "distribution": (
        "advertised_capabilities_verified",
        "lifecycle_rollback",
        "lifecycle_teardown",
        "multiarch_artifacts",
        "oci_core_conformance",
        "persistence",
        "runtime",
        "upgrade",
    ),
    "ceph": (
        "lifecycle_rollback",
        "lifecycle_teardown",
        "multiarch_artifacts",
        "persistence",
        "runtime",
        "s3_driver_compatibility",
        "upgrade",
    ),
    "oslo_messaging": (
        "dependency_import",
        "lifecycle_rollback",
        "lifecycle_teardown",
        "multiarch_artifacts",
        "runtime",
        "tls_hostname_verification",
        "upgrade",
    ),
}
EVIDENCE_KEYS = (
    "lifecycle_sha256",
    "protocol_sha256",
    "runtime_sha256",
    "security_sha256",
    "source_tree_sha256",
    "teardown_sha256",
    "upgrade_sha256",
)
SCOPE_CHECK_KEYS = (
    "feature_expansion",
    "protocol_extension",
    "referrers_reimplementation",
    "schema_change",
    "storage_format_change",
    "unrelated_dependency_refresh",
)

REVISION = re.compile(r"^[0-9a-f]{40}$")
CVE = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")


class InputLineageError(RuntimeError):
    pass


def _load_module(name: str, path: Path) -> Any:
    existing = sys.modules.get(name)
    if existing is not None:
        if Path(existing.__file__).resolve() != path.resolve():
            raise InputLineageError(f"module name {name} is already bound")
        return existing
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise InputLineageError(f"unable to load {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise InputLineageError(f"unable to load {path}") from error
    return module


TRUST = _load_module("coffer_production_trust_policy_v2", TRUST_SOURCE)


def _sha256(path: Path) -> str:
    try:
        return TRUST.sha256_file(path)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _sha256_bytes(payload: bytes) -> str:
    return TRUST.sha256_bytes(payload)


def _canonical_digest(value: object) -> str:
    try:
        return TRUST.canonical_sha256(value)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _require_serialized_size(
    value: object,
    *,
    maximum_bytes: int,
    label: str,
) -> None:
    try:
        size = len(TRUST.canonical_bytes(value)) + 1
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    if size > maximum_bytes:
        raise InputLineageError(f"{label} size exceeds the fixed budget")


def source_hashes() -> dict[str, str]:
    return {
        "input_lineage_verifier_sha256": _sha256(Path(__file__).resolve()),
        "trust_policy_verifier_sha256": _sha256(TRUST_SOURCE),
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputLineageError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputLineageError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise InputLineageError(f"{label} fields are invalid")


def _digest(value: object, label: str) -> str:
    try:
        return TRUST.digest(value, label)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _identifier(value: object, label: str) -> str:
    try:
        return TRUST.identifier(value, label)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _text(value: object, label: str, *, maximum: int = 2048) -> str:
    try:
        return TRUST.text(value, label, maximum=maximum)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _date(value: object, label: str) -> date:
    try:
        return TRUST.parse_date(value, label)
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error


def _revision(value: object, label: str) -> str:
    revision = _text(value, label, maximum=40)
    if REVISION.fullmatch(revision) is None:
        raise InputLineageError(f"{label} is invalid")
    return revision


def _url(value: object, label: str) -> str:
    url = _text(value, label)
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise InputLineageError(f"{label} is invalid") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
        or "\\" in parsed.path
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
        or "//" in parsed.path
    ):
        raise InputLineageError(f"{label} is invalid")
    return url


def _url_is_below_origin(url: str, origin: str) -> bool:
    target = urlsplit(url)
    source = urlsplit(origin)
    source_path = source.path.rstrip("/")
    return (
        target.scheme == source.scheme
        and target.netloc == source.netloc
        and target.path.startswith(source_path + "/")
    )


def _upstream_artifact_url(
    url: str,
    repository: str,
    *,
    input_class: str,
    status: str,
    label: str,
) -> None:
    target = urlsplit(url)
    source = urlsplit(repository)
    source_path = source.path.rstrip("/")
    kind: str | None = None
    if (
        target.netloc == source.netloc
        and not target.query
        and re.fullmatch(
            re.escape(source_path) + r"/(pull|issues)/[1-9][0-9]*",
            target.path.rstrip("/"),
        )
    ):
        kind = target.path.rstrip("/").split("/")[-2]
    elif (
        target.netloc == source.netloc
        and not target.query
        and re.fullmatch(
            re.escape(source_path) + r"/commit/[0-9a-f]{40}",
            target.path.rstrip("/"),
        )
    ):
        kind = "commit"
    elif (
        source.hostname == "opendev.org"
        and target.hostname == "review.opendev.org"
        and not target.query
        and re.fullmatch(
            r"/c/" + re.escape(source_path.lstrip("/")) + r"/\+/[1-9][0-9]*",
            target.path.rstrip("/"),
        )
    ):
        kind = "review"
    if (
        kind is None
        or (status == "merged" and kind == "issues")
        or (kind == "commit" and input_class != "approved-vendor-backport")
        or (kind == "commit" and status != "merged")
    ):
        raise InputLineageError(f"{label} is not an exact upstream change")


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _policy_vendor(
    policy: Mapping[str, Any],
    provider_id: str,
) -> Mapping[str, Any]:
    matches = [
        provider
        for provider in policy["vendors"]
        if provider["provider_id"] == provider_id
    ]
    if len(matches) != 1:
        raise InputLineageError("vendor provider is not allowlisted")
    return matches[0]


def _support(
    value: object,
    *,
    policy_release_end: date,
    today: date,
) -> dict[str, date]:
    support = _mapping(value, "support")
    _exact_keys(
        support,
        {"coffer_release_ends_on", "declared_ends_on", "starts_on"},
        "support",
    )
    starts = _date(support["starts_on"], "support starts_on")
    declared = _date(support["declared_ends_on"], "support declared_ends_on")
    coffer_end = _date(
        support["coffer_release_ends_on"],
        "support coffer_release_ends_on",
    )
    if (
        starts > today
        or starts > declared
        or declared > coffer_end
        or coffer_end != policy_release_end
    ):
        raise InputLineageError("support window is invalid")
    return {
        "coffer_release_ends_on": coffer_end,
        "declared_ends_on": declared,
        "starts_on": starts,
    }


def _upstream(
    value: object,
    *,
    component_policy: Mapping[str, Any],
) -> dict[str, Any]:
    upstream = _mapping(value, "upstream")
    _exact_keys(
        upstream,
        {
            "repository",
            "revision",
            "source_sha256",
            "support_ends_on",
            "tag",
            "version",
        },
        "upstream",
    )
    repository = _url(upstream["repository"], "upstream repository")
    tag = _text(upstream["tag"], "upstream tag", maximum=128)
    version = _text(
        upstream["version"],
        "upstream version",
        maximum=128,
    )
    if (
        repository not in component_policy["upstream_repositories"]
        or re.fullmatch(component_policy["tag_pattern"], tag) is None
        or version != tag
    ):
        raise InputLineageError("upstream release is not allowlisted")
    return {
        "repository": repository,
        "revision": _revision(upstream["revision"], "upstream revision"),
        "source_sha256": _digest(
            upstream["source_sha256"],
            "upstream source",
        ),
        "support_ends_on": _date(
            upstream["support_ends_on"],
            "upstream support_ends_on",
        ),
        "tag": tag,
        "version": version,
    }


def _release_identity(value: object) -> dict[str, str]:
    release = _mapping(value, "release")
    _exact_keys(
        release,
        {"repository", "revision", "source_sha256", "tag", "version"},
        "release",
    )
    repository = _url(release["repository"], "release repository")
    tag = _text(release["tag"], "release tag", maximum=128)
    version = _text(release["version"], "release version", maximum=128)
    return {
        "repository": repository,
        "revision": _revision(release["revision"], "release revision"),
        "source_sha256": _digest(release["source_sha256"], "release source"),
        "tag": tag,
        "version": version,
    }


def _artifacts(value: object) -> dict[str, Any]:
    artifacts = _mapping(value, "artifacts")
    _exact_keys(
        artifacts,
        {
            "architectures",
            "base_image_sha256",
            "build_recipe_sha256",
            "source_bundle_sha256",
            "toolchain_sha256",
        },
        "artifacts",
    )
    architectures = _array(
        artifacts["architectures"],
        "artifact architectures",
    )
    if len(architectures) != len(ARCHITECTURES):
        raise InputLineageError("artifact architectures are incomplete")
    parsed_architectures: list[dict[str, str]] = []
    identities: set[str] = set()
    for expected, raw in zip(ARCHITECTURES, architectures, strict=True):
        architecture = _mapping(raw, f"{expected} artifact")
        _exact_keys(
            architecture,
            {
                "artifact_sha256",
                "image_sha256",
                "name",
                "sbom_sha256",
            },
            f"{expected} artifact",
        )
        if architecture["name"] != expected:
            raise InputLineageError("artifact architecture order is invalid")
        item = {
            "artifact_sha256": _digest(
                architecture["artifact_sha256"],
                f"{expected} artifact",
            ),
            "image_sha256": _digest(
                architecture["image_sha256"],
                f"{expected} image",
            ),
            "name": expected,
            "sbom_sha256": _digest(
                architecture["sbom_sha256"],
                f"{expected} SBOM",
            ),
        }
        values = {
            item["artifact_sha256"],
            item["image_sha256"],
            item["sbom_sha256"],
        }
        if len(values) != 3 or identities.intersection(values):
            raise InputLineageError("artifact identities are not distinct")
        identities.update(values)
        parsed_architectures.append(item)
    materials = {
        "base_image_sha256": _digest(
            artifacts["base_image_sha256"],
            "base image",
        ),
        "build_recipe_sha256": _digest(
            artifacts["build_recipe_sha256"],
            "build recipe",
        ),
        "source_bundle_sha256": _digest(
            artifacts["source_bundle_sha256"],
            "source bundle",
        ),
        "toolchain_sha256": _digest(
            artifacts["toolchain_sha256"],
            "toolchain",
        ),
    }
    if len(set(materials.values()) | identities) != len(materials) + len(identities):
        raise InputLineageError("artifact and material identities overlap")
    return {"architectures": parsed_architectures, **materials}


def _patches(
    value: object,
    *,
    component: str,
    upstream_repository: str,
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    patches = _array(value, "patches")
    parsed: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_digests: set[str] = set()
    for index, raw in enumerate(patches):
        patch = _mapping(raw, f"patch {index}")
        _exact_keys(
            patch,
            {
                "blocker_id",
                "changed_paths_sha256",
                "id",
                "kind",
                "scope",
                "sha256",
                "upstream_revision",
                "upstream_url",
            },
            f"patch {index}",
        )
        patch_id = _identifier(patch["id"], f"patch {index} id")
        patch_digest = _digest(patch["sha256"], f"patch {index}")
        blocker_id = _identifier(
            patch["blocker_id"],
            f"patch {index} blocker",
        )
        blocker = policy["blockers"].get(blocker_id)
        if (
            patch_id in seen_ids
            or patch_digest in seen_digests
            or blocker is None
            or blocker["component"] != component
            or blocker["kind"] != patch["kind"]
            or blocker["upstream_repository"] != upstream_repository
            or patch["scope"] != "minimal"
        ):
            raise InputLineageError("patch policy is invalid")
        seen_ids.add(patch_id)
        seen_digests.add(patch_digest)
        upstream_url = _url(
            patch["upstream_url"],
            f"patch {index} upstream URL",
        )
        parsed.append(
            {
                "blocker_id": blocker_id,
                "changed_paths_sha256": _digest(
                    patch["changed_paths_sha256"],
                    f"patch {index} changed paths",
                ),
                "id": patch_id,
                "kind": patch["kind"],
                "scope": "minimal",
                "sha256": patch_digest,
                "upstream_revision": _revision(
                    patch["upstream_revision"],
                    f"patch {index} upstream revision",
                ),
                "upstream_url": upstream_url,
            }
        )
    return parsed


def _submission(
    value: object,
    *,
    patches: Sequence[Mapping[str, Any]],
    input_class: str,
    upstream_repository: str,
) -> dict[str, Any]:
    submission = _mapping(value, "upstream submission")
    _exact_keys(
        submission,
        {"items", "required"},
        "upstream submission",
    )
    required = submission["required"]
    raw_items = _array(submission["items"], "upstream submission items")
    if not isinstance(required, bool):
        raise InputLineageError("upstream submission is invalid")
    if (required and len(raw_items) != len(patches)) or (
        not required and (raw_items or patches)
    ):
        raise InputLineageError("upstream submission coverage is invalid")
    parsed: list[dict[str, str]] = []
    for index, (raw, patch) in enumerate(
        zip(raw_items, patches, strict=True)
    ):
        item = _mapping(raw, f"upstream submission item {index}")
        _exact_keys(
            item,
            {
                "patch_id",
                "revision",
                "status",
                "url",
            },
            f"upstream submission item {index}",
        )
        status = item["status"]
        if status not in {"merged", "open"}:
            raise InputLineageError("upstream submission is not active")
        url = _url(item["url"], f"upstream submission item {index} URL")
        revision = _revision(
            item["revision"],
            f"upstream submission item {index} revision",
        )
        if (
            item["patch_id"] != patch["id"]
            or revision != patch["upstream_revision"]
            or url != patch["upstream_url"]
        ):
            raise InputLineageError("upstream submission patch binding changed")
        _upstream_artifact_url(
            url,
            upstream_repository,
            input_class=input_class,
            status=status,
            label=f"upstream submission item {index} URL",
        )
        parsed.append(
            {
                "patch_id": patch["id"],
                "revision": revision,
                "status": status,
                "url": url,
            }
        )
    return {"items": parsed, "required": required}


def _provider(
    value: object,
    *,
    component: str,
    downstream: Mapping[str, Any],
    upstream: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    provider = _mapping(value, "vendor provider")
    _exact_keys(
        provider,
        {
            "advisory_url",
            "provider_id",
            "repository",
            "support_ends_on",
        },
        "vendor provider",
    )
    provider_id = _identifier(provider["provider_id"], "vendor provider ID")
    policy_provider = _policy_vendor(policy, provider_id)
    if component not in policy_provider["components"]:
        raise InputLineageError("vendor component is not allowlisted")
    repository = _url(provider["repository"], "vendor repository")
    advisory = _url(provider["advisory_url"], "vendor advisory URL")
    if repository not in policy_provider["repositories"] or not any(
        _url_is_below_origin(advisory, origin)
        for origin in policy_provider["advisory_origins"]
    ):
        raise InputLineageError("vendor source or advisory is not allowlisted")
    release = policy_provider["releases"].get(downstream["version"])
    if (
        release is None
        or release["component"] != component
        or release["repository"] != repository
        or release["revision"] != downstream["revision"]
        or release["source_sha256"] != downstream["source_sha256"]
        or release["tag"] != downstream["tag"]
        or release["upstream_revision"] != upstream["revision"]
        or release["upstream_source_sha256"] != upstream["source_sha256"]
        or release["upstream_tag"] != upstream["tag"]
    ):
        raise InputLineageError("vendor release is not allowlisted")
    support_end = _date(
        provider["support_ends_on"],
        "vendor support_ends_on",
    )
    if support_end != _date(
        release["support_ends_on"],
        "vendor policy support_ends_on",
    ):
        raise InputLineageError("vendor support changed from policy")
    return (
        {
            "advisory_url": advisory,
            "provider_id": provider_id,
            "repository": repository,
            "support_ends_on": support_end,
        },
        policy_provider,
        release,
    )


def _coffer_maintenance(value: object) -> dict[str, Any]:
    maintenance = _mapping(value, "Coffer maintenance")
    _exact_keys(
        maintenance,
        {
            "changed_tree_sha256",
            "owner_key_id",
            "released_on",
            "scope_checks",
        },
        "Coffer maintenance",
    )
    scope_checks = _mapping(
        maintenance["scope_checks"],
        "Coffer patch scope checks",
    )
    _exact_keys(
        scope_checks,
        set(SCOPE_CHECK_KEYS),
        "Coffer patch scope checks",
    )
    if any(value is not False for value in scope_checks.values()):
        raise InputLineageError("Coffer patch is not minimal")
    return {
        "changed_tree_sha256": _digest(
            maintenance["changed_tree_sha256"],
            "Coffer changed tree",
        ),
        "owner_key_id": _identifier(
            maintenance["owner_key_id"],
            "Coffer patch owner key ID",
        ),
        "released_on": _date(
            maintenance["released_on"],
            "Coffer patch released_on",
        ),
        "scope_checks": {name: False for name in SCOPE_CHECK_KEYS},
    }


def validate_manifest(
    value: object,
    *,
    policy: Mapping[str, Any],
    today: date | None = None,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    manifest = _mapping(value, "lineage manifest")
    _exact_keys(
        manifest,
        {
            "artifacts",
            "coffer_maintenance",
            "component",
            "fixture_only",
            "input_class",
            "patches",
            "provider",
            "release",
            "schema",
            "support",
            "upstream",
            "upstream_submission",
        },
        "lineage manifest",
    )
    component = manifest["component"]
    input_class = manifest["input_class"]
    if (
        manifest["schema"] != SCHEMA
        or component not in COMPONENTS
        or input_class not in INPUT_CLASSES
        or not isinstance(manifest["fixture_only"], bool)
    ):
        raise InputLineageError("lineage manifest identity is invalid")
    if policy["environment"] == "production" and manifest["fixture_only"] is not False:
        raise InputLineageError("fixture lineage is not production evidence")
    component_policy = policy["components"][component]
    support = _support(
        manifest["support"],
        policy_release_end=_date(
            policy["coffer"]["release_ends_on"],
            "Coffer policy release end",
        ),
        today=current,
    )
    upstream = _upstream(
        manifest["upstream"],
        component_policy=component_policy,
    )
    artifacts = _artifacts(manifest["artifacts"])
    release_identity = _release_identity(manifest["release"])
    if release_identity["source_sha256"] != artifacts["source_bundle_sha256"]:
        raise InputLineageError("release source is not the built source bundle")
    patches = _patches(
        manifest["patches"],
        component=component,
        upstream_repository=upstream["repository"],
        policy=policy,
    )
    submission = _submission(
        manifest["upstream_submission"],
        patches=patches,
        input_class=input_class,
        upstream_repository=upstream["repository"],
    )

    provider: dict[str, Any] | None = None
    provider_policy: Mapping[str, Any] | None = None
    coffer: dict[str, Any] | None = None
    coffer_patch_policy: Mapping[str, Any] | None = None
    if input_class == "official-upstream":
        release = component_policy["official_releases"].get(upstream["tag"])
        if (
            patches
            or manifest["provider"] is not None
            or manifest["coffer_maintenance"] is not None
            or submission["required"]
            or release is None
            or release["revision"] != upstream["revision"]
            or release["source_sha256"] != upstream["source_sha256"]
            or _date(
                release["support_ends_on"],
                "official policy support_ends_on",
            )
            != upstream["support_ends_on"]
            or upstream["version"] != upstream["tag"]
            or release_identity
            != {
                "repository": upstream["repository"],
                "revision": upstream["revision"],
                "source_sha256": upstream["source_sha256"],
                "tag": upstream["tag"],
                "version": upstream["version"],
            }
            or upstream["support_ends_on"] < support["coffer_release_ends_on"]
            or support["declared_ends_on"] != support["coffer_release_ends_on"]
        ):
            raise InputLineageError("official upstream lineage policy is not satisfied")
    elif input_class == "approved-vendor-backport":
        if (
            not patches
            or manifest["provider"] is None
            or manifest["coffer_maintenance"] is not None
            or not submission["required"]
        ):
            raise InputLineageError("vendor backport lineage policy is not satisfied")
        provider, provider_policy, _ = _provider(
            manifest["provider"],
            component=component,
            downstream=release_identity,
            upstream=upstream,
            policy=policy,
        )
        if (
            release_identity["repository"] != provider["repository"]
            or release_identity["version"] == upstream["version"]
            or release_identity["revision"] == upstream["revision"]
            or release_identity["source_sha256"] == upstream["source_sha256"]
            or release_identity["tag"] == upstream["tag"]
            or provider["support_ends_on"] < support["coffer_release_ends_on"]
            or upstream["support_ends_on"] < support["coffer_release_ends_on"]
            or support["declared_ends_on"] != support["coffer_release_ends_on"]
        ):
            raise InputLineageError("vendor support does not cover the Coffer release")
    else:
        base = component_policy["accepted_patch_bases"].get(upstream["tag"])
        coffer_patch_policy = policy["coffer"]["patch_releases"].get(
            release_identity["version"]
        )
        if (
            not patches
            or manifest["provider"] is not None
            or manifest["coffer_maintenance"] is None
            or not submission["required"]
            or base is None
            or coffer_patch_policy is None
            or base["revision"] != upstream["revision"]
            or base["source_sha256"] != upstream["source_sha256"]
            or _date(
                base["support_ends_on"],
                "Coffer base support_ends_on",
            )
            != upstream["support_ends_on"]
        ):
            raise InputLineageError("Coffer patch lineage policy is not satisfied")
        coffer = _coffer_maintenance(manifest["coffer_maintenance"])
        initial_end = min(
            support["coffer_release_ends_on"],
            upstream["support_ends_on"],
            _add_months(
                coffer["released_on"],
                policy["coffer"]["maximum_patch_support_months"],
            ),
        )
        if (
            coffer["released_on"] != support["starts_on"]
            or support["declared_ends_on"] != initial_end
            or coffer_patch_policy["admitted_on"]
            != coffer["released_on"].isoformat()
            or coffer_patch_policy["component"] != component
            or coffer_patch_policy["owner_authority_key_id"]
            != coffer["owner_key_id"]
            or coffer_patch_policy["release_revision"]
            != release_identity["revision"]
            or coffer_patch_policy["release_source_sha256"]
            != release_identity["source_sha256"]
            or coffer_patch_policy["release_tag"]
            != release_identity["tag"]
            or coffer_patch_policy["support_ends_on"]
            != initial_end.isoformat()
            or coffer_patch_policy["upstream_revision"]
            != upstream["revision"]
            or coffer_patch_policy["upstream_source_sha256"]
            != upstream["source_sha256"]
            or coffer_patch_policy["upstream_tag"] != upstream["tag"]
            or release_identity["repository"] != policy["coffer"]["repository"]
            or release_identity["version"] != release_identity["tag"]
            or release_identity["version"] == upstream["version"]
            or re.fullmatch(
                component_policy["tag_pattern"],
                release_identity["tag"],
            )
            is None
            or release_identity["revision"] == upstream["revision"]
            or release_identity["source_sha256"] == upstream["source_sha256"]
        ):
            raise InputLineageError("Coffer patch support is not the earliest bound")

    return {
        "artifacts": artifacts,
        "coffer_maintenance": coffer,
        "coffer_patch_policy": coffer_patch_policy,
        "component": component,
        "fixture_only": manifest["fixture_only"],
        "input_class": input_class,
        "patches": patches,
        "provider": provider,
        "provider_policy": provider_policy,
        "release": release_identity,
        "schema": SCHEMA,
        "support": support,
        "upstream": upstream,
        "upstream_submission": submission,
    }


def _subject_map(lineage: Mapping[str, Any]) -> dict[str, str]:
    artifacts = lineage["artifacts"]
    result = {
        "base-image": artifacts["base_image_sha256"],
        "build-recipe": artifacts["build_recipe_sha256"],
        "source-bundle": artifacts["source_bundle_sha256"],
        "toolchain": artifacts["toolchain_sha256"],
    }
    for architecture in artifacts["architectures"]:
        name = architecture["name"]
        result[f"{name}-artifact"] = architecture["artifact_sha256"]
        result[f"{name}-image"] = architecture["image_sha256"]
        result[f"{name}-sbom"] = architecture["sbom_sha256"]
    return dict(sorted(result.items()))


def _product_map(lineage: Mapping[str, Any]) -> dict[str, str]:
    subjects = _subject_map(lineage)
    return {
        name: subjects[name]
        for name in sorted(subjects)
        if name.endswith(("-artifact", "-image"))
    }


def _materials(lineage: Mapping[str, Any]) -> dict[str, str]:
    artifacts = lineage["artifacts"]
    patches = lineage["patches"]
    patch_series = _canonical_digest(
        [{"id": patch["id"], "sha256": patch["sha256"]} for patch in patches]
    )
    return {
        "base_image_sha256": artifacts["base_image_sha256"],
        "build_recipe_sha256": artifacts["build_recipe_sha256"],
        "ordered_patch_series_sha256": patch_series,
        "source_bundle_sha256": artifacts["source_bundle_sha256"],
        "toolchain_sha256": artifacts["toolchain_sha256"],
        "upstream_source_sha256": lineage["upstream"]["source_sha256"],
    }


def _release_verification(
    value: object,
    *,
    lineage: Mapping[str, Any],
    provenance: Mapping[str, Any],
    policy: Mapping[str, Any],
    qualification_key: str,
    today: date,
) -> tuple[dict[str, Any], list[date]]:
    raw_attestation = _mapping(value, "release verification attestation")
    raw_predicate = _mapping(
        raw_attestation.get("predicate"),
        "release verification predicate",
    )
    adapter_id = _identifier(
        raw_predicate.get("adapter_id"),
        "release verification adapter ID",
    )
    adapter = policy["release_verification_adapters"].get(adapter_id)
    if adapter is None:
        raise InputLineageError("release verification adapter is not approved")
    release = raw_predicate
    _exact_keys(
        release,
        {
            "adapter_id",
            "draft",
            "prerelease",
            "repository",
            "revision",
            "schema",
            "signature_bundle_sha256",
            "signing_identity",
            "signed_subjects",
            "source_sha256",
            "tag",
        },
        "release verification predicate",
    )
    input_class = lineage["input_class"]
    component = lineage["component"]
    expected_release = lineage["release"]
    if input_class == "official-upstream":
        identities = policy["components"][component]["release_signing_identities"]
    elif input_class == "approved-vendor-backport":
        identities = lineage["provider_policy"]["release_signing_identities"]
    else:
        identities = policy["coffer"]["release_signing_identities"]
    signing_identity = _text(
        release["signing_identity"],
        "release signing identity",
    )
    signature_bundle = _digest(
        release["signature_bundle_sha256"],
        "release signature bundle",
    )
    expected_signed_subjects = {
        "provenance-statement": provenance["statement_sha256"],
        "release-source": expected_release["source_sha256"],
        **_subject_map(lineage),
    }
    raw_signed_subjects = _mapping(
        release["signed_subjects"],
        "release signed subjects",
    )
    signed_subjects = {
        name: _digest(value, f"release signed subject {name}")
        for name, value in sorted(raw_signed_subjects.items())
    }
    if (
        release["schema"] != RELEASE_VERIFICATION_PREDICATE_SCHEMA
        or release["draft"] is not False
        or release["prerelease"] is not False
        or release["repository"] != expected_release["repository"]
        or release["revision"] != expected_release["revision"]
        or release["source_sha256"] != expected_release["source_sha256"]
        or release["tag"] != expected_release["tag"]
        or signed_subjects != dict(sorted(expected_signed_subjects.items()))
        or signing_identity not in identities
        or component not in adapter["components"]
        or input_class not in adapter["input_classes"]
        or adapter["output_schema"] != RELEASE_VERIFICATION_PREDICATE_SCHEMA
    ):
        raise InputLineageError("release signature verification is invalid")
    subjects = {
        "release-subjects": _canonical_digest(expected_signed_subjects),
        "signature-bundle": signature_bundle,
        "verification-adapter": _canonical_digest(adapter),
    }
    try:
        attestation = TRUST.verify_attestation(
            raw_attestation,
            policy=policy,
            role="release-verification",
            predicate_type=policy["predicate_types"]["release_verification"],
            subjects=subjects,
            today=today,
            component=component,
            input_class=input_class,
        )
        verification_authority = TRUST.policy_authority(
            policy,
            key_id=attestation["key_id"],
            role="release-verification",
            component=component,
            input_class=input_class,
            today=today,
        )
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=component,
            input_class=input_class,
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    if (
        attestation["key_id"] != adapter["authority_key_id"]
        or _date(attestation["issued_on"], "release verification issued_on")
        < _date(adapter["valid_from"], "release adapter valid_from")
        or _date(attestation["expires_on"], "release verification expires_on")
        > _date(adapter["valid_until"], "release adapter valid_until")
        or verification_authority["trust_domain"]
        == qualification_authority["trust_domain"]
        or verification_authority["operator_id"]
        == qualification_authority["operator_id"]
    ):
        raise InputLineageError("release verification is not independent")
    normalized_predicate = {
        "adapter_id": adapter_id,
        "draft": False,
        "prerelease": False,
        "repository": expected_release["repository"],
        "revision": expected_release["revision"],
        "schema": RELEASE_VERIFICATION_PREDICATE_SCHEMA,
        "signature_bundle_sha256": signature_bundle,
        "signing_identity": signing_identity,
        "signed_subjects": dict(sorted(expected_signed_subjects.items())),
        "source_sha256": expected_release["source_sha256"],
        "tag": expected_release["tag"],
    }
    normalized_attestation = dict(attestation)
    normalized_attestation["predicate"] = normalized_predicate
    return normalized_attestation, [
        _date(attestation["expires_on"], "release verification expiry"),
        _date(adapter["valid_until"], "release verification adapter validity"),
    ]


def _input_evidence(
    value: object,
    *,
    lineage: Mapping[str, Any],
    lineage_sha256: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    qualification_key: str,
    today: date,
) -> tuple[
    dict[str, Any],
    list[date],
    dict[str, str],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
]:
    raw_attestation = _mapping(value, "input evidence attestation")
    predicate = _mapping(
        raw_attestation.get("predicate"),
        "input evidence predicate",
    )
    adapter_id = _identifier(
        predicate.get("adapter_id"),
        "input evidence adapter ID",
    )
    adapter = policy["input_evidence_adapters"].get(adapter_id)
    if (
        adapter is None
        or lineage["component"] not in adapter["components"]
        or lineage["input_class"] not in adapter["input_classes"]
        or adapter["output_schema"] != INPUT_EVIDENCE_PREDICATE_SCHEMA
    ):
        raise InputLineageError("input evidence adapter is not approved")
    _exact_keys(
        predicate,
        {
            "adapter_id",
            "checks",
            "evidence",
            "lineage_sha256",
            "observed_on",
            "policy_sha256",
            "residue",
            "scanner_inventory",
            "schema",
            "valid_until",
        },
        "input evidence predicate",
    )
    checks = _mapping(predicate["checks"], "input evidence checks")
    _exact_keys(
        checks,
        set(CHECKS[lineage["component"]]),
        "input evidence checks",
    )
    if any(not isinstance(value, bool) for value in checks.values()):
        raise InputLineageError("input evidence check status is invalid")
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    evidence = _mapping(predicate["evidence"], "input evidence")
    _exact_keys(evidence, set(EVIDENCE_KEYS), "input evidence")
    parsed_evidence = {
        name: _digest(evidence[name], f"input evidence {name}")
        for name in EVIDENCE_KEYS
    }
    inventory, findings = _findings(
        predicate["scanner_inventory"],
        lineage=lineage,
        today=today,
    )
    residue = _mapping(predicate["residue"], "input evidence residue")
    _exact_keys(
        residue,
        {"known_secret_matches", "total", "unexpected_errors"},
        "input evidence residue",
    )
    observed = _date(predicate["observed_on"], "input evidence observed_on")
    valid_until = _date(predicate["valid_until"], "input evidence valid_until")
    adapter_starts = _date(adapter["valid_from"], "input adapter valid_from")
    adapter_ends = _date(adapter["valid_until"], "input adapter valid_until")
    if (
        predicate["schema"] != INPUT_EVIDENCE_PREDICATE_SCHEMA
        or predicate["policy_sha256"] != policy_sha256
        or predicate["lineage_sha256"] != lineage_sha256
        or observed > today
        or today - observed > timedelta(days=1)
        or observed < adapter_starts
        or valid_until < today
        or valid_until > adapter_ends
        or valid_until - observed > timedelta(days=7)
        or residue
        != {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        }
        or any(
            _date(item["observed_on"], "scanner inventory observed_on") < adapter_starts
            or _date(item["observed_on"], "scanner inventory observed_on") > observed
            for item in inventory
        )
    ):
        raise InputLineageError("input operational evidence is invalid")
    subjects = {
        "adapter": _canonical_digest(adapter),
        "lineage": lineage_sha256,
        **_subject_map(lineage),
        **{
            f"evidence:{name}": digest
            for name, digest in sorted(parsed_evidence.items())
        },
        "scanner-inventory": _canonical_digest(inventory),
    }
    try:
        attestation = TRUST.verify_attestation(
            raw_attestation,
            policy=policy,
            role="input-evidence",
            predicate_type=policy["predicate_types"]["input_evidence"],
            subjects=dict(sorted(subjects.items())),
            today=today,
            component=lineage["component"],
            input_class=lineage["input_class"],
        )
        evidence_authority = TRUST.policy_authority(
            policy,
            key_id=attestation["key_id"],
            role="input-evidence",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    if (
        attestation["key_id"] != adapter["authority_key_id"]
        or _date(attestation["issued_on"], "input evidence issued_on") < adapter_starts
        or _date(attestation["issued_on"], "input evidence issued_on") < observed
        or _date(attestation["expires_on"], "input evidence expires_on") > adapter_ends
        or evidence_authority["trust_domain"] == qualification_authority["trust_domain"]
        or evidence_authority["operator_id"] == qualification_authority["operator_id"]
    ):
        raise InputLineageError("input evidence is not independently trusted")
    normalized_predicate = {
        "adapter_id": adapter_id,
        "checks": {
            name: checks[name] for name in CHECKS[lineage["component"]]
        },
        "evidence": parsed_evidence,
        "lineage_sha256": lineage_sha256,
        "observed_on": observed.isoformat(),
        "policy_sha256": policy_sha256,
        "residue": {
            "known_secret_matches": 0,
            "total": 0,
            "unexpected_errors": 0,
        },
        "scanner_inventory": inventory,
        "schema": INPUT_EVIDENCE_PREDICATE_SCHEMA,
        "valid_until": valid_until.isoformat(),
    }
    normalized_attestation = dict(attestation)
    normalized_attestation["predicate"] = normalized_predicate
    return (
        normalized_attestation,
        [
            valid_until,
            _date(attestation["expires_on"], "input evidence expiry"),
            adapter_ends,
        ],
        parsed_evidence,
        inventory,
        findings,
        failed_checks,
    )


def _builder_attestations(
    value: object,
    *,
    lineage: Mapping[str, Any],
    lineage_sha256: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    qualification_key: str,
    today: date,
) -> tuple[list[dict[str, Any]], list[date], set[str]]:
    raw_builders = _array(value, "builder attestations")
    required = 1 if lineage["input_class"] == "official-upstream" else 2
    if len(raw_builders) != required * len(ARCHITECTURES):
        raise InputLineageError("builder attestation quorum is incomplete")
    artifacts = {item["name"]: item for item in lineage["artifacts"]["architectures"]}
    materials = _materials(lineage)
    materials_sha256 = _canonical_digest(materials)
    parsed: list[dict[str, Any]] = []
    expiry: list[date] = []
    keys_by_architecture: dict[str, set[str]] = {
        architecture: set() for architecture in ARCHITECTURES
    }
    domains_by_architecture: dict[str, set[str]] = {
        architecture: set() for architecture in ARCHITECTURES
    }
    operators_by_architecture: dict[str, set[str]] = {
        architecture: set() for architecture in ARCHITECTURES
    }
    try:
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    for raw in raw_builders:
        raw_map = _mapping(raw, "builder attestation")
        raw_predicate = _mapping(
            raw_map.get("predicate"),
            "builder predicate",
        )
        architecture = raw_predicate.get("architecture")
        if architecture not in ARCHITECTURES:
            raise InputLineageError("builder architecture is invalid")
        artifact = artifacts[architecture]
        subjects = {
            "artifact": artifact["artifact_sha256"],
            "image": artifact["image_sha256"],
            "lineage": lineage_sha256,
            "materials": materials_sha256,
            "sbom": artifact["sbom_sha256"],
        }
        try:
            attestation = TRUST.verify_attestation(
                raw,
                policy=policy,
                role="builder",
                predicate_type=policy["predicate_types"]["builder"],
                subjects=subjects,
                today=today,
                component=lineage["component"],
                input_class=lineage["input_class"],
            )
            builder_authority = TRUST.policy_authority(
                policy,
                key_id=attestation["key_id"],
                role="builder",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
        except TRUST.TrustPolicyError as error:
            raise InputLineageError(str(error)) from error
        predicate = _mapping(attestation["predicate"], "builder predicate")
        _exact_keys(
            predicate,
            {
                "architecture",
                "lineage_sha256",
                "materials",
                "outputs",
                "policy_sha256",
                "schema",
            },
            "builder predicate",
        )
        outputs = _mapping(predicate["outputs"], "builder outputs")
        _exact_keys(
            outputs,
            {"artifact_sha256", "image_sha256", "sbom_sha256"},
            "builder outputs",
        )
        if (
            predicate["schema"] != BUILDER_PREDICATE_SCHEMA
            or predicate["policy_sha256"] != policy_sha256
            or predicate["lineage_sha256"] != lineage_sha256
            or predicate["architecture"] != architecture
            or predicate["materials"] != materials
            or outputs
            != {
                "artifact_sha256": artifact["artifact_sha256"],
                "image_sha256": artifact["image_sha256"],
                "sbom_sha256": artifact["sbom_sha256"],
            }
            or attestation["key_id"] == qualification_key
            or attestation["key_id"] in keys_by_architecture[architecture]
            or builder_authority["trust_domain"]
            == qualification_authority["trust_domain"]
            or builder_authority["operator_id"]
            == qualification_authority["operator_id"]
            or builder_authority["trust_domain"]
            in domains_by_architecture[architecture]
            or builder_authority["operator_id"]
            in operators_by_architecture[architecture]
        ):
            raise InputLineageError("builder predicate is not reproducible")
        keys_by_architecture[architecture].add(attestation["key_id"])
        domains_by_architecture[architecture].add(builder_authority["trust_domain"])
        operators_by_architecture[architecture].add(builder_authority["operator_id"])
        expiry.append(_date(attestation["expires_on"], "builder expiry"))
        parsed.append(attestation)
    if any(
        len(keys_by_architecture[architecture]) != required
        or len(domains_by_architecture[architecture]) != required
        or len(operators_by_architecture[architecture]) != required
        for architecture in ARCHITECTURES
    ):
        raise InputLineageError("independent builder quorum is incomplete")
    if lineage["input_class"] != "official-upstream" and any(
        not operators_by_architecture[architecture].intersection(
            policy["coffer"]["builder_operator_ids"]
        )
        for architecture in ARCHITECTURES
    ):
        raise InputLineageError(
            "Coffer-operated independent rebuild is missing"
        )
    parsed.sort(
        key=lambda item: (
            item["predicate"]["architecture"],
            item["key_id"],
        )
    )
    return parsed, expiry, set().union(*keys_by_architecture.values())


def _provenance(
    value: object,
    *,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    provenance = _mapping(value, "provenance")
    _exact_keys(
        provenance,
        {
            "materials",
            "predicate_type",
            "statement_sha256",
            "subjects",
        },
        "provenance",
    )
    products = _product_map(lineage)
    materials = _materials(lineage)
    if (
        provenance["predicate_type"] != "https://slsa.dev/provenance/v1"
        or provenance["subjects"] != products
        or provenance["materials"] != materials
    ):
        raise InputLineageError("provenance subjects or materials changed")
    return {
        "materials": materials,
        "predicate_type": "https://slsa.dev/provenance/v1",
        "statement_sha256": _digest(
            provenance["statement_sha256"],
            "provenance statement",
        ),
        "subjects": products,
    }


def _findings(
    value: object,
    *,
    lineage: Mapping[str, Any],
    today: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = _array(value, "scanner inventory")
    products = _product_map(lineage)
    expected_pairs = {
        (scanner, subject) for scanner in SCANNERS for subject in products
    }
    seen_pairs: set[tuple[str, str]] = set()
    parsed_inventory: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    finding_keys: set[tuple[str, str, str, str, str]] = set()
    for raw in inventory:
        scan = _mapping(raw, "scanner inventory entry")
        _exact_keys(
            scan,
            {
                "critical_high_complete",
                "database_sha256",
                "findings",
                "observed_on",
                "report_sha256",
                "scanner",
                "subject_name",
                "subject_sha256",
                "version",
            },
            "scanner inventory entry",
        )
        pair = (scan["scanner"], scan["subject_name"])
        if (
            pair not in expected_pairs
            or pair in seen_pairs
            or scan["subject_sha256"] != products.get(scan["subject_name"])
            or scan["critical_high_complete"] is not True
        ):
            raise InputLineageError("scanner inventory matrix is invalid")
        observed = _date(scan["observed_on"], "scanner observed_on")
        if observed > today or today - observed > timedelta(days=1):
            raise InputLineageError("scanner inventory is stale")
        seen_pairs.add(pair)
        database = _digest(
            scan["database_sha256"],
            "scanner database",
        )
        scanner_findings = _array(scan["findings"], "scanner findings")
        parsed_findings: list[dict[str, str]] = []
        previous: tuple[str, str, str] | None = None
        for finding_raw in scanner_findings:
            finding = _mapping(finding_raw, "scanner finding")
            _exact_keys(
                finding,
                {"id", "purl", "severity", "subject_sha256"},
                "scanner finding",
            )
            finding_id = finding["id"]
            severity = finding["severity"]
            purl = finding["purl"]
            if (
                not isinstance(finding_id, str)
                or CVE.fullmatch(finding_id) is None
                or severity not in {"critical", "high"}
                or not isinstance(purl, str)
                or not purl.startswith("pkg:")
                or len(purl) > 1024
                or finding["subject_sha256"] != products[pair[1]]
            ):
                raise InputLineageError("scanner finding is invalid")
            order = (finding_id, purl, severity)
            if previous is not None and order <= previous:
                raise InputLineageError("scanner findings are not sorted and unique")
            previous = order
            parsed_finding = {
                "database_sha256": database,
                "id": finding_id,
                "purl": purl,
                "scanner": pair[0],
                "severity": severity,
                "subject_name": pair[1],
                "subject_sha256": products[pair[1]],
            }
            key = (
                pair[0],
                database,
                finding_id,
                purl,
                products[pair[1]],
            )
            if key in finding_keys:
                raise InputLineageError("scanner finding is duplicated")
            finding_keys.add(key)
            all_findings.append(parsed_finding)
            parsed_findings.append(
                {
                    "id": finding_id,
                    "purl": purl,
                    "severity": severity,
                    "subject_sha256": products[pair[1]],
                }
            )
        parsed_inventory.append(
            {
                "critical_high_complete": True,
                "database_sha256": database,
                "findings": parsed_findings,
                "observed_on": observed.isoformat(),
                "report_sha256": _digest(
                    scan["report_sha256"],
                    "scanner report",
                ),
                "scanner": pair[0],
                "subject_name": pair[1],
                "subject_sha256": products[pair[1]],
                "version": _text(
                    scan["version"],
                    "scanner version",
                    maximum=128,
                ),
            }
        )
    if seen_pairs != expected_pairs:
        raise InputLineageError("scanner inventory matrix is incomplete")
    parsed_inventory.sort(key=lambda item: (item["scanner"], item["subject_name"]))
    all_findings.sort(
        key=lambda item: (
            item["scanner"],
            item["database_sha256"],
            item["id"],
            item["purl"],
            item["subject_sha256"],
        )
    )
    return parsed_inventory, all_findings


def _vex_attestations(
    value: object,
    *,
    findings: list[dict[str, Any]],
    lineage: Mapping[str, Any],
    lineage_sha256: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    qualification_key: str,
    evidence_key: str,
    builder_keys: set[str],
    support_end: date,
    today: date,
) -> tuple[list[dict[str, Any]], list[date], list[str]]:
    raw_vex = _array(value, "VEX attestations")
    expected = {_canonical_digest(finding): finding for finding in findings}
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    expiry: list[date] = []
    unresolved: list[str] = []
    try:
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        evidence_authority = TRUST.policy_authority(
            policy,
            key_id=evidence_key,
            role="input-evidence",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        builder_authorities = [
            TRUST.policy_authority(
                policy,
                key_id=key_id,
                role="builder",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
            for key_id in builder_keys
        ]
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    for raw in raw_vex:
        raw_map = _mapping(raw, "VEX attestation")
        outer_expires = _date(
            raw_map.get("expires_on"),
            "VEX attestation expires_on",
        )
        verification_date = min(today, outer_expires)
        subjects = _mapping(raw_map.get("subjects"), "VEX subjects")
        finding_digest = subjects.get("finding")
        finding = expected.get(finding_digest)
        if finding is None or finding_digest in seen:
            raise InputLineageError("VEX finding binding is invalid")
        expected_subjects = {
            "finding": finding_digest,
            "lineage": lineage_sha256,
            "product": finding["subject_sha256"],
        }
        try:
            attestation = TRUST.verify_attestation(
                raw,
                policy=policy,
                role="vex",
                predicate_type=policy["predicate_types"]["vex"],
                subjects=expected_subjects,
                today=verification_date,
                component=lineage["component"],
                input_class=lineage["input_class"],
            )
            vex_authority = TRUST.policy_authority(
                policy,
                key_id=attestation["key_id"],
                role="vex",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
        except TRUST.TrustPolicyError as error:
            raise InputLineageError(str(error)) from error
        predicate = _mapping(attestation["predicate"], "VEX predicate")
        _exact_keys(
            predicate,
            {
                "cve",
                "expires_on",
                "fixed",
                "issued_on",
                "lineage_sha256",
                "not_affected",
                "openvex_context",
                "policy_sha256",
                "product_sha256",
                "purl",
                "scanner",
                "scanner_database_sha256",
                "schema",
                "status",
                "under_investigation",
            },
            "VEX predicate",
        )
        issued = _date(predicate["issued_on"], "VEX issued_on")
        expires = _date(predicate["expires_on"], "VEX expires_on")
        outer_issued = _date(
            attestation["issued_on"],
            "VEX attestation issued_on",
        )
        vex_expired = expires < today or outer_expires < today
        if (
            predicate["schema"] != VEX_PREDICATE_SCHEMA
            or predicate["policy_sha256"] != policy_sha256
            or predicate["lineage_sha256"] != lineage_sha256
            or predicate["openvex_context"] != "https://openvex.dev/ns/v0.2.0"
            or predicate["cve"] != finding["id"]
            or predicate["purl"] != finding["purl"]
            or predicate["product_sha256"] != finding["subject_sha256"]
            or predicate["scanner"] != finding["scanner"]
            or predicate["scanner_database_sha256"] != finding["database_sha256"]
            or predicate["status"] not in VEX_STATUSES
            or issued > today
            or issued > expires
            or outer_issued < issued
            or attestation["key_id"] == qualification_key
            or vex_authority["trust_domain"] == qualification_authority["trust_domain"]
            or vex_authority["operator_id"] == qualification_authority["operator_id"]
            or vex_authority["trust_domain"] == evidence_authority["trust_domain"]
            or vex_authority["operator_id"] == evidence_authority["operator_id"]
            or any(
                vex_authority["trust_domain"] == authority["trust_domain"]
                or vex_authority["operator_id"] == authority["operator_id"]
                for authority in builder_authorities
            )
        ):
            raise InputLineageError("signed OpenVEX predicate is invalid")
        if predicate["status"] == "not_affected":
            details = _mapping(
                predicate["not_affected"],
                "not_affected evidence",
            )
            _exact_keys(
                details,
                {
                    "binary_reachability_sha256",
                    "justification",
                    "source_reachability_sha256",
                },
                "not_affected evidence",
            )
            if (
                predicate["fixed"] is not None
                or predicate["under_investigation"] is not None
                or details["justification"] not in {
                "component_not_present",
                "vulnerable_code_not_in_execute_path",
                "vulnerable_code_not_present",
                }
            ):
                raise InputLineageError("not_affected OpenVEX evidence is invalid")
            _digest(
                details["binary_reachability_sha256"],
                "binary reachability",
            )
            _digest(
                details["source_reachability_sha256"],
                "source reachability",
            )
        elif predicate["status"] == "fixed":
            details = _mapping(predicate["fixed"], "fixed evidence")
            _exact_keys(
                details,
                {
                    "fixed_artifact_sha256",
                    "post_fix_verification_sha256",
                    "remediation_revision",
                },
                "fixed evidence",
            )
            if (
                predicate["not_affected"] is not None
                or predicate["under_investigation"] is not None
                or details["fixed_artifact_sha256"] != finding["subject_sha256"]
            ):
                raise InputLineageError("fixed OpenVEX evidence is invalid")
            _digest(
                details["post_fix_verification_sha256"],
                "post-fix verification",
            )
            _revision(
                details["remediation_revision"],
                "remediation revision",
            )
        else:
            details = _mapping(
                predicate["under_investigation"],
                "under_investigation evidence",
            )
            _exact_keys(
                details,
                {"analysis_sha256", "due_on", "owner"},
                "under_investigation evidence",
            )
            due_on = _date(details["due_on"], "under_investigation due_on")
            if (
                predicate["fixed"] is not None
                or predicate["not_affected"] is not None
                or (support_end >= today and due_on > support_end)
            ):
                raise InputLineageError(
                    "under_investigation OpenVEX evidence is invalid"
                )
            _digest(
                details["analysis_sha256"],
                "under_investigation analysis",
            )
            _identifier(details["owner"], "under_investigation owner")
            unresolved.append(
                f"unresolved-finding:{finding['id']}:{finding['subject_name']}"
            )
            if due_on < today:
                unresolved.append(
                    f"overdue-investigation:{finding['id']}:"
                    f"{finding['subject_name']}"
                )
        if vex_expired:
            unresolved.append(
                f"expired-vex:{finding['id']}:{finding['subject_name']}"
            )
        seen.add(finding_digest)
        if not vex_expired:
            expiry.extend(
                (
                    expires,
                    outer_expires,
                )
            )
        parsed.append(attestation)
    for finding_digest, finding in expected.items():
        if finding_digest not in seen:
            unresolved.append(
                f"unresolved-finding:{finding['id']}:{finding['subject_name']}"
            )
    parsed.sort(key=lambda item: item["subjects"]["finding"])
    return parsed, expiry, sorted(unresolved)


def _lifecycle_attestation(
    value: object,
    *,
    lineage: Mapping[str, Any],
    lineage_sha256: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    qualification_key: str,
    evidence_key: str,
    builder_keys: set[str],
    today: date,
) -> tuple[dict[str, Any], list[date], date, list[str]]:
    raw_attestation = _mapping(value, "lifecycle observation attestation")
    raw_predicate = _mapping(
        raw_attestation.get("predicate"),
        "lifecycle observation predicate",
    )
    adapter_id = _identifier(
        raw_predicate.get("adapter_id"),
        "lifecycle observation adapter ID",
    )
    adapter = policy["lifecycle_observation_adapters"].get(adapter_id)
    if (
        adapter is None
        or lineage["component"] not in adapter["components"]
        or lineage["input_class"] not in adapter["input_classes"]
        or adapter["output_schema"]
        != LIFECYCLE_OBSERVATION_PREDICATE_SCHEMA
    ):
        raise InputLineageError(
            "lifecycle observation adapter is not allowlisted"
        )
    predicate = raw_predicate
    _exact_keys(
        predicate,
        {
            "adapter_id",
            "advisory_active",
            "lineage_sha256",
            "new_reachable_critical_high",
            "observed_on",
            "policy_sha256",
            "provider_support_ends_on",
            "replacement",
            "schema",
            "signer_active",
            "submission",
            "valid_until",
        },
        "lifecycle observation predicate",
    )
    observed = _date(
        predicate["observed_on"],
        "lifecycle observed_on",
    )
    valid_until = _date(
        predicate["valid_until"],
        "lifecycle valid_until",
    )
    adapter_starts = _date(
        adapter["valid_from"],
        "lifecycle adapter valid_from",
    )
    adapter_ends = _date(
        adapter["valid_until"],
        "lifecycle adapter valid_until",
    )
    provider_support = _date(
        predicate["provider_support_ends_on"],
        "lifecycle provider support_ends_on",
    )
    expected_provider_support = (
        lineage["provider"]["support_ends_on"]
        if lineage["provider"] is not None
        else lineage["upstream"]["support_ends_on"]
    )
    submission = _mapping(
        predicate["submission"],
        "lifecycle upstream submission",
    )
    _exact_keys(
        submission,
        {"items", "required"},
        "lifecycle upstream submission",
    )
    expected_submission = lineage["upstream_submission"]
    raw_submission_items = _array(
        submission["items"],
        "lifecycle upstream submission items",
    )
    if (
        submission["required"] is not expected_submission["required"]
        or len(raw_submission_items) != len(expected_submission["items"])
    ):
        raise InputLineageError("lifecycle upstream submission is invalid")
    observed_submission_items: list[dict[str, str]] = []
    submission_reason_codes: list[str] = []
    for index, (raw_item, baseline_item) in enumerate(
        zip(
            raw_submission_items,
            expected_submission["items"],
            strict=True,
        )
    ):
        item = _mapping(
            raw_item,
            f"lifecycle upstream submission item {index}",
        )
        _exact_keys(
            item,
            {"patch_id", "revision", "status", "url"},
            f"lifecycle upstream submission item {index}",
        )
        status = item["status"]
        if (
            status not in {"closed", "merged", "open", "rejected"}
            or item["patch_id"] != baseline_item["patch_id"]
            or item["revision"] != baseline_item["revision"]
            or item["url"] != baseline_item["url"]
            or (
                baseline_item["status"] == "merged"
                and status != "merged"
            )
        ):
            raise InputLineageError(
                "lifecycle upstream submission is invalid"
            )
        _upstream_artifact_url(
            baseline_item["url"],
            lineage["upstream"]["repository"],
            input_class=lineage["input_class"],
            status=status,
            label=f"lifecycle upstream submission item {index} URL",
        )
        observed_submission_items.append(
            {
                "patch_id": baseline_item["patch_id"],
                "revision": baseline_item["revision"],
                "status": status,
                "url": baseline_item["url"],
            }
        )
        if status in {"closed", "rejected"}:
            submission_reason_codes.append(
                f"upstream-submission-{status}:{baseline_item['patch_id']}"
            )
    observed_submission = {
        "items": observed_submission_items,
        "required": expected_submission["required"],
    }
    findings_raw = _array(
        predicate["new_reachable_critical_high"],
        "lifecycle new reachable findings",
    )
    findings: list[dict[str, str]] = []
    previous_finding: str | None = None
    for index, raw in enumerate(findings_raw):
        finding = _mapping(
            raw,
            f"lifecycle reachable finding {index}",
        )
        _exact_keys(
            finding,
            {"evidence_sha256", "id"},
            f"lifecycle reachable finding {index}",
        )
        finding_id = finding["id"]
        if (
            not isinstance(finding_id, str)
            or CVE.fullmatch(finding_id) is None
            or (previous_finding is not None and finding_id <= previous_finding)
        ):
            raise InputLineageError(
                "lifecycle reachable findings are invalid"
            )
        previous_finding = finding_id
        findings.append(
            {
                "evidence_sha256": _digest(
                    finding["evidence_sha256"],
                    f"lifecycle reachable finding {index} evidence",
                ),
                "id": finding_id,
            }
        )
    expected_replacement = (
        None
        if lineage["coffer_patch_policy"] is None
        else lineage["coffer_patch_policy"]["replacement"]
    )
    if (
        predicate["schema"] != LIFECYCLE_OBSERVATION_PREDICATE_SCHEMA
        or predicate["policy_sha256"] != policy_sha256
        or predicate["lineage_sha256"] != lineage_sha256
        or not isinstance(predicate["signer_active"], bool)
        or not isinstance(predicate["advisory_active"], bool)
        or provider_support > expected_provider_support
        or predicate["replacement"] != expected_replacement
        or observed > today
        or today - observed > timedelta(days=1)
        or observed < adapter_starts
        or valid_until < today
        or valid_until > adapter_ends
        or valid_until - observed > timedelta(days=7)
    ):
        raise InputLineageError("lifecycle observation is invalid")
    subjects = {
        "adapter": _canonical_digest(adapter),
        "lineage": lineage_sha256,
        "replacement": _canonical_digest(expected_replacement),
        "submission-baseline": _canonical_digest(expected_submission),
        "submission-observation": _canonical_digest(observed_submission),
    }
    try:
        attestation = TRUST.verify_attestation(
            raw_attestation,
            policy=policy,
            role="lifecycle-observer",
            predicate_type=policy["predicate_types"][
                "lifecycle_observation"
            ],
            subjects=dict(sorted(subjects.items())),
            today=today,
            component=lineage["component"],
            input_class=lineage["input_class"],
        )
        observer_authority = TRUST.policy_authority(
            policy,
            key_id=attestation["key_id"],
            role="lifecycle-observer",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        evidence_authority = TRUST.policy_authority(
            policy,
            key_id=evidence_key,
            role="input-evidence",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        builder_authorities = [
            TRUST.policy_authority(
                policy,
                key_id=key_id,
                role="builder",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
            for key_id in builder_keys
        ]
        owner_authority = (
            None
            if lineage["coffer_maintenance"] is None
            else TRUST.policy_authority(
                policy,
                key_id=lineage["coffer_maintenance"]["owner_key_id"],
                role="patch-owner",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    independent_authorities = [
        qualification_authority,
        evidence_authority,
        *builder_authorities,
        *([] if owner_authority is None else [owner_authority]),
    ]
    if (
        attestation["key_id"] != adapter["authority_key_id"]
        or _date(
            attestation["issued_on"],
            "lifecycle attestation issued_on",
        )
        < observed
        or _date(
            attestation["issued_on"],
            "lifecycle attestation issued_on",
        )
        < adapter_starts
        or _date(
            attestation["expires_on"],
            "lifecycle attestation expires_on",
        )
        > adapter_ends
        or valid_until
        > _date(
            attestation["expires_on"],
            "lifecycle attestation expires_on",
        )
        or attestation["key_id"]
        in {qualification_key, evidence_key, *builder_keys}
        or any(
            observer_authority["operator_id"] == authority["operator_id"]
            or observer_authority["trust_domain"]
            == authority["trust_domain"]
            for authority in independent_authorities
        )
    ):
        raise InputLineageError(
            "lifecycle observation is not independently trusted"
        )
    required_support_end = min(
        lineage["support"]["declared_ends_on"],
        lineage["support"]["coffer_release_ends_on"],
        (
            _date(
                lineage["coffer_patch_policy"]["retire_on"],
                "Coffer patch retire_on",
            )
            if lineage["coffer_patch_policy"] is not None
            else lineage["support"]["declared_ends_on"]
        ),
    )
    effective_end = min(required_support_end, provider_support)
    reason_codes: list[str] = []
    reason_codes.extend(submission_reason_codes)
    if predicate["signer_active"] is False:
        reason_codes.append("retirement-signer-revoked")
    if predicate["advisory_active"] is False:
        reason_codes.append("retirement-advisory-withdrawn")
    if provider_support < required_support_end:
        reason_codes.append("provider-support-shortened")
    reason_codes.extend(
        f"retirement-new-reachable:{finding['id']}"
        for finding in findings
    )
    if effective_end < today:
        reason_codes.append(
            "replacement-grace-expired"
            if expected_replacement is not None
            else "support-window-expired"
        )
    normalized_predicate = {
        "adapter_id": adapter_id,
        "advisory_active": predicate["advisory_active"],
        "lineage_sha256": lineage_sha256,
        "new_reachable_critical_high": findings,
        "observed_on": observed.isoformat(),
        "policy_sha256": policy_sha256,
        "provider_support_ends_on": provider_support.isoformat(),
        "replacement": expected_replacement,
        "schema": LIFECYCLE_OBSERVATION_PREDICATE_SCHEMA,
        "signer_active": predicate["signer_active"],
        "submission": observed_submission,
        "valid_until": valid_until.isoformat(),
    }
    normalized = dict(attestation)
    normalized["predicate"] = normalized_predicate
    if _canonical_digest(normalized) != _canonical_digest(raw_attestation):
        raise InputLineageError(
            "normalized lifecycle observation binding changed"
        )
    return (
        normalized,
        [
            valid_until,
            _date(attestation["expires_on"], "lifecycle attestation expiry"),
            adapter_ends,
        ],
        effective_end,
        sorted(reason_codes),
    )


def _patch_review(
    value: object,
    *,
    lineage: Mapping[str, Any],
    lineage_sha256: str,
    policy: Mapping[str, Any],
    policy_sha256: str,
    qualification_key: str,
    builder_keys: set[str],
    today: date,
) -> dict[str, Any] | None:
    if lineage["input_class"] != "coffer-minimal-patch":
        if value is not None:
            raise InputLineageError("patch review is not allowed")
        return None
    maintenance = lineage["coffer_maintenance"]
    patch_series = _canonical_digest(
        [
            {
                "blocker_id": patch["blocker_id"],
                "id": patch["id"],
                "sha256": patch["sha256"],
            }
            for patch in lineage["patches"]
        ]
    )
    subjects = {
        "changed-tree": maintenance["changed_tree_sha256"],
        "lineage": lineage_sha256,
        "patch-series": patch_series,
    }
    try:
        attestation = TRUST.verify_attestation(
            value,
            policy=policy,
            role="security-review",
            predicate_type=("https://coffer.invalid/attestations/patch-review/v2"),
            subjects=subjects,
            today=today,
            component=lineage["component"],
            input_class=lineage["input_class"],
        )
        reviewer_authority = TRUST.policy_authority(
            policy,
            key_id=attestation["key_id"],
            role="security-review",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        qualification_authority = TRUST.policy_authority(
            policy,
            key_id=qualification_key,
            role="input-qualification",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
        builder_authorities = [
            TRUST.policy_authority(
                policy,
                key_id=key_id,
                role="builder",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
            for key_id in builder_keys
        ]
        owner_authority = TRUST.policy_authority(
            policy,
            key_id=maintenance["owner_key_id"],
            role="patch-owner",
            component=lineage["component"],
            input_class=lineage["input_class"],
            today=today,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    predicate = _mapping(attestation["predicate"], "patch review predicate")
    _exact_keys(
        predicate,
        {
            "lineage_sha256",
            "owner_key_id",
            "patches",
            "policy_sha256",
            "reviewed_on",
            "schema",
            "scope_checks",
        },
        "patch review predicate",
    )
    reviewed_on = _date(predicate["reviewed_on"], "patch reviewed_on")
    expected_patches = [
        {
            "blocker_id": patch["blocker_id"],
            "changed_paths_sha256": patch["changed_paths_sha256"],
            "id": patch["id"],
            "sha256": patch["sha256"],
        }
        for patch in lineage["patches"]
    ]
    if (
        predicate["schema"] != PATCH_REVIEW_PREDICATE_SCHEMA
        or predicate["policy_sha256"] != policy_sha256
        or predicate["lineage_sha256"] != lineage_sha256
        or predicate["owner_key_id"] != maintenance["owner_key_id"]
        or predicate["patches"] != expected_patches
        or predicate["scope_checks"] != maintenance["scope_checks"]
        or reviewed_on > today
        or today - reviewed_on > timedelta(days=7)
        or _date(
            attestation["issued_on"],
            "patch review attestation issued_on",
        )
        < reviewed_on
        or attestation["key_id"] == qualification_key
        or attestation["key_id"] in builder_keys
        or attestation["key_id"] == maintenance["owner_key_id"]
        or reviewer_authority["trust_domain"]
        == owner_authority["trust_domain"]
        or reviewer_authority["operator_id"]
        == owner_authority["operator_id"]
        or reviewer_authority["trust_domain"] == qualification_authority["trust_domain"]
        or reviewer_authority["operator_id"] == qualification_authority["operator_id"]
        or any(
            reviewer_authority["trust_domain"] == authority["trust_domain"]
            or reviewer_authority["operator_id"] == authority["operator_id"]
            for authority in builder_authorities
        )
    ):
        raise InputLineageError("independent patch review is invalid")
    return attestation


def _derive(
    *,
    manifest_value: object,
    qualification_value: object,
    policy: Mapping[str, Any],
    policy_sha256: str,
    today: date,
) -> dict[str, Any]:
    lineage = validate_manifest(
        manifest_value,
        policy=policy,
        today=today,
    )
    lineage_sha256 = _canonical_digest(manifest_value)
    subjects = {"lineage": lineage_sha256, **_subject_map(lineage)}
    raw_qualification = _mapping(
        qualification_value,
        "qualification attestation",
    )
    try:
        qualification = TRUST.verify_attestation(
            raw_qualification,
            policy=policy,
            role="input-qualification",
            predicate_type=policy["predicate_types"]["input_qualification"],
            subjects=subjects,
            today=today,
            component=lineage["component"],
            input_class=lineage["input_class"],
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    predicate = _mapping(
        qualification["predicate"],
        "qualification predicate",
    )
    _exact_keys(
        predicate,
        {
            "builders",
            "component",
            "evidence_attestation",
            "lifecycle_attestation",
            "lineage_sha256",
            "patch_review",
            "policy_sha256",
            "provenance",
            "release",
            "schema",
            "vex",
        },
        "qualification predicate",
    )
    if (
        predicate["schema"] != QUALIFICATION_PREDICATE_SCHEMA
        or predicate["policy_sha256"] != policy_sha256
        or predicate["lineage_sha256"] != lineage_sha256
        or predicate["component"] != lineage["component"]
    ):
        raise InputLineageError("qualification predicate identity is invalid")

    provenance = _provenance(predicate["provenance"], lineage=lineage)
    release, release_expiry = _release_verification(
        predicate["release"],
        lineage=lineage,
        provenance=provenance,
        policy=policy,
        qualification_key=qualification["key_id"],
        today=today,
    )
    (
        evidence_attestation,
        evidence_expiry,
        parsed_evidence,
        _inventory,
        findings,
        failed_checks,
    ) = _input_evidence(
        predicate["evidence_attestation"],
        lineage=lineage,
        lineage_sha256=lineage_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        qualification_key=qualification["key_id"],
        today=today,
    )
    builders, builder_expiry, builder_keys = _builder_attestations(
        predicate["builders"],
        lineage=lineage,
        lineage_sha256=lineage_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        qualification_key=qualification["key_id"],
        today=today,
    )
    (
        lifecycle_attestation,
        lifecycle_expiry,
        effective_end,
        lifecycle_reason_codes,
    ) = _lifecycle_attestation(
        predicate["lifecycle_attestation"],
        lineage=lineage,
        lineage_sha256=lineage_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        qualification_key=qualification["key_id"],
        evidence_key=evidence_attestation["key_id"],
        builder_keys=builder_keys,
        today=today,
    )
    vex, vex_expiry, unresolved_findings = _vex_attestations(
        predicate["vex"],
        findings=findings,
        lineage=lineage,
        lineage_sha256=lineage_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        qualification_key=qualification["key_id"],
        evidence_key=evidence_attestation["key_id"],
        builder_keys=builder_keys,
        support_end=effective_end,
        today=today,
    )
    patch_review = _patch_review(
        predicate["patch_review"],
        lineage=lineage,
        lineage_sha256=lineage_sha256,
        policy=policy,
        policy_sha256=policy_sha256,
        qualification_key=qualification["key_id"],
        builder_keys=builder_keys,
        today=today,
    )
    if patch_review is not None:
        try:
            lifecycle_authority = TRUST.policy_authority(
                policy,
                key_id=lifecycle_attestation["key_id"],
                role="lifecycle-observer",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
            review_authority = TRUST.policy_authority(
                policy,
                key_id=patch_review["key_id"],
                role="security-review",
                component=lineage["component"],
                input_class=lineage["input_class"],
                today=today,
            )
        except TRUST.TrustPolicyError as error:
            raise InputLineageError(str(error)) from error
        if (
            lifecycle_attestation["key_id"] == patch_review["key_id"]
            or lifecycle_authority["operator_id"]
            == review_authority["operator_id"]
            or lifecycle_authority["trust_domain"]
            == review_authority["trust_domain"]
        ):
            raise InputLineageError(
                "lifecycle observer and patch reviewer are not independent"
            )
    validity = [
        _date(qualification["expires_on"], "qualification expiry"),
        _date(policy["valid_until"], "trust policy expiry"),
        *evidence_expiry,
        *lifecycle_expiry,
        *release_expiry,
        *builder_expiry,
        *vex_expiry,
    ]
    if patch_review is not None:
        validity.append(_date(patch_review["expires_on"], "patch review expiry"))
    if effective_end >= today:
        validity.append(effective_end)
    valid_until = min(validity)
    if valid_until < today:
        raise InputLineageError("input qualification validity has expired")
    production = (
        policy["environment"] == "production" and lineage["fixture_only"] is False
    )
    production_ready = (
        production
        and not failed_checks
        and not unresolved_findings
        and not lifecycle_reason_codes
    )
    reason_codes = [
        *[f"input-check-failed:{name}" for name in failed_checks],
        *lifecycle_reason_codes,
        *unresolved_findings,
    ]
    normalized_predicate = {
        "builders": builders,
        "component": lineage["component"],
        "evidence_attestation": evidence_attestation,
        "lifecycle_attestation": lifecycle_attestation,
        "lineage_sha256": lineage_sha256,
        "patch_review": patch_review,
        "policy_sha256": policy_sha256,
        "provenance": provenance,
        "release": release,
        "schema": QUALIFICATION_PREDICATE_SCHEMA,
        "vex": vex,
    }
    normalized_qualification = dict(qualification)
    normalized_qualification["predicate"] = normalized_predicate
    return {
        "bundle": {
            "lineage": dict(_mapping(manifest_value, "lineage manifest")),
            "qualification": normalized_qualification,
        },
        "derived": {
            "component": lineage["component"],
            "evidence_attestation_sha256": _canonical_digest(evidence_attestation),
            "evidence_sha256": _canonical_digest(parsed_evidence),
            "effective_support_ends_on": effective_end.isoformat(),
            "input_class": lineage["input_class"],
            "lineage_sha256": lineage_sha256,
            "patch_count": len(lineage["patches"]),
            "policy_sha256": policy_sha256,
            "production_input": production_ready,
            "qualification_sha256": _canonical_digest(normalized_qualification),
            "reason_codes": reason_codes,
            "status": (
                ("blocked" if production else "synthetic-blocked")
                if reason_codes
                else ("qualified" if production else "synthetic-qualified")
            ),
            "valid_until": valid_until.isoformat(),
            "vex_count": len(vex),
        },
        "schema": RESULT_SCHEMA,
        "source": source_hashes(),
    }


def _compile_result_with_policy(
    *,
    manifest: Any,
    qualification: Any,
    policy_path: Path,
    today: date | None = None,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    try:
        manifest_value = TRUST.verify_loaded_document(
            manifest,
            "lineage manifest",
            maximum_bytes=LINEAGE_MANIFEST_MAX_BYTES,
        )
        qualification_value = TRUST.verify_loaded_document(
            qualification,
            "input qualification",
            maximum_bytes=QUALIFICATION_MAX_BYTES,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    _require_serialized_size(
        manifest_value,
        maximum_bytes=LINEAGE_MANIFEST_MAX_BYTES,
        label="lineage manifest",
    )
    _require_serialized_size(
        qualification_value,
        maximum_bytes=QUALIFICATION_MAX_BYTES,
        label="input qualification",
    )
    current = datetime.now(tz=UTC).date() if today is None else today
    try:
        policy, policy_sha256 = TRUST.load_policy(
            policy_path,
            today=current,
            allow_synthetic=allow_synthetic_policy,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    result = _derive(
        manifest_value=manifest_value,
        qualification_value=qualification_value,
        policy=policy,
        policy_sha256=policy_sha256,
        today=current,
    )
    _require_serialized_size(
        result,
        maximum_bytes=INPUT_RESULT_MAX_BYTES,
        label="input lineage result",
    )
    return result


def compile_result(
    *,
    manifest: Any,
    qualification: Any,
) -> dict[str, Any]:
    return _compile_result_with_policy(
        manifest=manifest,
        qualification=qualification,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        allow_synthetic_policy=False,
    )


def compile_test_result(
    *,
    manifest: Any,
    qualification: Any,
    policy_path: Path,
    today: date,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    """Exercise an injected policy in tests; never consume this in a ledger."""
    return _compile_result_with_policy(
        manifest=manifest,
        qualification=qualification,
        policy_path=policy_path,
        today=today,
        allow_synthetic_policy=allow_synthetic_policy,
    )


def _validate_result_with_policy(
    value: object,
    *,
    policy_path: Path,
    today: date | None = None,
    allow_synthetic_policy: bool,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    _require_serialized_size(
        value,
        maximum_bytes=INPUT_RESULT_MAX_BYTES,
        label="input lineage result",
    )
    result = dict(_mapping(value, "input lineage result"))
    _exact_keys(
        result,
        {"bundle", "derived", "schema", "source"},
        "input lineage result",
    )
    if result["schema"] != RESULT_SCHEMA or result["source"] != source_hashes():
        raise InputLineageError("input lineage result source is invalid")
    bundle = _mapping(result["bundle"], "input lineage bundle")
    _exact_keys(
        bundle,
        {"lineage", "qualification"},
        "input lineage bundle",
    )
    _require_serialized_size(
        bundle["lineage"],
        maximum_bytes=LINEAGE_MANIFEST_MAX_BYTES,
        label="lineage manifest",
    )
    _require_serialized_size(
        bundle["qualification"],
        maximum_bytes=QUALIFICATION_MAX_BYTES,
        label="input qualification",
    )
    try:
        policy, policy_sha256 = TRUST.load_policy(
            policy_path,
            today=current,
            allow_synthetic=allow_synthetic_policy,
        )
    except TRUST.TrustPolicyError as error:
        raise InputLineageError(str(error)) from error
    expected = _derive(
        manifest_value=bundle["lineage"],
        qualification_value=bundle["qualification"],
        policy=policy,
        policy_sha256=policy_sha256,
        today=current,
    )
    if result != expected:
        raise InputLineageError("input lineage result was not derived")
    if not allow_synthetic_policy and expected["derived"]["status"] not in {
        "blocked",
        "qualified",
    }:
        raise InputLineageError("input lineage result is not production")
    return result


def validate_final_result(
    value: object,
) -> dict[str, Any]:
    return _validate_result_with_policy(
        value,
        policy_path=PRODUCTION_POLICY_SOURCE,
        today=None,
        allow_synthetic_policy=False,
    )


def validate_test_result(
    value: object,
    *,
    policy_path: Path,
    today: date,
    allow_synthetic_policy: bool = False,
) -> dict[str, Any]:
    """Validate an injected-policy result in tests; never use in a ledger."""
    return _validate_result_with_policy(
        value,
        policy_path=policy_path,
        today=today,
        allow_synthetic_policy=allow_synthetic_policy,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a signed, policy-bound official, vendor, or Coffer "
            "dependency lineage."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        manifest = TRUST.load_private_json(
            arguments.manifest,
            "lineage manifest",
            maximum_bytes=LINEAGE_MANIFEST_MAX_BYTES,
        )
        qualification = TRUST.load_private_json(
            arguments.qualification,
            "input qualification",
            maximum_bytes=QUALIFICATION_MAX_BYTES,
        )
        result = compile_result(
            manifest=manifest,
            qualification=qualification,
        )
        TRUST.write_owner_only(
            arguments.output,
            result,
            maximum_bytes=INPUT_RESULT_MAX_BYTES,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (InputLineageError, TRUST.TrustPolicyError) as error:
        print(f"input lineage error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
