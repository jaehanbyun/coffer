from __future__ import annotations

import ipaddress
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from keystoneauth1 import adapter, session, token_endpoint
from keystoneauth1 import exceptions as ksa_exceptions
from openstack_dashboard.api import base

SERVICE_TYPE = "oci-registry"
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000
MAX_ARTIFACT_PAGE_LIMIT = 100
MAX_ARTIFACT_QUERY_LENGTH = 128
MAX_LOGICAL_BYTES = 2**63 - 1
REQUEST_TIMEOUT = (5, 30)
REPOSITORY_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
PROJECT_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
REGISTRY_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)
ARTIFACT_KINDS = frozenset({"artifact", "image", "image_index"})
RESULTS = frozenset(
    {
        "authentication_required",
        "conflict",
        "forbidden",
        "invalid_request",
        "invalid_response",
        "not_found",
        "unavailable",
    }
)
REPOSITORY_FIELDS = frozenset(
    {"id", "project_id", "name", "immutable_tags", "created_at"}
)
QUOTA_FIELDS = frozenset({"project_id", "limit_bytes", "used_bytes", "reserved_bytes"})
ARTIFACT_FIELDS = frozenset(
    {
        "project_id",
        "repository_id",
        "digest",
        "media_type",
        "artifact_type",
        "kind",
        "size_bytes",
        "pushed_at",
        "updated_at",
        "tags",
        "tag_count",
        "tags_truncated",
    }
)


class CofferAPIError(RuntimeError):
    def __init__(self, result: str) -> None:
        if result not in RESULTS:
            raise ValueError("Coffer API result is not bounded")
        self.result = result
        super().__init__(f"Coffer API request failed: {result}")


@dataclass(frozen=True, slots=True)
class Repository:
    id: str
    project_id: str
    name: str
    immutable_tags: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class RepositoryPage:
    repositories: tuple[Repository, ...]
    next_marker: str | None


@dataclass(frozen=True, slots=True)
class Quota:
    project_id: str
    limit_bytes: int
    used_bytes: int
    reserved_bytes: int

    @property
    def available_bytes(self) -> int:
        return max(self.limit_bytes - self.used_bytes - self.reserved_bytes, 0)

    @property
    def charged_bytes(self) -> int:
        return self.used_bytes + self.reserved_bytes

    @property
    def usage_percent(self) -> float:
        if self.limit_bytes == 0:
            return 100.0 if self.charged_bytes else 0.0
        return min(self.charged_bytes / self.limit_bytes * 100, 100.0)


@dataclass(frozen=True, slots=True)
class Artifact:
    project_id: str
    repository_id: str
    digest: str
    media_type: str
    artifact_type: str | None
    kind: str
    size_bytes: int
    pushed_at: str
    updated_at: str
    tags: tuple[str, ...]
    tag_count: int
    tags_truncated: bool

    @property
    def primary_tag(self) -> str | None:
        return self.tags[0] if self.tags else None

    @property
    def display_type(self) -> str:
        return {
            "image": "Container image",
            "image_index": "Multi-platform image",
            "artifact": "OCI artifact",
        }[self.kind]


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    artifacts: tuple[Artifact, ...]
    next_marker: str | None


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise CofferAPIError("invalid_response")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        parsed = None
    if parsed is None:
        raise CofferAPIError("invalid_response")
    if str(parsed) != value:
        raise CofferAPIError("invalid_response")
    return value


def _project_id(request: Any) -> str:
    project_id = getattr(request.user, "project_id", None)
    if (
        not isinstance(project_id, str)
        or PROJECT_SEGMENT.fullmatch(project_id) is None
    ):
        raise CofferAPIError("authentication_required")
    return project_id


def _verify_setting() -> bool | str:
    if getattr(settings, "OPENSTACK_SSL_NO_VERIFY", False):
        return False
    cacert = getattr(settings, "OPENSTACK_SSL_CACERT", None)
    return cacert or True


def _registry_netloc(parsed: Any) -> str:
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError:
        raise CofferAPIError("unavailable") from None
    if not isinstance(host, str) or not host:
        raise CofferAPIError("unavailable")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None:
        if REGISTRY_DNS_NAME.fullmatch(host) is None:
            raise CofferAPIError("unavailable")
        safe_host = host.lower()
    elif address.version == 6:
        safe_host = f"[{address.compressed}]"
    else:
        safe_host = address.compressed
    return f"{safe_host}:{port}" if port is not None else safe_host


def _endpoint(request: Any) -> str:
    try:
        endpoint = base.url_for(request, SERVICE_TYPE)
    except Exception:
        endpoint = None
    if not isinstance(endpoint, str):
        raise CofferAPIError("unavailable")
    endpoint = endpoint.rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith("/v1")
    ):
        raise CofferAPIError("unavailable")
    _registry_netloc(parsed)
    return endpoint


def registry_host(request: Any) -> str:
    """Return the credential-free OCI host:port from the catalog endpoint."""
    return _registry_netloc(urlsplit(_endpoint(request)))


def _new_adapter(request: Any, endpoint: str) -> adapter.Adapter:
    token = getattr(getattr(request.user, "token", None), "id", None)
    if not isinstance(token, str) or not token:
        raise CofferAPIError("authentication_required")
    auth = token_endpoint.Token(endpoint=endpoint, token=token)
    client_session = session.Session(auth=auth, verify=_verify_setting())
    return adapter.Adapter(
        session=client_session,
        service_type=SERVICE_TYPE,
        endpoint_override=endpoint,
    )


def _result_for_status(status: int | None) -> str:
    return {
        400: "invalid_request",
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
    }.get(status, "unavailable")


def _request(
    request: Any,
    method: str,
    path: str,
    *,
    params: dict[str, object] | None = None,
    document: dict[str, object] | None = None,
) -> object:
    endpoint = _endpoint(request)
    request_id = f"req-{uuid.uuid4()}"
    url = f"{endpoint}/{path.lstrip('/')}"
    response = None
    failure = None
    try:
        response = _new_adapter(request, endpoint).request(
            url,
            method,
            headers={"X-Openstack-Request-Id": request_id},
            params=params,
            json=document,
            timeout=REQUEST_TIMEOUT,
            connect_retries=0,
            status_code_retries=0,
            raise_exc=True,
        )
    except ksa_exceptions.http.HttpError as error:
        failure = CofferAPIError(_result_for_status(error.http_status))
    except (ksa_exceptions.ClientException, OSError, ValueError, TypeError):
        failure = CofferAPIError("unavailable")
    if failure is not None:
        raise failure
    invalid_json = False
    try:
        assert response is not None
        return response.json()
    except (TypeError, ValueError, AttributeError):
        invalid_json = True
    if invalid_json:
        raise CofferAPIError("invalid_response")
    raise AssertionError("unreachable Coffer response state")


def _repository(value: object, *, project_id: str) -> Repository:
    if not isinstance(value, dict) or set(value) != REPOSITORY_FIELDS:
        raise CofferAPIError("invalid_response")
    repository_id = _canonical_uuid(value["id"])
    actual_project_id = value["project_id"]
    name = value["name"]
    immutable_tags = value["immutable_tags"]
    created_at = value["created_at"]
    if actual_project_id != project_id:
        raise CofferAPIError("invalid_response")
    if (
        not isinstance(name, str)
        or len(name) > 255
        or REPOSITORY_NAME.fullmatch(name) is None
        or not isinstance(immutable_tags, bool)
        or not isinstance(created_at, str)
    ):
        raise CofferAPIError("invalid_response")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        parsed_created_at = None
    if parsed_created_at is None:
        raise CofferAPIError("invalid_response")
    if parsed_created_at.tzinfo is None or parsed_created_at.utcoffset() is None:
        raise CofferAPIError("invalid_response")
    return Repository(
        id=repository_id,
        project_id=actual_project_id,
        name=name,
        immutable_tags=immutable_tags,
        created_at=created_at,
    )


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise CofferAPIError("invalid_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.tzinfo is None
        or parsed.utcoffset() is None
    ):
        raise CofferAPIError("invalid_response")
    return value


def _artifact(
    value: object,
    *,
    project_id: str,
    repository_id: str,
) -> Artifact:
    if not isinstance(value, dict) or set(value) != ARTIFACT_FIELDS:
        raise CofferAPIError("invalid_response")
    if (
        value["project_id"] != project_id
        or value["repository_id"] != repository_id
    ):
        raise CofferAPIError("invalid_response")
    digest = value["digest"]
    media_type = value["media_type"]
    artifact_type = value["artifact_type"]
    kind = value["kind"]
    size_bytes = value["size_bytes"]
    tags = value["tags"]
    tag_count = value["tag_count"]
    tags_truncated = value["tags_truncated"]
    if (
        not isinstance(digest, str)
        or SHA256_DIGEST.fullmatch(digest) is None
        or not isinstance(media_type, str)
        or not 1 <= len(media_type) <= 255
        or (
            artifact_type is not None
            and (
                not isinstance(artifact_type, str)
                or not 1 <= len(artifact_type) <= 255
            )
        )
        or kind not in ARTIFACT_KINDS
        or isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or not 0 <= size_bytes <= MAX_LOGICAL_BYTES
        or not isinstance(tags, list)
        or len(tags) > MAX_ARTIFACT_PAGE_LIMIT
        or any(
            not isinstance(tag, str) or TAG_NAME.fullmatch(tag) is None
            for tag in tags
        )
        or isinstance(tag_count, bool)
        or not isinstance(tag_count, int)
        or tag_count < len(tags)
        or not isinstance(tags_truncated, bool)
        or tags_truncated != (tag_count > len(tags))
    ):
        raise CofferAPIError("invalid_response")
    return Artifact(
        project_id=project_id,
        repository_id=repository_id,
        digest=digest,
        media_type=media_type,
        artifact_type=artifact_type,
        kind=kind,
        size_bytes=size_bytes,
        pushed_at=_timestamp(value["pushed_at"]),
        updated_at=_timestamp(value["updated_at"]),
        tags=tuple(tags),
        tag_count=tag_count,
        tags_truncated=tags_truncated,
    )


def _quota(value: object, *, project_id: str) -> Quota:
    if not isinstance(value, dict) or set(value) != QUOTA_FIELDS:
        raise CofferAPIError("invalid_response")
    if value["project_id"] != project_id:
        raise CofferAPIError("invalid_response")
    byte_values = (
        value["limit_bytes"],
        value["used_bytes"],
        value["reserved_bytes"],
    )
    if any(
        isinstance(item, bool)
        or not isinstance(item, int)
        or not 0 <= item <= MAX_LOGICAL_BYTES
        for item in byte_values
    ):
        raise CofferAPIError("invalid_response")
    return Quota(
        project_id=project_id,
        limit_bytes=value["limit_bytes"],
        used_bytes=value["used_bytes"],
        reserved_bytes=value["reserved_bytes"],
    )


def list_repositories(
    request: Any,
    *,
    marker: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> RepositoryPage:
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_PAGE_LIMIT
    ):
        raise ValueError("repository limit is invalid")
    if marker is not None:
        _canonical_uuid(marker)
    project_id = _project_id(request)
    params: dict[str, object] = {"limit": limit}
    if marker is not None:
        params["marker"] = marker
    payload = _request(request, "GET", "repositories", params=params)
    if not isinstance(payload, dict) or set(payload) != {
        "repositories",
        "next_marker",
    }:
        raise CofferAPIError("invalid_response")
    items = payload["repositories"]
    if not isinstance(items, list) or len(items) > limit:
        raise CofferAPIError("invalid_response")
    repositories = tuple(_repository(item, project_id=project_id) for item in items)
    next_marker = payload["next_marker"]
    if next_marker is not None:
        _canonical_uuid(next_marker)
        if not repositories or repositories[-1].id != next_marker:
            raise CofferAPIError("invalid_response")
    return RepositoryPage(
        repositories=repositories,
        next_marker=next_marker,
    )


def create_repository(
    request: Any,
    *,
    name: str,
    immutable_tags: bool = False,
) -> Repository:
    if (
        not isinstance(name, str)
        or len(name) > 255
        or REPOSITORY_NAME.fullmatch(name) is None
        or not isinstance(immutable_tags, bool)
    ):
        raise ValueError("repository input is invalid")
    project_id = _project_id(request)
    payload = _request(
        request,
        "POST",
        "repositories",
        document={"name": name, "immutable_tags": immutable_tags},
    )
    if not isinstance(payload, dict) or set(payload) != {"repository"}:
        raise CofferAPIError("invalid_response")
    return _repository(payload["repository"], project_id=project_id)


def get_repository(request: Any, repository_id: str) -> Repository:
    repository_id = _canonical_uuid(repository_id)
    project_id = _project_id(request)
    payload = _request(request, "GET", f"repositories/{repository_id}")
    if not isinstance(payload, dict) or set(payload) != {"repository"}:
        raise CofferAPIError("invalid_response")
    return _repository(payload["repository"], project_id=project_id)


def list_artifacts(
    request: Any,
    repository_id: str,
    *,
    marker: str | None = None,
    query: str | None = None,
    limit: int = MAX_ARTIFACT_PAGE_LIMIT,
) -> ArtifactPage:
    repository_id = _canonical_uuid(repository_id)
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_ARTIFACT_PAGE_LIMIT
    ):
        raise ValueError("artifact limit is invalid")
    if marker is not None and (
        not isinstance(marker, str)
        or SHA256_DIGEST.fullmatch(marker) is None
    ):
        raise ValueError("artifact marker is invalid")
    if query is not None and (
        not isinstance(query, str)
        or not query
        or query.strip() != query
        or len(query) > MAX_ARTIFACT_QUERY_LENGTH
        or "\x00" in query
    ):
        raise ValueError("artifact query is invalid")
    project_id = _project_id(request)
    params: dict[str, object] = {"limit": limit}
    if marker is not None:
        params["marker"] = marker
    if query is not None:
        params["query"] = query
    payload = _request(
        request,
        "GET",
        f"repositories/{repository_id}/artifacts",
        params=params,
    )
    if not isinstance(payload, dict) or set(payload) != {
        "artifacts",
        "next_marker",
    }:
        raise CofferAPIError("invalid_response")
    items = payload["artifacts"]
    if not isinstance(items, list) or len(items) > limit:
        raise CofferAPIError("invalid_response")
    artifacts = tuple(
        _artifact(
            item,
            project_id=project_id,
            repository_id=repository_id,
        )
        for item in items
    )
    next_marker = payload["next_marker"]
    if next_marker is not None:
        if (
            not isinstance(next_marker, str)
            or SHA256_DIGEST.fullmatch(next_marker) is None
            or not artifacts
            or artifacts[-1].digest != next_marker
        ):
            raise CofferAPIError("invalid_response")
    return ArtifactPage(artifacts=artifacts, next_marker=next_marker)


def get_artifact(
    request: Any,
    repository_id: str,
    digest: str,
) -> Artifact:
    repository_id = _canonical_uuid(repository_id)
    if not isinstance(digest, str) or SHA256_DIGEST.fullmatch(digest) is None:
        raise ValueError("artifact digest is invalid")
    project_id = _project_id(request)
    payload = _request(
        request,
        "GET",
        f"repositories/{repository_id}/artifacts/{digest}",
    )
    if not isinstance(payload, dict) or set(payload) != {"artifact"}:
        raise CofferAPIError("invalid_response")
    return _artifact(
        payload["artifact"],
        project_id=project_id,
        repository_id=repository_id,
    )


def get_quota(request: Any) -> Quota:
    project_id = _project_id(request)
    payload = _request(request, "GET", "quota")
    if not isinstance(payload, dict) or set(payload) != {"quota"}:
        raise CofferAPIError("invalid_response")
    return _quota(payload["quota"], project_id=project_id)
