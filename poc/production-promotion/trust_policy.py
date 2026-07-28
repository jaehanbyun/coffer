from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DIRECTORY = Path(__file__).resolve().parent
PRODUCTION_POLICY_SOURCE = DIRECTORY / "trust-policy-v2.json"

POLICY_SCHEMA = "coffer.production-trust-policy/v2"
ATTESTATION_SCHEMA = "coffer.signed-attestation/v2"
ENVIRONMENTS = ("production", "synthetic")
ROLES = (
    "builder",
    "input-evidence",
    "input-qualification",
    "lifecycle-observer",
    "migration-checkpoint",
    "patch-owner",
    "release-verification",
    "rollback-authorization",
    "scope-evidence",
    "scope-qualification",
    "security-review",
    "storage-provider",
    "vex",
    "writer-fence",
)
COMPONENTS = ("ceph", "distribution", "oslo_messaging")
INPUT_CLASSES = (
    "approved-vendor-backport",
    "coffer-minimal-patch",
    "official-upstream",
)
SCOPES = (
    "horizon",
    "referrers",
    "registry_core",
    "rgw_barbican_kms",
    "skyline",
    "storage_backend",
)
OWNER_ONLY_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
OWNER_ONLY_HARD_MAX_BYTES = OWNER_ONLY_DEFAULT_MAX_BYTES
PREDICATE_KEYS = (
    "builder",
    "input_evidence",
    "input_qualification",
    "lifecycle_observation",
    "migration_checkpoint",
    "release_verification",
    "rollback_authorization",
    "scope_evidence",
    "scope_qualification",
    "storage_provider",
    "vex",
    "writer_fence",
)

SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


class TrustPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedDocument:
    value: dict[str, Any]
    raw_sha256: str
    canonical_sha256: str
    raw_bytes: bytes


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise TrustPolicyError("document is not canonical JSON") from error


def sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def strict_json_loads(payload: bytes | bytearray) -> object:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TrustPolicyError("JSON object contains duplicate keys")
            result[key] = value
        return result

    try:
        return json.loads(
            payload,
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                TrustPolicyError(f"JSON constant {value} is not allowed")
            ),
        )
    except TrustPolicyError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise TrustPolicyError("document is not valid JSON") from error


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise TrustPolicyError(f"unable to hash {path}") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrustPolicyError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TrustPolicyError(f"{label} must be a JSON array")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise TrustPolicyError(f"{label} fields are invalid")


def digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise TrustPolicyError(f"{label} is invalid")
    return value


def identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise TrustPolicyError(f"{label} is invalid")
    return value


def text(value: object, label: str, *, maximum: int = 2048) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 0x20 for character in value)
    ):
        raise TrustPolicyError(f"{label} is invalid")
    return value


def parse_date(value: object, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise TrustPolicyError(f"{label} is invalid") from error


def _string_set(
    value: object,
    *,
    allowed: Sequence[str],
    label: str,
) -> list[str]:
    items = _array(value, label)
    if items != sorted(set(items)) or any(item not in allowed for item in items):
        raise TrustPolicyError(f"{label} is invalid")
    return list(items)


def _public_key(value: object, label: str) -> str:
    encoded = text(value, label, maximum=128)
    try:
        raw = base64.b64decode(encoded, validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, binascii.Error) as error:
        raise TrustPolicyError(f"{label} is invalid") from error
    if len(raw) != 32:
        raise TrustPolicyError(f"{label} is invalid")
    return encoded


def _https_url(value: object, label: str) -> str:
    url = text(value, label)
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise TrustPolicyError(f"{label} is invalid") from error
    segments = parsed.path.split("/")
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
        or any(segment in {".", ".."} for segment in segments)
        or "//" in parsed.path
    ):
        raise TrustPolicyError(f"{label} is invalid")
    return url


def validate_policy(value: object, *, today: date | None = None) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    policy = _mapping(value, "trust policy")
    _exact_keys(
        policy,
        {
            "attestation_max_age_days",
            "authorities",
            "blockers",
            "checkpoint_revocations",
            "coffer",
            "components",
            "environment",
            "input_evidence_adapters",
            "lifecycle_observation_adapters",
            "policy_id",
            "predicate_types",
            "release_verification_adapters",
            "schema",
            "scope_evidence_adapters",
            "storage_backends",
            "valid_from",
            "valid_until",
            "vendors",
            "writer_fence_adapters",
        },
        "trust policy",
    )
    starts = parse_date(policy["valid_from"], "trust policy valid_from")
    ends = parse_date(policy["valid_until"], "trust policy valid_until")
    maximum_age = policy["attestation_max_age_days"]
    if (
        policy["schema"] != POLICY_SCHEMA
        or policy["environment"] not in ENVIRONMENTS
        or not isinstance(maximum_age, int)
        or isinstance(maximum_age, bool)
        or not 1 <= maximum_age <= 31
        or starts > current
        or ends < current
        or starts > ends
    ):
        raise TrustPolicyError("trust policy is not currently valid")

    predicate_types = _mapping(
        policy["predicate_types"],
        "trust policy predicate types",
    )
    _exact_keys(
        predicate_types,
        set(PREDICATE_KEYS),
        "trust policy predicate types",
    )
    parsed_predicates = {
        name: text(predicate_types[name], f"{name} predicate type")
        for name in PREDICATE_KEYS
    }

    checkpoint_revocations = _array(
        policy["checkpoint_revocations"],
        "checkpoint revocations",
    )
    parsed_checkpoint_revocations: list[dict[str, Any]] = []
    revoked_checkpoint_keys: set[str] = set()
    for index, raw in enumerate(checkpoint_revocations):
        revocation = _mapping(raw, f"checkpoint revocation {index}")
        _exact_keys(
            revocation,
            {"compromised_since", "key_id", "reason", "revoked_on"},
            f"checkpoint revocation {index}",
        )
        key_id = identifier(
            revocation["key_id"],
            f"checkpoint revocation {index} key_id",
        )
        if key_id in revoked_checkpoint_keys:
            raise TrustPolicyError("checkpoint revocation keys are not unique")
        revoked_checkpoint_keys.add(key_id)
        revoked_on = parse_date(
            revocation["revoked_on"],
            f"checkpoint revocation {index} revoked_on",
        )
        compromised_since = (
            None
            if revocation["compromised_since"] is None
            else parse_date(
                revocation["compromised_since"],
                f"checkpoint revocation {index} compromised_since",
            )
        )
        if compromised_since is not None and compromised_since > revoked_on:
            raise TrustPolicyError(
                f"checkpoint revocation {index} dates are invalid"
            )
        parsed_checkpoint_revocations.append(
            {
                "compromised_since": (
                    None
                    if compromised_since is None
                    else compromised_since.isoformat()
                ),
                "key_id": key_id,
                "reason": text(
                    revocation["reason"],
                    f"checkpoint revocation {index} reason",
                    maximum=512,
                ),
                "revoked_on": revoked_on.isoformat(),
            }
        )
    if parsed_checkpoint_revocations != sorted(
        parsed_checkpoint_revocations,
        key=lambda item: item["key_id"],
    ):
        raise TrustPolicyError("checkpoint revocations are not sorted")

    components = _mapping(policy["components"], "trust policy components")
    _exact_keys(components, set(COMPONENTS), "trust policy components")
    parsed_components: dict[str, dict[str, Any]] = {}
    for name in COMPONENTS:
        component = _mapping(components[name], f"{name} policy")
        _exact_keys(
            component,
            {
                "accepted_patch_bases",
                "latest_supported_patch_base",
                "official_releases",
                "release_signing_identities",
                "tag_pattern",
                "upstream_repositories",
            },
            f"{name} policy",
        )
        repositories = _array(
            component["upstream_repositories"],
            f"{name} repositories",
        )
        identities = _array(
            component["release_signing_identities"],
            f"{name} release identities",
        )
        if (
            repositories != sorted(set(repositories))
            or identities != sorted(set(identities))
            or not repositories
        ):
            raise TrustPolicyError(f"{name} policy allowlist is invalid")
        tag_pattern = text(
            component["tag_pattern"],
            f"{name} tag pattern",
            maximum=512,
        )
        try:
            compiled_tag = re.compile(tag_pattern)
        except re.error as error:
            raise TrustPolicyError(f"{name} tag pattern is invalid") from error
        release_catalogs: dict[str, dict[str, dict[str, str]]] = {}
        for catalog_name in ("accepted_patch_bases", "official_releases"):
            catalog = _mapping(
                component[catalog_name],
                f"{name} {catalog_name}",
            )
            parsed_catalog: dict[str, dict[str, str]] = {}
            for release_name in sorted(catalog):
                release = _mapping(
                    catalog[release_name],
                    f"{name} {catalog_name} {release_name}",
                )
                _exact_keys(
                    release,
                    {"revision", "source_sha256", "support_ends_on"},
                    f"{name} {catalog_name} {release_name}",
                )
                if compiled_tag.fullmatch(release_name) is None:
                    raise TrustPolicyError(f"{name} {catalog_name} tag is invalid")
                parsed_catalog[release_name] = {
                    "revision": text(
                        release["revision"],
                        f"{name} {catalog_name} revision",
                        maximum=40,
                    ),
                    "source_sha256": digest(
                        release["source_sha256"],
                        f"{name} {catalog_name} source",
                    ),
                    "support_ends_on": parse_date(
                        release["support_ends_on"],
                        f"{name} {catalog_name} support_ends_on",
                    ).isoformat(),
                }
                if REVISION.fullmatch(parsed_catalog[release_name]["revision"]) is None:
                    raise TrustPolicyError(f"{name} {catalog_name} revision is invalid")
            release_catalogs[catalog_name] = parsed_catalog
        latest_patch_base = component["latest_supported_patch_base"]
        if latest_patch_base is not None:
            latest_patch_base = text(
                latest_patch_base,
                f"{name} latest supported patch base",
                maximum=128,
            )
        if (
            latest_patch_base is None
            and release_catalogs["accepted_patch_bases"]
        ) or (
            latest_patch_base is not None
            and latest_patch_base not in release_catalogs["accepted_patch_bases"]
        ):
            raise TrustPolicyError(
                f"{name} latest supported patch base is invalid"
            )
        parsed_components[name] = {
            "accepted_patch_bases": release_catalogs["accepted_patch_bases"],
            "latest_supported_patch_base": latest_patch_base,
            "official_releases": release_catalogs["official_releases"],
            "release_signing_identities": [
                text(item, f"{name} release identity") for item in identities
            ],
            "tag_pattern": tag_pattern,
            "upstream_repositories": [
                text(item, f"{name} repository") for item in repositories
            ],
        }

    authorities = _array(policy["authorities"], "trust policy authorities")
    parsed_authorities: list[dict[str, Any]] = []
    authority_ids: set[str] = set()
    authority_public_keys: set[str] = set()
    for index, raw in enumerate(authorities):
        authority = _mapping(raw, f"authority {index}")
        _exact_keys(
            authority,
            {
                "components",
                "input_classes",
                "key_id",
                "not_after",
                "not_before",
                "operator_id",
                "public_key",
                "revoked_on",
                "roles",
                "scopes",
                "trust_domain",
            },
            f"authority {index}",
        )
        key_id = identifier(authority["key_id"], f"authority {index} key_id")
        if key_id in authority_ids:
            raise TrustPolicyError("authority key IDs are not unique")
        authority_ids.add(key_id)
        not_before = parse_date(
            authority["not_before"],
            f"authority {index} not_before",
        )
        not_after = parse_date(
            authority["not_after"],
            f"authority {index} not_after",
        )
        revoked_on = (
            None
            if authority["revoked_on"] is None
            else parse_date(
                authority["revoked_on"],
                f"authority {index} revoked_on",
            )
        )
        if not_before > not_after or (
            revoked_on is not None and revoked_on < not_before
        ):
            raise TrustPolicyError(f"authority {index} dates are invalid")
        public_key = _public_key(
            authority["public_key"],
            f"authority {index} public key",
        )
        if public_key in authority_public_keys:
            raise TrustPolicyError("authority public keys are not unique")
        authority_public_keys.add(public_key)
        roles = _string_set(
            authority["roles"],
            allowed=ROLES,
            label=f"authority {index} roles",
        )
        if len(roles) != 1:
            raise TrustPolicyError("authority keys must have exactly one role")
        parsed_authorities.append(
            {
                "components": _string_set(
                    authority["components"],
                    allowed=COMPONENTS,
                    label=f"authority {index} components",
                ),
                "input_classes": _string_set(
                    authority["input_classes"],
                    allowed=INPUT_CLASSES,
                    label=f"authority {index} input classes",
                ),
                "key_id": key_id,
                "not_after": not_after.isoformat(),
                "not_before": not_before.isoformat(),
                "operator_id": identifier(
                    authority["operator_id"],
                    f"authority {index} operator_id",
                ),
                "public_key": public_key,
                "revoked_on": (None if revoked_on is None else revoked_on.isoformat()),
                "roles": roles,
                "scopes": _string_set(
                    authority["scopes"],
                    allowed=SCOPES,
                    label=f"authority {index} scopes",
                ),
                "trust_domain": identifier(
                    authority["trust_domain"],
                    f"authority {index} trust_domain",
                ),
            }
        )

    authority_by_id = {
        authority["key_id"]: authority for authority in parsed_authorities
    }

    release_adapters = _mapping(
        policy["release_verification_adapters"],
        "release verification adapters",
    )
    parsed_release_adapters: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(release_adapters):
        adapter_id = identifier(raw_id, "release verification adapter ID")
        adapter = _mapping(
            release_adapters[raw_id],
            f"release verification adapter {adapter_id}",
        )
        _exact_keys(
            adapter,
            {
                "authority_key_id",
                "components",
                "input_classes",
                "name",
                "output_schema",
                "repository",
                "revision",
                "source_sha256",
                "trust_root_sha256",
                "valid_from",
                "valid_until",
            },
            f"release verification adapter {adapter_id}",
        )
        adapter_starts = parse_date(
            adapter["valid_from"],
            f"release verification adapter {adapter_id} valid_from",
        )
        adapter_ends = parse_date(
            adapter["valid_until"],
            f"release verification adapter {adapter_id} valid_until",
        )
        authority_key_id = identifier(
            adapter["authority_key_id"],
            f"release verification adapter {adapter_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        revision = text(
            adapter["revision"],
            f"release verification adapter {adapter_id} revision",
            maximum=40,
        )
        if (
            authority is None
            or authority["roles"] != ["release-verification"]
            or REVISION.fullmatch(revision) is None
            or adapter_starts > current
            or adapter_ends < current
            or adapter_starts > adapter_ends
        ):
            raise TrustPolicyError(
                f"release verification adapter {adapter_id} is invalid"
            )
        parsed_release_adapters[adapter_id] = {
            "authority_key_id": authority_key_id,
            "components": _string_set(
                adapter["components"],
                allowed=COMPONENTS,
                label=f"release verification adapter {adapter_id} components",
            ),
            "input_classes": _string_set(
                adapter["input_classes"],
                allowed=INPUT_CLASSES,
                label=f"release verification adapter {adapter_id} input classes",
            ),
            "name": identifier(
                adapter["name"],
                f"release verification adapter {adapter_id} name",
            ),
            "output_schema": text(
                adapter["output_schema"],
                f"release verification adapter {adapter_id} output schema",
            ),
            "repository": _https_url(
                adapter["repository"],
                f"release verification adapter {adapter_id} repository",
            ),
            "revision": revision,
            "source_sha256": digest(
                adapter["source_sha256"],
                f"release verification adapter {adapter_id} source",
            ),
            "trust_root_sha256": digest(
                adapter["trust_root_sha256"],
                f"release verification adapter {adapter_id} trust root",
            ),
            "valid_from": adapter_starts.isoformat(),
            "valid_until": adapter_ends.isoformat(),
        }

    input_adapters = _mapping(
        policy["input_evidence_adapters"],
        "input evidence adapters",
    )
    parsed_input_adapters: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(input_adapters):
        adapter_id = identifier(raw_id, "input evidence adapter ID")
        adapter = _mapping(
            input_adapters[raw_id],
            f"input evidence adapter {adapter_id}",
        )
        _exact_keys(
            adapter,
            {
                "authority_key_id",
                "built_artifact_sha256",
                "components",
                "input_classes",
                "output_schema",
                "repository",
                "revision",
                "source_sha256",
                "valid_from",
                "valid_until",
            },
            f"input evidence adapter {adapter_id}",
        )
        adapter_starts = parse_date(
            adapter["valid_from"],
            f"input evidence adapter {adapter_id} valid_from",
        )
        adapter_ends = parse_date(
            adapter["valid_until"],
            f"input evidence adapter {adapter_id} valid_until",
        )
        authority_key_id = identifier(
            adapter["authority_key_id"],
            f"input evidence adapter {adapter_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        revision = text(
            adapter["revision"],
            f"input evidence adapter {adapter_id} revision",
            maximum=40,
        )
        if (
            authority is None
            or authority["roles"] != ["input-evidence"]
            or REVISION.fullmatch(revision) is None
            or adapter_starts > current
            or adapter_ends < current
            or adapter_starts > adapter_ends
        ):
            raise TrustPolicyError(f"input evidence adapter {adapter_id} is invalid")
        parsed_input_adapters[adapter_id] = {
            "authority_key_id": authority_key_id,
            "built_artifact_sha256": digest(
                adapter["built_artifact_sha256"],
                f"input evidence adapter {adapter_id} artifact",
            ),
            "components": _string_set(
                adapter["components"],
                allowed=COMPONENTS,
                label=f"input evidence adapter {adapter_id} components",
            ),
            "input_classes": _string_set(
                adapter["input_classes"],
                allowed=INPUT_CLASSES,
                label=f"input evidence adapter {adapter_id} input classes",
            ),
            "output_schema": text(
                adapter["output_schema"],
                f"input evidence adapter {adapter_id} output schema",
            ),
            "repository": _https_url(
                adapter["repository"],
                f"input evidence adapter {adapter_id} repository",
            ),
            "revision": revision,
            "source_sha256": digest(
                adapter["source_sha256"],
                f"input evidence adapter {adapter_id} source",
            ),
            "valid_from": adapter_starts.isoformat(),
            "valid_until": adapter_ends.isoformat(),
        }

    lifecycle_adapters = _mapping(
        policy["lifecycle_observation_adapters"],
        "lifecycle observation adapters",
    )
    parsed_lifecycle_adapters: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(lifecycle_adapters):
        adapter_id = identifier(raw_id, "lifecycle observation adapter ID")
        adapter = _mapping(
            lifecycle_adapters[raw_id],
            f"lifecycle observation adapter {adapter_id}",
        )
        _exact_keys(
            adapter,
            {
                "authority_key_id",
                "built_artifact_sha256",
                "components",
                "input_classes",
                "output_schema",
                "repository",
                "revision",
                "source_sha256",
                "valid_from",
                "valid_until",
            },
            f"lifecycle observation adapter {adapter_id}",
        )
        adapter_starts = parse_date(
            adapter["valid_from"],
            f"lifecycle observation adapter {adapter_id} valid_from",
        )
        adapter_ends = parse_date(
            adapter["valid_until"],
            f"lifecycle observation adapter {adapter_id} valid_until",
        )
        authority_key_id = identifier(
            adapter["authority_key_id"],
            f"lifecycle observation adapter {adapter_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        revision = text(
            adapter["revision"],
            f"lifecycle observation adapter {adapter_id} revision",
            maximum=40,
        )
        if (
            authority is None
            or authority["roles"] != ["lifecycle-observer"]
            or REVISION.fullmatch(revision) is None
            or adapter_starts > current
            or adapter_ends < current
            or adapter_starts > adapter_ends
        ):
            raise TrustPolicyError(
                f"lifecycle observation adapter {adapter_id} is invalid"
            )
        parsed_lifecycle_adapters[adapter_id] = {
            "authority_key_id": authority_key_id,
            "built_artifact_sha256": digest(
                adapter["built_artifact_sha256"],
                f"lifecycle observation adapter {adapter_id} artifact",
            ),
            "components": _string_set(
                adapter["components"],
                allowed=COMPONENTS,
                label=f"lifecycle observation adapter {adapter_id} components",
            ),
            "input_classes": _string_set(
                adapter["input_classes"],
                allowed=INPUT_CLASSES,
                label=f"lifecycle observation adapter {adapter_id} input classes",
            ),
            "output_schema": text(
                adapter["output_schema"],
                f"lifecycle observation adapter {adapter_id} output schema",
            ),
            "repository": _https_url(
                adapter["repository"],
                f"lifecycle observation adapter {adapter_id} repository",
            ),
            "revision": revision,
            "source_sha256": digest(
                adapter["source_sha256"],
                f"lifecycle observation adapter {adapter_id} source",
            ),
            "valid_from": adapter_starts.isoformat(),
            "valid_until": adapter_ends.isoformat(),
        }

    scope_adapters = _mapping(
        policy["scope_evidence_adapters"],
        "scope evidence adapters",
    )
    parsed_scope_adapters: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(scope_adapters):
        adapter_id = identifier(raw_id, "scope evidence adapter ID")
        adapter = _mapping(
            scope_adapters[raw_id],
            f"scope evidence adapter {adapter_id}",
        )
        _exact_keys(
            adapter,
            {
                "authority_key_id",
                "built_artifact_sha256",
                "output_schema",
                "repository",
                "revision",
                "scope_source_sha256",
                "scopes",
                "valid_from",
                "valid_until",
                "verifier_source_sha256",
            },
            f"scope evidence adapter {adapter_id}",
        )
        adapter_starts = parse_date(
            adapter["valid_from"],
            f"scope evidence adapter {adapter_id} valid_from",
        )
        adapter_ends = parse_date(
            adapter["valid_until"],
            f"scope evidence adapter {adapter_id} valid_until",
        )
        authority_key_id = identifier(
            adapter["authority_key_id"],
            f"scope evidence adapter {adapter_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        revision = text(
            adapter["revision"],
            f"scope evidence adapter {adapter_id} revision",
            maximum=40,
        )
        scopes = _string_set(
            adapter["scopes"],
            allowed=SCOPES,
            label=f"scope evidence adapter {adapter_id} scopes",
        )
        source_map = _mapping(
            adapter["scope_source_sha256"],
            f"scope evidence adapter {adapter_id} source map",
        )
        _exact_keys(
            source_map,
            set(scopes),
            f"scope evidence adapter {adapter_id} source map",
        )
        if (
            authority is None
            or authority["roles"] != ["scope-evidence"]
            or REVISION.fullmatch(revision) is None
            or adapter_starts > current
            or adapter_ends < current
            or adapter_starts > adapter_ends
            or not scopes
        ):
            raise TrustPolicyError(f"scope evidence adapter {adapter_id} is invalid")
        parsed_scope_adapters[adapter_id] = {
            "authority_key_id": authority_key_id,
            "built_artifact_sha256": digest(
                adapter["built_artifact_sha256"],
                f"scope evidence adapter {adapter_id} artifact",
            ),
            "output_schema": text(
                adapter["output_schema"],
                f"scope evidence adapter {adapter_id} output schema",
            ),
            "repository": _https_url(
                adapter["repository"],
                f"scope evidence adapter {adapter_id} repository",
            ),
            "revision": revision,
            "scope_source_sha256": {
                scope: digest(
                    source_map[scope],
                    f"scope evidence adapter {adapter_id} {scope} source",
                )
                for scope in scopes
            },
            "scopes": scopes,
            "valid_from": adapter_starts.isoformat(),
            "valid_until": adapter_ends.isoformat(),
            "verifier_source_sha256": digest(
                adapter["verifier_source_sha256"],
                f"scope evidence adapter {adapter_id} verifier source",
            ),
        }

    storage_backends = _mapping(policy["storage_backends"], "storage backends")
    parsed_storage_backends: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(storage_backends):
        backend_id = identifier(raw_id, "storage backend ID")
        backend = _mapping(storage_backends[raw_id], f"storage backend {backend_id}")
        _exact_keys(
            backend,
            {
                "backend_type",
                "authority_key_id",
                "driver_contract_sha256",
                "provider_artifact_sha256",
                "provider_kind",
                "provider_lineage_sha256",
                "provider_name",
                "provider_revision",
                "provider_source_sha256",
                "provider_version",
                "support_ends_on",
                "tested_distribution_lineages_sha256",
            },
            f"storage backend {backend_id}",
        )
        provider_revision = text(
            backend["provider_revision"],
            f"storage backend {backend_id} provider revision",
            maximum=40,
        )
        support_end = parse_date(
            backend["support_ends_on"],
            f"storage backend {backend_id} support end",
        )
        authority_key_id = identifier(
            backend["authority_key_id"],
            f"storage backend {backend_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        tested_distribution_lineages = sorted(
            {
                digest(
                    item,
                    f"storage backend {backend_id} tested Distribution lineage",
                )
                for item in _array(
                    backend["tested_distribution_lineages_sha256"],
                    f"storage backend {backend_id} tested Distribution lineages",
                )
            }
        )
        if (
            authority is None
            or authority["roles"] != ["storage-provider"]
            or backend["backend_type"] != "s3-compatible"
            or backend["provider_kind"] != "open-source"
            or REVISION.fullmatch(provider_revision) is None
            or support_end < current
            or not tested_distribution_lineages
        ):
            raise TrustPolicyError(f"storage backend {backend_id} is invalid")
        parsed_storage_backends[backend_id] = {
            "authority_key_id": authority_key_id,
            "backend_type": "s3-compatible",
            "driver_contract_sha256": digest(
                backend["driver_contract_sha256"],
                f"storage backend {backend_id} driver contract",
            ),
            "provider_artifact_sha256": digest(
                backend["provider_artifact_sha256"],
                f"storage backend {backend_id} provider artifact",
            ),
            "provider_kind": backend["provider_kind"],
            "provider_lineage_sha256": digest(
                backend["provider_lineage_sha256"],
                f"storage backend {backend_id} provider lineage",
            ),
            "provider_name": identifier(
                backend["provider_name"],
                f"storage backend {backend_id} provider name",
            ),
            "provider_revision": provider_revision,
            "provider_source_sha256": digest(
                backend["provider_source_sha256"],
                f"storage backend {backend_id} provider source",
            ),
            "provider_version": identifier(
                backend["provider_version"],
                f"storage backend {backend_id} provider version",
            ),
            "support_ends_on": support_end.isoformat(),
            "tested_distribution_lineages_sha256": tested_distribution_lineages,
        }

    writer_fence_adapters = _mapping(
        policy["writer_fence_adapters"],
        "writer fence adapters",
    )
    parsed_writer_fence_adapters: dict[str, dict[str, Any]] = {}
    for raw_id in sorted(writer_fence_adapters):
        adapter_id = identifier(raw_id, "writer fence adapter ID")
        adapter = _mapping(
            writer_fence_adapters[raw_id],
            f"writer fence adapter {adapter_id}",
        )
        _exact_keys(
            adapter,
            {
                "authority_key_id",
                "built_artifact_sha256",
                "lease_namespace",
                "output_schema",
                "repository",
                "revision",
                "source_sha256",
                "state_backend",
                "valid_from",
                "valid_until",
            },
            f"writer fence adapter {adapter_id}",
        )
        adapter_starts = parse_date(
            adapter["valid_from"],
            f"writer fence adapter {adapter_id} valid_from",
        )
        adapter_ends = parse_date(
            adapter["valid_until"],
            f"writer fence adapter {adapter_id} valid_until",
        )
        authority_key_id = identifier(
            adapter["authority_key_id"],
            f"writer fence adapter {adapter_id} authority",
        )
        authority = authority_by_id.get(authority_key_id)
        revision = text(
            adapter["revision"],
            f"writer fence adapter {adapter_id} revision",
            maximum=40,
        )
        if (
            authority is None
            or authority["roles"] != ["writer-fence"]
            or REVISION.fullmatch(revision) is None
            or adapter["state_backend"] != "shared-cas-lease"
            or adapter_starts > current
            or adapter_ends < current
            or adapter_starts > adapter_ends
        ):
            raise TrustPolicyError(
                f"writer fence adapter {adapter_id} is invalid"
            )
        parsed_writer_fence_adapters[adapter_id] = {
            "authority_key_id": authority_key_id,
            "built_artifact_sha256": digest(
                adapter["built_artifact_sha256"],
                f"writer fence adapter {adapter_id} artifact",
            ),
            "lease_namespace": identifier(
                adapter["lease_namespace"],
                f"writer fence adapter {adapter_id} lease namespace",
            ),
            "output_schema": text(
                adapter["output_schema"],
                f"writer fence adapter {adapter_id} output schema",
            ),
            "repository": _https_url(
                adapter["repository"],
                f"writer fence adapter {adapter_id} repository",
            ),
            "revision": revision,
            "source_sha256": digest(
                adapter["source_sha256"],
                f"writer fence adapter {adapter_id} source",
            ),
            "state_backend": "shared-cas-lease",
            "valid_from": adapter_starts.isoformat(),
            "valid_until": adapter_ends.isoformat(),
        }

    blockers = _mapping(policy["blockers"], "trust policy blockers")
    parsed_blockers: dict[str, dict[str, str]] = {}
    for raw_id in sorted(blockers):
        blocker_id = identifier(raw_id, "blocker ID")
        blocker = _mapping(blockers[raw_id], f"blocker {blocker_id}")
        _exact_keys(
            blocker,
            {"component", "kind", "upstream_repository"},
            f"blocker {blocker_id}",
        )
        component = blocker["component"]
        if (
            component not in COMPONENTS
            or blocker["kind"] not in {"correctness", "security"}
            or blocker["upstream_repository"]
            not in parsed_components[component]["upstream_repositories"]
        ):
            raise TrustPolicyError(f"blocker {blocker_id} is invalid")
        parsed_blockers[blocker_id] = {
            "component": component,
            "kind": blocker["kind"],
            "upstream_repository": blocker["upstream_repository"],
        }

    vendors = _array(policy["vendors"], "trust policy vendors")
    parsed_vendors: list[dict[str, Any]] = []
    vendor_ids: set[str] = set()
    for index, raw in enumerate(vendors):
        vendor = _mapping(raw, f"vendor {index}")
        _exact_keys(
            vendor,
            {
                "advisory_origins",
                "components",
                "provider_id",
                "release_signing_identities",
                "releases",
                "repositories",
            },
            f"vendor {index}",
        )
        provider_id = identifier(
            vendor["provider_id"],
            f"vendor {index} provider_id",
        )
        if provider_id in vendor_ids:
            raise TrustPolicyError("vendor IDs are not unique")
        vendor_ids.add(provider_id)
        vendor_repositories = sorted(
            {
                text(item, f"vendor {index} repository")
                for item in _array(
                    vendor["repositories"],
                    f"vendor {index} repositories",
                )
            }
        )
        releases = _mapping(
            vendor["releases"],
            f"vendor {index} releases",
        )
        parsed_releases: dict[str, dict[str, str]] = {}
        for version in sorted(releases):
            release = _mapping(
                releases[version],
                f"vendor {index} release {version}",
            )
            _exact_keys(
                release,
                {
                    "component",
                    "repository",
                    "revision",
                    "source_sha256",
                    "support_ends_on",
                    "upstream_revision",
                    "upstream_source_sha256",
                    "upstream_tag",
                    "tag",
                },
                f"vendor {index} release {version}",
            )
            component = release["component"]
            if (
                component not in COMPONENTS
                or component not in vendor["components"]
                or release["repository"] not in vendor_repositories
                or REVISION.fullmatch(str(release["revision"])) is None
                or REVISION.fullmatch(str(release["upstream_revision"])) is None
                or re.fullmatch(
                    parsed_components[component]["tag_pattern"],
                    str(release["tag"]),
                )
                is None
                or release["tag"] != version
                or re.fullmatch(
                    parsed_components[component]["tag_pattern"],
                    str(release["upstream_tag"]),
                )
                is None
            ):
                raise TrustPolicyError(f"vendor {index} release {version} is invalid")
            parsed_releases[text(version, "vendor release version")] = {
                "component": component,
                "repository": release["repository"],
                "revision": release["revision"],
                "source_sha256": digest(
                    release["source_sha256"],
                    "vendor release source",
                ),
                "support_ends_on": parse_date(
                    release["support_ends_on"],
                    "vendor release support_ends_on",
                ).isoformat(),
                "upstream_revision": release["upstream_revision"],
                "upstream_source_sha256": digest(
                    release["upstream_source_sha256"],
                    "vendor upstream source",
                ),
                "upstream_tag": release["upstream_tag"],
                "tag": release["tag"],
            }
        parsed_vendors.append(
            {
                "advisory_origins": sorted(
                    {
                        _https_url(
                            item,
                            f"vendor {index} advisory origin",
                        )
                        for item in _array(
                            vendor["advisory_origins"],
                            f"vendor {index} advisory origins",
                        )
                    }
                ),
                "components": _string_set(
                    vendor["components"],
                    allowed=COMPONENTS,
                    label=f"vendor {index} components",
                ),
                "provider_id": provider_id,
                "release_signing_identities": sorted(
                    {
                        text(item, f"vendor {index} release identity")
                        for item in _array(
                            vendor["release_signing_identities"],
                            f"vendor {index} release identities",
                        )
                    }
                ),
                "releases": parsed_releases,
                "repositories": vendor_repositories,
            }
        )

    coffer = _mapping(policy["coffer"], "Coffer trust policy")
    _exact_keys(
        coffer,
        {
            "builder_operator_ids",
            "maximum_patch_support_months",
            "patch_releases",
            "release_ends_on",
            "release_signing_identities",
            "replacement_grace_days",
            "repository",
        },
        "Coffer trust policy",
    )
    maximum_support = coffer["maximum_patch_support_months"]
    replacement_grace = coffer["replacement_grace_days"]
    coffer_identities = _array(
        coffer["release_signing_identities"],
        "Coffer release identities",
    )
    coffer_builder_operators = _array(
        coffer["builder_operator_ids"],
        "Coffer builder operator IDs",
    )
    release_ends_on = parse_date(
        coffer["release_ends_on"],
        "Coffer release end",
    )
    if (
        maximum_support != 12
        or replacement_grace != 90
        or coffer_identities != sorted(set(coffer_identities))
        or coffer_builder_operators
        != sorted(set(coffer_builder_operators))
    ):
        raise TrustPolicyError("Coffer trust policy is invalid")
    parsed_patch_releases: dict[str, dict[str, Any]] = {}
    patch_releases = _mapping(
        coffer["patch_releases"],
        "Coffer patch releases",
    )
    for version in sorted(patch_releases):
        raw = _mapping(
            patch_releases[version],
            f"Coffer patch release {version}",
        )
        _exact_keys(
            raw,
            {
                "admitted_on",
                "component",
                "owner_authority_key_id",
                "release_revision",
                "release_source_sha256",
                "release_tag",
                "replacement",
                "retire_on",
                "support_ends_on",
                "upstream_revision",
                "upstream_source_sha256",
                "upstream_tag",
            },
            f"Coffer patch release {version}",
        )
        component = raw["component"]
        if component not in COMPONENTS:
            raise TrustPolicyError(
                f"Coffer patch release {version} is invalid"
            )
        owner_key_id = identifier(
            raw["owner_authority_key_id"],
            f"Coffer patch release {version} owner",
        )
        owner = authority_by_id.get(owner_key_id)
        admitted_on = parse_date(
            raw["admitted_on"],
            f"Coffer patch release {version} admitted_on",
        )
        support_ends_on = parse_date(
            raw["support_ends_on"],
            f"Coffer patch release {version} support_ends_on",
        )
        retire_on = parse_date(
            raw["retire_on"],
            f"Coffer patch release {version} retire_on",
        )
        replacement_raw = raw["replacement"]
        replacement: dict[str, Any] | None
        if replacement_raw is None:
            replacement = None
        else:
            replacement_map = _mapping(
                replacement_raw,
                f"Coffer patch release {version} replacement",
            )
            _exact_keys(
                replacement_map,
                {
                    "input_class",
                    "provider_id",
                    "qualified_on",
                    "release_tag",
                    "result_sha256",
                    "upstream_tag",
                },
                f"Coffer patch release {version} replacement",
            )
            replacement_class = replacement_map["input_class"]
            replacement_qualified_on = parse_date(
                replacement_map["qualified_on"],
                f"Coffer patch release {version} replacement qualified_on",
            )
            replacement_tag = text(
                replacement_map["upstream_tag"],
                f"Coffer patch release {version} replacement upstream tag",
                maximum=128,
            )
            replacement_release_tag = text(
                replacement_map["release_tag"],
                f"Coffer patch release {version} replacement release tag",
                maximum=128,
            )
            replacement_provider_id = replacement_map["provider_id"]
            replacement_release: Mapping[str, Any] | None = None
            replacement_catalog_valid = False
            if replacement_class == "official-upstream":
                if replacement_provider_id is not None:
                    raise TrustPolicyError(
                        f"Coffer patch release {version} replacement is invalid"
                    )
                replacement_release = parsed_components[component][
                    "official_releases"
                ].get(replacement_release_tag)
                replacement_provider: str | None = None
                replacement_catalog_valid = (
                    replacement_release is not None
                    and replacement_release_tag == replacement_tag
                )
            elif replacement_class == "approved-vendor-backport":
                replacement_provider = identifier(
                    replacement_provider_id,
                    (
                        f"Coffer patch release {version} replacement "
                        "provider"
                    ),
                )
                matching_vendors = [
                    vendor
                    for vendor in parsed_vendors
                    if vendor["provider_id"] == replacement_provider
                ]
                if len(matching_vendors) == 1:
                    replacement_release = matching_vendors[0][
                        "releases"
                    ].get(replacement_release_tag)
                replacement_catalog_valid = (
                    replacement_release is not None
                    and replacement_release["component"] == component
                    and replacement_release["upstream_tag"]
                    == replacement_tag
                )
            else:
                replacement_provider = None
            replacement = {
                "input_class": replacement_class,
                "provider_id": replacement_provider,
                "qualified_on": replacement_qualified_on.isoformat(),
                "release_revision": (
                    None
                    if replacement_release is None
                    else replacement_release["revision"]
                ),
                "release_source_sha256": (
                    None
                    if replacement_release is None
                    else replacement_release["source_sha256"]
                ),
                "release_tag": replacement_release_tag,
                "result_sha256": digest(
                    replacement_map["result_sha256"],
                    f"Coffer patch release {version} replacement result",
                ),
                "upstream_revision": (
                    None
                    if replacement_release is None
                    else replacement_release.get(
                        "upstream_revision",
                        replacement_release["revision"],
                    )
                ),
                "upstream_source_sha256": (
                    None
                    if replacement_release is None
                    else replacement_release.get(
                        "upstream_source_sha256",
                        replacement_release["source_sha256"],
                    )
                ),
                "upstream_tag": replacement_tag,
            }
            if (
                replacement_class
                not in {"approved-vendor-backport", "official-upstream"}
                or component not in COMPONENTS
                or replacement_release is None
                or not replacement_catalog_valid
                or re.fullmatch(
                    parsed_components[component]["tag_pattern"],
                    replacement_tag,
                )
                is None
                or re.fullmatch(
                    parsed_components[component]["tag_pattern"],
                    replacement_release_tag,
                )
                is None
                or (
                    replacement_class == "official-upstream"
                    and replacement_tag == raw["upstream_tag"]
                )
                or replacement_release_tag == raw["release_tag"]
                or replacement_qualified_on < admitted_on
                or replacement_qualified_on > current
                or replacement_qualified_on > support_ends_on
                or replacement_qualified_on > release_ends_on
                or retire_on
                != min(
                    replacement_qualified_on
                    + timedelta(days=replacement_grace),
                    support_ends_on,
                    release_ends_on,
                )
                or parse_date(
                    replacement_release["support_ends_on"],
                    (
                        f"Coffer patch release {version} replacement "
                        "support end"
                    ),
                )
                < release_ends_on
            ):
                raise TrustPolicyError(
                    f"Coffer patch release {version} replacement is invalid"
                )
        if (
            component not in COMPONENTS
            or owner is None
            or owner["roles"] != ["patch-owner"]
            or component not in owner["components"]
            or "coffer-minimal-patch" not in owner["input_classes"]
            or REVISION.fullmatch(str(raw["release_revision"])) is None
            or REVISION.fullmatch(str(raw["upstream_revision"])) is None
            or version != raw["release_tag"]
            or re.fullmatch(
                parsed_components[component]["tag_pattern"],
                str(raw["release_tag"]),
            )
            is None
            or re.fullmatch(
                parsed_components[component]["tag_pattern"],
                str(raw["upstream_tag"]),
            )
            is None
            or admitted_on > support_ends_on
            or admitted_on > current
            or retire_on > support_ends_on
            or retire_on > release_ends_on
            or (
                raw["upstream_tag"]
                != parsed_components[component]["latest_supported_patch_base"]
                and replacement is None
            )
        ):
            raise TrustPolicyError(
                f"Coffer patch release {version} is invalid"
            )
        parsed_patch_releases[version] = {
            "admitted_on": admitted_on.isoformat(),
            "component": component,
            "owner_authority_key_id": owner_key_id,
            "release_revision": raw["release_revision"],
            "release_source_sha256": digest(
                raw["release_source_sha256"],
                f"Coffer patch release {version} source",
            ),
            "release_tag": raw["release_tag"],
            "replacement": replacement,
            "retire_on": retire_on.isoformat(),
            "support_ends_on": support_ends_on.isoformat(),
            "upstream_revision": raw["upstream_revision"],
            "upstream_source_sha256": digest(
                raw["upstream_source_sha256"],
                f"Coffer patch release {version} upstream source",
            ),
            "upstream_tag": raw["upstream_tag"],
        }
    if parsed_patch_releases and (
        not coffer_builder_operators or not coffer_identities
    ):
        raise TrustPolicyError(
            "Coffer patch releases require builders and release identities"
        )

    return {
        "attestation_max_age_days": maximum_age,
        "authorities": parsed_authorities,
        "blockers": parsed_blockers,
        "checkpoint_revocations": parsed_checkpoint_revocations,
        "coffer": {
            "builder_operator_ids": [
                identifier(item, "Coffer builder operator")
                for item in coffer_builder_operators
            ],
            "maximum_patch_support_months": 12,
            "patch_releases": parsed_patch_releases,
            "release_ends_on": release_ends_on.isoformat(),
            "release_signing_identities": [
                text(item, "Coffer release identity") for item in coffer_identities
            ],
            "replacement_grace_days": 90,
            "repository": text(coffer["repository"], "Coffer repository"),
        },
        "components": parsed_components,
        "environment": policy["environment"],
        "input_evidence_adapters": parsed_input_adapters,
        "lifecycle_observation_adapters": parsed_lifecycle_adapters,
        "policy_id": identifier(policy["policy_id"], "trust policy ID"),
        "predicate_types": parsed_predicates,
        "release_verification_adapters": parsed_release_adapters,
        "schema": POLICY_SCHEMA,
        "scope_evidence_adapters": parsed_scope_adapters,
        "storage_backends": parsed_storage_backends,
        "valid_from": starts.isoformat(),
        "valid_until": ends.isoformat(),
        "vendors": parsed_vendors,
        "writer_fence_adapters": parsed_writer_fence_adapters,
    }


def policy_authority(
    policy: Mapping[str, Any],
    *,
    key_id: str,
    role: str,
    component: str | None = None,
    input_class: str | None = None,
    scope: str | None = None,
    today: date | None = None,
) -> Mapping[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    matches = [
        authority
        for authority in policy["authorities"]
        if authority["key_id"] == key_id
    ]
    if len(matches) != 1:
        raise TrustPolicyError("attestation authority is not trusted")
    authority = matches[0]
    if (
        role not in authority["roles"]
        or (component is not None and component not in authority["components"])
        or (input_class is not None and input_class not in authority["input_classes"])
        or (scope is not None and scope not in authority["scopes"])
        or parse_date(authority["not_before"], "authority not_before") > current
        or parse_date(authority["not_after"], "authority not_after") < current
        or (
            authority["revoked_on"] is not None
            and parse_date(authority["revoked_on"], "authority revoked_on") <= current
        )
    ):
        raise TrustPolicyError("attestation authority scope is not trusted")
    return authority


def verify_attestation(
    value: object,
    *,
    policy: Mapping[str, Any],
    role: str,
    predicate_type: str,
    subjects: Mapping[str, str],
    today: date | None = None,
    component: str | None = None,
    input_class: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    current = datetime.now(tz=UTC).date() if today is None else today
    attestation = _mapping(value, "signed attestation")
    _exact_keys(
        attestation,
        {
            "algorithm",
            "expires_on",
            "issued_on",
            "key_id",
            "predicate",
            "predicate_type",
            "role",
            "schema",
            "signature",
            "subjects",
        },
        "signed attestation",
    )
    issued = parse_date(attestation["issued_on"], "attestation issued_on")
    expires = parse_date(attestation["expires_on"], "attestation expires_on")
    if (
        attestation["schema"] != ATTESTATION_SCHEMA
        or attestation["algorithm"] != "ed25519"
        or attestation["role"] != role
        or attestation["predicate_type"] != predicate_type
        or issued > current
        or expires < current
        or issued > expires
        or (expires - issued).days > policy["attestation_max_age_days"]
    ):
        raise TrustPolicyError("signed attestation identity is invalid")
    key_id = identifier(attestation["key_id"], "attestation key_id")
    authority = policy_authority(
        policy,
        key_id=key_id,
        role=role,
        component=component,
        input_class=input_class,
        scope=scope,
        today=current,
    )
    authority_starts = parse_date(
        authority["not_before"],
        "authority not_before",
    )
    authority_ends = parse_date(authority["not_after"], "authority not_after")
    authority_revoked = (
        None
        if authority["revoked_on"] is None
        else parse_date(authority["revoked_on"], "authority revoked_on")
    )
    if (
        issued < authority_starts
        or expires > authority_ends
        or (authority_revoked is not None and authority_revoked <= expires)
    ):
        raise TrustPolicyError("attestation exceeds authority validity")
    parsed_subjects = _mapping(
        attestation["subjects"],
        "attestation subjects",
    )
    if set(parsed_subjects) != set(subjects):
        raise TrustPolicyError("attestation subjects are incomplete")
    normalized_subjects = {
        name: digest(parsed_subjects[name], f"attestation subject {name}")
        for name in sorted(parsed_subjects)
    }
    if normalized_subjects != dict(sorted(subjects.items())):
        raise TrustPolicyError("attestation subject binding changed")
    signature_text = text(
        attestation["signature"],
        "attestation signature",
        maximum=256,
    )
    try:
        signature = base64.b64decode(signature_text, validate=True)
        public_key = base64.b64decode(
            authority["public_key"],
            validate=True,
        )
        signed = dict(attestation)
        del signed["signature"]
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            canonical_bytes(signed),
        )
    except (InvalidSignature, ValueError, binascii.Error) as error:
        raise TrustPolicyError("attestation signature is invalid") from error
    return {
        "algorithm": "ed25519",
        "expires_on": expires.isoformat(),
        "issued_on": issued.isoformat(),
        "key_id": key_id,
        "predicate": dict(_mapping(attestation["predicate"], "predicate")),
        "predicate_type": predicate_type,
        "role": role,
        "schema": ATTESTATION_SCHEMA,
        "signature": signature_text,
        "subjects": normalized_subjects,
    }


def load_private_json(
    path: Path,
    label: str,
    *,
    maximum_bytes: int = 16 * 1024 * 1024,
) -> LoadedDocument:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or stat.S_IMODE(details.st_mode) != 0o600
            or details.st_uid != os.getuid()
            or details.st_size < 1
            or details.st_size > maximum_bytes
        ):
            raise TrustPolicyError(f"{label} ownership or size is unsafe")
        payload = bytearray()
        while len(payload) <= maximum_bytes:
            chunk = os.read(descriptor, min(65536, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if not payload or len(payload) > maximum_bytes:
            raise TrustPolicyError(f"{label} size is invalid")
        value = strict_json_loads(payload)
    except TrustPolicyError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TrustPolicyError(f"{label} is invalid") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise TrustPolicyError(f"{label} must be a JSON object")
    return LoadedDocument(
        value=value,
        raw_sha256=sha256_bytes(bytes(payload)),
        canonical_sha256=canonical_sha256(value),
        raw_bytes=bytes(payload),
    )


def verify_loaded_document(
    value: object,
    label: str,
    *,
    maximum_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    if not isinstance(value, LoadedDocument):
        raise TrustPolicyError(f"{label} is not a loaded document")
    payload = value.raw_bytes
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= maximum_bytes:
        raise TrustPolicyError(f"{label} loaded bytes are invalid")
    parsed = strict_json_loads(payload)
    if (
        not isinstance(parsed, dict)
        or parsed != value.value
        or sha256_bytes(payload) != value.raw_sha256
        or canonical_sha256(parsed) != value.canonical_sha256
    ):
        raise TrustPolicyError(f"{label} loaded document binding changed")
    return parsed


def load_policy(
    path: Path = PRODUCTION_POLICY_SOURCE,
    *,
    today: date | None = None,
    allow_synthetic: bool = False,
) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = strict_json_loads(payload)
    except TrustPolicyError:
        raise
    except OSError as error:
        raise TrustPolicyError("trust policy source is invalid") from error
    policy = validate_policy(value, today=today)
    if policy["environment"] == "synthetic" and not allow_synthetic:
        raise TrustPolicyError("synthetic trust policy is not production")
    return policy, sha256_bytes(payload)


def write_owner_only(
    path: Path,
    value: Mapping[str, Any],
    *,
    maximum_bytes: int = OWNER_ONLY_DEFAULT_MAX_BYTES,
) -> None:
    write_owner_only_bytes(
        path,
        canonical_bytes(value) + b"\n",
        maximum_bytes=maximum_bytes,
    )


def write_or_verify_owner_only(
    path: Path,
    value: Mapping[str, Any],
    *,
    label: str,
    maximum_bytes: int = OWNER_ONLY_DEFAULT_MAX_BYTES,
) -> None:
    """Create an immutable result or verify its exact requested bytes.

    This is limited to deterministic compiler outputs. Primary attestations
    continue to use ``write_owner_only`` and must choose a new path.
    """

    payload = canonical_bytes(value) + b"\n"
    _validate_owner_only_destination(
        path,
        payload,
        maximum_bytes=maximum_bytes,
    )
    if path.exists() or path.is_symlink():
        existing = load_private_json(
            path,
            label,
            maximum_bytes=maximum_bytes,
        )
        if existing.raw_bytes != payload:
            raise TrustPolicyError(
                f"existing {label} does not match requested inputs"
            )
        return
    write_owner_only_bytes(
        path,
        payload,
        maximum_bytes=maximum_bytes,
    )


def _validate_owner_only_destination(
    path: Path,
    payload: bytes,
    *,
    maximum_bytes: int,
) -> None:
    if not path.is_absolute():
        raise TrustPolicyError("output path must be absolute")
    if (
        not isinstance(maximum_bytes, int)
        or isinstance(maximum_bytes, bool)
        or not 1 <= maximum_bytes <= OWNER_ONLY_HARD_MAX_BYTES
        or not payload
        or len(payload) > maximum_bytes
    ):
        raise TrustPolicyError("output payload size is invalid")
    try:
        parent = path.parent.lstat()
    except OSError as error:
        raise TrustPolicyError("output directory is invalid") from error
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise TrustPolicyError("output directory ownership is unsafe")


def write_owner_only_bytes(
    path: Path,
    payload: bytes,
    *,
    maximum_bytes: int = OWNER_ONLY_DEFAULT_MAX_BYTES,
) -> None:
    _validate_owner_only_destination(
        path,
        payload,
        maximum_bytes=maximum_bytes,
    )
    if path.exists() or path.is_symlink():
        raise TrustPolicyError("output path already exists")

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary = Path(temporary_name)
    linked = False
    try:
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written < 1:
                raise TrustPolicyError("unable to write owner-only output")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(temporary, path, follow_symlinks=False)
        linked = True
        temporary.unlink()
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except FileExistsError as error:
        raise TrustPolicyError("output path already exists") from error
    except OSError as error:
        if linked:
            path.unlink(missing_ok=True)
        raise TrustPolicyError("unable to write owner-only output") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
