from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import falcon
from falcon import testing
from sqlalchemy.exc import SQLAlchemyError

from coffer.api import (
    MAX_REPOSITORY_LIMIT,
    MAX_REPOSITORY_NAME_LENGTH,
    REPOSITORY_NAME,
    REQUEST_ID,
    QuotaResource,
    RepositoryCollectionResource,
    RepositoryResource,
    RequestIdMiddleware,
)
from coffer.config import new_config
from coffer.db import Repository
from coffer.policy import RULES, create_enforcer
from coffer.quota import MAX_LOGICAL_BYTES, QuotaUsage


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "api-ref" / "openapi.json"
HTTP_METHODS = frozenset(
    {"delete", "get", "head", "options", "patch", "post", "put"}
)
EXPECTED_OPERATIONS = {
    ("/v1/repositories", "GET"): "repository:list",
    ("/v1/repositories", "POST"): "repository:create",
    ("/v1/repositories/{repository_id}", "GET"): "repository:get",
    ("/v1/quota", "GET"): "quota:get",
}
EXPECTED_RESPONSES = {
    ("/repositories", "get"): {"200", "400", "401", "403", "503"},
    ("/repositories", "post"): {"201", "400", "401", "403", "409", "503"},
    ("/repositories/{repository_id}", "get"): {
        "200",
        "401",
        "403",
        "404",
        "503",
    },
    ("/quota", "get"): {"200", "401", "403", "404", "503"},
}


def load_spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def resolve(spec: dict[str, object], reference: str) -> dict[str, object]:
    assert reference.startswith("#/")
    value: object = spec
    for component in reference.removeprefix("#/").split("/"):
        assert isinstance(value, dict)
        value = value[component]
    assert isinstance(value, dict)
    return value


def operations(
    spec: dict[str, object],
) -> dict[tuple[str, str], dict[str, object]]:
    result = {}
    paths = spec["paths"]
    assert isinstance(paths, dict)
    for path, path_item in paths.items():
        assert isinstance(path, str)
        assert isinstance(path_item, dict)
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            assert isinstance(operation, dict)
            result[(path, method)] = operation
    return result


def response_value(
    spec: dict[str, object],
    response: dict[str, object],
) -> dict[str, object]:
    reference = response.get("$ref")
    if reference is None:
        return response
    assert isinstance(reference, str)
    return resolve(spec, reference)


def test_openapi_is_version_relative_and_matches_control_policy_operations() -> None:
    spec = load_spec()
    assert spec["openapi"] == "3.1.0"
    assert spec["servers"] == [
        {
            "url": "/v1",
            "description": (
                "Versioned oci-registry endpoint from the Keystone service catalog."
            ),
        }
    ]
    assert spec["security"] == [{"keystoneToken": []}]

    documented = {
        (f"/v1{path}", method.upper()): operation["x-openstack-policy"]
        for (path, method), operation in operations(spec).items()
    }
    registered = {
        (item["path"], item["method"]): rule.name
        for rule in RULES
        for item in rule.operations
        if item["path"].startswith("/v1/")
    }
    assert documented == EXPECTED_OPERATIONS
    assert registered == EXPECTED_OPERATIONS


def test_openapi_methods_match_the_falcon_resource_callbacks() -> None:
    callbacks = {
        "/v1/repositories": {
            name.removeprefix("on_").upper()
            for name in vars(RepositoryCollectionResource)
            if name.startswith("on_")
        },
        "/v1/repositories/{repository_id}": {
            name.removeprefix("on_").upper()
            for name in vars(RepositoryResource)
            if name.startswith("on_")
        },
        "/v1/quota": {
            name.removeprefix("on_").upper()
            for name in vars(QuotaResource)
            if name.startswith("on_")
        },
    }
    implemented = {
        (path, method): EXPECTED_OPERATIONS[(path, method)]
        for path, methods in callbacks.items()
        for method in methods
    }
    assert implemented == EXPECTED_OPERATIONS


def test_openapi_response_classes_and_request_correlation_are_exact() -> None:
    spec = load_spec()
    for key, operation in operations(spec).items():
        responses = operation["responses"]
        assert isinstance(responses, dict)
        assert set(responses) == EXPECTED_RESPONSES[key]
        for status, raw_response in responses.items():
            assert isinstance(raw_response, dict)
            response = response_value(spec, raw_response)
            headers = response.get("headers", {})
            assert isinstance(headers, dict)
            if status == "401":
                assert set(headers) == {"WWW-Authenticate"}
            else:
                assert "X-Openstack-Request-Id" in headers


def test_openapi_repository_and_quota_schemas_match_runtime_values() -> None:
    spec = load_spec()
    components = spec["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    parameters = components["parameters"]
    headers = components["headers"]
    assert isinstance(schemas, dict)
    assert isinstance(parameters, dict)
    assert isinstance(headers, dict)

    repository = Repository(
        id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        project_id="project",
        name="team/application",
        immutable_tags=True,
        created_at=datetime(2026, 7, 26),
    )
    quota = QuotaUsage(
        project_id="project",
        limit_bytes=100,
        used_bytes=50,
        reserved_bytes=10,
    )
    assert set(schemas["Repository"]["required"]) == set(repository.to_dict())
    assert set(schemas["Quota"]["required"]) == set(quota.to_dict())
    assert schemas["Repository"]["properties"]["name"]["pattern"] == (
        REPOSITORY_NAME.pattern
    )
    assert (
        schemas["Repository"]["properties"]["name"]["maxLength"]
        == MAX_REPOSITORY_NAME_LENGTH
    )
    assert (
        schemas["CreateRepositoryRequest"]["properties"]["name"]["maxLength"]
        == MAX_REPOSITORY_NAME_LENGTH
    )
    assert parameters["RepositoryLimit"]["schema"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": MAX_REPOSITORY_LIMIT,
        "default": 100,
    }
    assert schemas["RepositoryPage"]["properties"]["repositories"]["maxItems"] == (
        MAX_REPOSITORY_LIMIT
    )
    for name in ("limit_bytes", "used_bytes", "reserved_bytes"):
        assert schemas["Quota"]["properties"][name]["maximum"] == MAX_LOGICAL_BYTES
    assert headers["RequestId"]["schema"]["pattern"] == REQUEST_ID.pattern


def test_every_local_reference_resolves_and_private_surfaces_are_absent() -> None:
    spec = load_spec()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                assert isinstance(reference, str)
                resolve(spec, reference)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(spec)
    paths = spec["paths"]
    assert isinstance(paths, dict)
    assert all(
        forbidden not in path
        for path in paths
        for forbidden in (
            "/auth/token",
            "/healthz",
            "/internal/",
            "/metrics",
            "/readyz",
            "/v2/",
        )
    )
    rendered = json.dumps(spec, sort_keys=True)
    assert "BEGIN PRIVATE KEY" not in rendered
    assert "password" not in rendered.lower()
    assert "secret" not in rendered.lower()


class _ProjectIdentity:
    def process_request(self, req: falcon.Request, _resp: falcon.Response) -> None:
        req.env.update(
            {
                "HTTP_X_IDENTITY_STATUS": "Confirmed",
                "HTTP_X_PROJECT_ID": "project",
                "HTTP_X_USER_ID": "user",
                "HTTP_X_ROLES": "reader",
                "keystone.token_auth": SimpleNamespace(
                    user=SimpleNamespace(
                        project_scoped=True,
                        project_id="project",
                    )
                ),
            }
        )


class _UnavailableRepositories:
    def list_page(self, *_args: object, **_kwargs: object) -> object:
        raise SQLAlchemyError("database connection contains sensitive material")


class _UnavailableQuota:
    def usage(self, _project_id: str) -> object:
        raise SQLAlchemyError("database connection contains sensitive material")


def test_known_control_dependency_failures_are_fixed_and_secret_safe() -> None:
    conf = new_config()
    conf(args=[])
    enforcer = create_enforcer(conf)
    application = falcon.App(
        middleware=[_ProjectIdentity(), RequestIdMiddleware()]
    )
    application.add_route(
        "/v1/repositories",
        RepositoryCollectionResource(_UnavailableRepositories(), enforcer),  # type: ignore[arg-type]
    )
    application.add_route(
        "/v1/quota",
        QuotaResource(_UnavailableQuota(), enforcer),  # type: ignore[arg-type]
    )
    client = testing.TestClient(application)

    for path in ("/v1/repositories", "/v1/quota"):
        result = client.simulate_get(path)
        assert result.status_code == 503
        assert result.json == {
            "title": "Control service unavailable",
            "description": "A required control dependency is unavailable.",
        }
        assert result.headers["x-openstack-request-id"].startswith("req-")
        assert "sensitive material" not in result.text
