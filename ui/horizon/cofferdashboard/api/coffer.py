from __future__ import annotations

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
MAX_LOGICAL_BYTES = 2**63 - 1
REQUEST_TIMEOUT = (5, 30)
REPOSITORY_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
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
    if not isinstance(project_id, str) or not project_id or len(project_id) > 64:
        raise CofferAPIError("authentication_required")
    return project_id


def _verify_setting() -> bool | str:
    if getattr(settings, "OPENSTACK_SSL_NO_VERIFY", False):
        return False
    cacert = getattr(settings, "OPENSTACK_SSL_CACERT", None)
    return cacert or True


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
    return endpoint


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


def get_quota(request: Any) -> Quota:
    project_id = _project_id(request)
    payload = _request(request, "GET", "quota")
    if not isinstance(payload, dict) or set(payload) != {"quota"}:
        raise CofferAPIError("invalid_response")
    return _quota(payload["quota"], project_id=project_id)
