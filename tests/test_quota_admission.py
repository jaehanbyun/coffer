from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import rsa
from falcon import testing
from sqlalchemy import exc as sa_exception

from coffer.db import RepositoryStore
from coffer.keystone import ApplicationCredentialPrincipal
from coffer.quota import QuotaStore
from coffer.quota_admission import (
    ManifestAdmissionService,
    RegistryTokenVerifier,
    UpstreamResponse,
    build_manifest_admission_application,
)
from coffer.tokens import AccessGrant, TokenIssuer


PROJECT = "11111111-1111-4111-8111-111111111111"
CANONICAL_REPOSITORY = f"p/{PROJECT}/demo"


def sha256_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def manifest(config_size: int = 100, layer_size: int = 200) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"digest": sha256_digest(b"config"), "size": config_size},
            "layers": [
                {"digest": sha256_digest(b"layer"), "size": layer_size}
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


class FakeUpstream:
    def __init__(self, *, status: int = 201, raises: bool = False) -> None:
        self.status = status
        self.raises = raises
        self.bodies: list[bytes] = []
        self.headers: list[dict[str, str]] = []

    def descriptor_size(self, *, digest: str, **_kwargs: object) -> int:
        sizes = {
            sha256_digest(b"config"): 100,
            sha256_digest(b"layer"): 200,
        }
        return sizes[digest]

    def put_manifest(self, **kwargs: object) -> UpstreamResponse:
        if self.raises:
            raise OSError("bounded upstream failure")
        self.bodies.append(kwargs["body"])  # type: ignore[arg-type]
        self.headers.append(dict(kwargs["headers"]))  # type: ignore[arg-type]
        return UpstreamResponse(
            self.status,
            (("Docker-Content-Digest", sha256_digest(kwargs["body"])),),  # type: ignore[arg-type]
            b"",
        )


def fixture(tmp_path: Path, *, quota_limit: int | None, upstream: FakeUpstream):
    database = f"sqlite:///{tmp_path / 'quota.sqlite'}"
    repositories = RepositoryStore(database)
    repositories.create(PROJECT, "demo")
    quotas = QuotaStore(database, bootstrap_schema=True)
    if quota_limit is not None:
        quotas.set_limit(PROJECT, quota_limit)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = TokenIssuer(
        private_key=private_key,
        issuer="coffer-quota-test",
        service="coffer-quota-registry",
        clock=lambda: datetime.now(UTC),
    )
    principal = ApplicationCredentialPrincipal(
        application_credential_id="credential-id",
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        project_id=PROJECT,
        roles=("member",),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        audit_ids=("audit-id",),
    )
    token = issuer.issue(
        principal,
        (AccessGrant("repository", CANONICAL_REPOSITORY, ("pull", "push")),),
    ).token
    verifier = RegistryTokenVerifier(
        issuer.jwks(), issuer=issuer.issuer, service=issuer.service
    )
    application = build_manifest_admission_application(
        verifier,
        ManifestAdmissionService(repositories, quotas),
        upstream,
        token_realm="https://registry.example/auth/token",
    )
    return testing.TestClient(application), quotas, token


def put(client: testing.TestClient, token: str, body: bytes):
    return client.simulate_put(
        f"/v2/{CANONICAL_REPOSITORY}/manifests/latest",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.oci.image.manifest.v1+json",
            "Host": "registry.example:5000",
            "X-Openstack-Request-Id": "req-quota-test",
        },
        body=body,
    )


def test_manifest_is_forwarded_byte_for_byte_and_committed(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)
    body = manifest()

    result = put(client, token, body)

    assert result.status_code == 201
    assert upstream.bodies == [body]
    assert upstream.headers[0]["HOST"] == "registry.example:5000"
    assert quotas.usage(PROJECT).used_bytes > 0
    assert quotas.usage(PROJECT).reserved_bytes == 0
    assert result.headers["docker-content-digest"] == sha256_digest(body)


def test_quota_denial_is_distribution_compatible_and_does_not_forward(
    tmp_path: Path,
) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=1, upstream=upstream)

    result = put(client, token, manifest())

    assert result.status_code == 429
    assert result.headers["retry-after"] == "60"
    assert result.json == {
        "errors": [
            {
                "code": "TOOMANYREQUESTS",
                "message": "project logical quota exceeded",
            }
        ]
    }
    assert upstream.bodies == []
    assert quotas.usage(PROJECT).used_bytes == 0
    assert quotas.usage(PROJECT).reserved_bytes == 0


def test_missing_quota_fails_closed_with_503(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    client, _quotas, token = fixture(tmp_path, quota_limit=None, upstream=upstream)

    result = put(client, token, manifest())

    assert result.status_code == 503
    assert result.headers["retry-after"] == "5"
    assert result.json["errors"][0]["code"] == "UNAVAILABLE"
    assert upstream.bodies == []


def test_invalid_or_insufficient_token_is_401_before_quota(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    client, quotas, _token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)

    result = put(client, "not-a-jwt", manifest())

    assert result.status_code == 401
    assert result.json["errors"][0]["code"] == "UNAUTHORIZED"
    assert result.headers["www-authenticate"] == (
        'Bearer realm="https://registry.example/auth/token",'
        'service="coffer-quota-registry",'
        f'scope="repository:{CANONICAL_REPOSITORY}:pull,push"'
    )
    assert upstream.bodies == []
    assert quotas.usage(PROJECT).reserved_bytes == 0


def test_oversized_and_malformed_manifests_do_not_reserve(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=10_000_000, upstream=upstream)

    malformed = put(client, token, b"not-json")
    oversized = put(client, token, b"{" + b" " * (4 * 1024 * 1024) + b"}")

    assert malformed.status_code == 400
    assert oversized.status_code == 413
    assert quotas.usage(PROJECT).reserved_bytes == 0
    assert upstream.bodies == []


def test_upstream_failure_retains_conservative_release_pending_charge(
    tmp_path: Path,
) -> None:
    upstream = FakeUpstream(raises=True)
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)

    result = put(client, token, manifest())

    assert result.status_code == 503
    assert result.json["errors"][0]["code"] == "UNAVAILABLE"
    usage = quotas.usage(PROJECT)
    assert usage.used_bytes == 0
    assert usage.reserved_bytes > 0


def test_declared_descriptor_size_must_match_upstream_content(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)

    result = put(client, token, manifest(config_size=0))

    assert result.status_code == 400
    assert result.json["errors"][0]["code"] == "MANIFEST_INVALID"
    assert quotas.usage(PROJECT).reserved_bytes == 0
    assert upstream.bodies == []


def test_release_pending_retry_can_commit_and_committed_retry_never_downgrades(
    tmp_path: Path,
) -> None:
    upstream = FakeUpstream(raises=True)
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)
    body = manifest()

    assert put(client, token, body).status_code == 503
    assert quotas.usage(PROJECT).reserved_bytes > 0
    upstream.raises = False
    assert put(client, token, body).status_code == 201
    committed = quotas.usage(PROJECT)
    assert committed.used_bytes > 0
    assert committed.reserved_bytes == 0

    upstream.raises = True
    assert put(client, token, body).status_code == 503
    assert quotas.usage(PROJECT) == committed
    upstream.raises = False
    assert put(client, token, body).status_code == 201
    assert quotas.usage(PROJECT) == committed


def test_definitive_upstream_rejection_releases_pending_charge(tmp_path: Path) -> None:
    upstream = FakeUpstream(status=400)
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)

    result = put(client, token, manifest())

    assert result.status_code == 400
    assert quotas.usage(PROJECT).used_bytes == 0
    assert quotas.usage(PROJECT).reserved_bytes == 0


def test_raw_sqlalchemy_failures_map_to_503(tmp_path: Path, monkeypatch) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)
    operational_error = sa_exception.OperationalError(
        "quota operation", {}, RuntimeError("database unavailable")
    )

    def fail_reserve(**_kwargs: object) -> None:
        raise operational_error

    monkeypatch.setattr(quotas, "reserve", fail_reserve)

    result = put(client, token, manifest())

    assert result.status_code == 503
    assert result.json["errors"][0]["code"] == "UNAVAILABLE"
    assert upstream.bodies == []


def test_commit_sqlalchemy_failure_is_indeterminate_503(
    tmp_path: Path, monkeypatch
) -> None:
    upstream = FakeUpstream()
    client, quotas, token = fixture(tmp_path, quota_limit=10_000, upstream=upstream)
    operational_error = sa_exception.OperationalError(
        "quota commit", {}, RuntimeError("database unavailable")
    )

    def fail_commit(_reservation_id: str) -> None:
        raise operational_error

    monkeypatch.setattr(quotas, "commit", fail_commit)
    result = put(client, token, manifest())

    assert result.status_code == 503
    assert result.json["errors"][0]["code"] == "UNAVAILABLE"
    assert len(upstream.bodies) == 1
    assert quotas.usage(PROJECT).reserved_bytes > 0
