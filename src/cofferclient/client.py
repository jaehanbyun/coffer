from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from osc_lib import exceptions


class InvalidResponse(exceptions.CommandError):
    pass


@dataclass(frozen=True)
class EndpointSet:
    control: str
    registry: str
    token: str


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidResponse(f"Registry returned an invalid {label} document")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidResponse(f"Registry returned an invalid {label}")
    return value


def parse_endpoint_document(document: object) -> EndpointSet:
    root = _mapping(document, "endpoint")
    version = _mapping(root.get("version"), "version")
    if (
        version.get("id") != "v1"
        or version.get("status") != "CURRENT"
        or version.get("service_type") != "oci-registry"
    ):
        raise InvalidResponse("Registry returned an unsupported endpoint version")
    endpoints = _mapping(version.get("endpoints"), "endpoint set")
    result = EndpointSet(
        control=_string(endpoints.get("control"), "control endpoint"),
        registry=_string(endpoints.get("registry"), "registry endpoint"),
        token=_string(endpoints.get("token"), "token endpoint"),
    )
    parsed = {
        "control": urlsplit(result.control),
        "registry": urlsplit(result.registry),
        "token": urlsplit(result.token),
    }
    for label, value in parsed.items():
        try:
            port = value.port or 443
        except ValueError as exc:
            raise InvalidResponse(
                f"Registry returned an invalid {label} endpoint"
            ) from exc
        if (
            value.scheme != "https"
            or not value.hostname
            or value.username is not None
            or value.password is not None
            or value.query
            or value.fragment
        ):
            raise InvalidResponse(
                f"Registry returned an invalid {label} endpoint"
            )
        if port < 1 or port > 65535:
            raise InvalidResponse(
                f"Registry returned an invalid {label} endpoint"
            )
    origins = {
        (value.scheme, value.hostname, value.port or 443)
        for value in parsed.values()
    }
    if len(origins) != 1:
        raise InvalidResponse("Registry endpoints do not share one origin")
    expected_paths = {
        "control": "/v1",
        "registry": "/v2/",
        "token": "/auth/token",
    }
    if any(
        parsed[label].path != path for label, path in expected_paths.items()
    ):
        raise InvalidResponse("Registry returned unsupported endpoint paths")
    return result


class Client:
    def __init__(self, session: Any, endpoint: str) -> None:
        if not isinstance(endpoint, str) or not endpoint:
            raise exceptions.CommandError(
                "The oci-registry endpoint is missing from the service catalog"
            )
        self.session = session
        self.endpoint = endpoint.rstrip("/")

    def _request(
        self,
        method: str,
        path: str = "",
        *,
        json: Mapping[str, object] | None = None,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        response = self.session.request(
            f"{self.endpoint}{path}",
            method,
            authenticated=True,
            json=json,
            params=params,
            raise_exc=False,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise exceptions.CommandError(
                "Registry request failed with HTTP "
                f"{response.status_code}"
            )
        try:
            return _mapping(response.json(), "response")
        except (TypeError, ValueError) as exc:
            raise InvalidResponse(
                "Registry returned an invalid JSON response"
            ) from exc

    def endpoints(self) -> EndpointSet:
        return parse_endpoint_document(self._request("GET"))

    def create_repository(
        self,
        name: str,
        *,
        immutable_tags: bool = False,
    ) -> Mapping[str, object]:
        document = self._request(
            "POST",
            "/repositories",
            json={"name": name, "immutable_tags": immutable_tags},
        )
        return _mapping(document.get("repository"), "repository")

    def repositories(
        self,
        *,
        limit: int = 100,
        marker: str | None = None,
    ) -> tuple[tuple[Mapping[str, object], ...], str | None]:
        params: dict[str, object] = {"limit": limit}
        if marker is not None:
            params["marker"] = marker
        document = self._request("GET", "/repositories", params=params)
        raw_repositories = document.get("repositories")
        if not isinstance(raw_repositories, list):
            raise InvalidResponse("Registry returned an invalid repository page")
        repositories = tuple(
            _mapping(repository, "repository")
            for repository in raw_repositories
        )
        next_marker = document.get("next_marker")
        if next_marker is not None and not isinstance(next_marker, str):
            raise InvalidResponse("Registry returned an invalid next marker")
        return repositories, next_marker

    def repository(self, repository_id: str) -> Mapping[str, object]:
        document = self._request(
            "GET",
            f"/repositories/{repository_id}",
        )
        return _mapping(document.get("repository"), "repository")

    def quota(self) -> Mapping[str, object]:
        document = self._request("GET", "/quota")
        return _mapping(document.get("quota"), "quota")
