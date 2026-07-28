from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from osc_lib import exceptions

from cofferclient.client import Client, InvalidResponse, parse_endpoint_document
from cofferclient.osc import plugin
from cofferclient.osc.commands import login


ENDPOINT_DOCUMENT = {
    "version": {
        "id": "v1",
        "status": "CURRENT",
        "service_type": "oci-registry",
        "endpoints": {
            "control": "https://registry.example:18788/v1",
            "registry": "https://registry.example:18788/v2/",
            "token": "https://registry.example:18788/auth/token",
        },
    }
}


@dataclass
class Response:
    status_code: int
    document: object

    def json(self) -> object:
        return self.document


class Session:
    def __init__(self, responses: list[Response]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, url: str, method: str, **kwargs: object) -> Response:
        self.requests.append((url, method, kwargs))
        return self.responses.pop(0)


def test_client_discovers_exact_catalog_origin_and_calls_control_resources() -> None:
    session = Session(
        [
            Response(200, ENDPOINT_DOCUMENT),
            Response(
                201,
                {
                    "repository": {
                        "id": "repository-id",
                        "name": "team/app",
                    }
                },
            ),
            Response(
                200,
                {
                    "repositories": [{"id": "repository-id"}],
                    "next_marker": None,
                },
            ),
            Response(200, {"repository": {"id": "repository-id"}}),
            Response(
                200,
                {
                    "artifacts": [{"digest": f"sha256:{'a' * 64}"}],
                    "next_marker": None,
                },
            ),
            Response(
                200,
                {"artifact": {"digest": f"sha256:{'a' * 64}"}},
            ),
            Response(200, {"quota": {"limit_bytes": 100}}),
        ]
    )
    client = Client(session, "https://registry.example:18788/v1/")

    assert client.endpoints().registry.endswith("/v2/")
    assert client.create_repository(
        "team/app", immutable_tags=True
    )["name"] == "team/app"
    assert client.repositories(limit=10) == (
        ({"id": "repository-id"},),
        None,
    )
    assert client.repository("repository-id")["id"] == "repository-id"
    digest = f"sha256:{'a' * 64}"
    assert client.artifacts(
        "repository-id",
        limit=10,
        query="latest",
    ) == (({"digest": digest},), None)
    assert client.artifact("repository-id", digest)["digest"] == digest
    assert client.quota()["limit_bytes"] == 100
    assert [request[:2] for request in session.requests] == [
        ("https://registry.example:18788/v1", "GET"),
        ("https://registry.example:18788/v1/repositories", "POST"),
        ("https://registry.example:18788/v1/repositories", "GET"),
        ("https://registry.example:18788/v1/repositories/repository-id", "GET"),
        (
            "https://registry.example:18788/v1/repositories/"
            "repository-id/artifacts",
            "GET",
        ),
        (
            "https://registry.example:18788/v1/repositories/"
            f"repository-id/artifacts/{digest}",
            "GET",
        ),
        ("https://registry.example:18788/v1/quota", "GET"),
    ]
    assert all(request[2]["authenticated"] is True for request in session.requests)
    assert session.requests[1][2]["json"] == {
        "name": "team/app",
        "immutable_tags": True,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["version"].update({"id": "v2"}),
        lambda value: value["version"]["endpoints"].update(
            {"token": "https://other.example/auth/token"}
        ),
        lambda value: value["version"]["endpoints"].update(
            {"registry": "http://registry.example:18788/v2/"}
        ),
        lambda value: value["version"]["endpoints"].update(
            {"registry": "https://registry.example:18788/registry"}
        ),
        lambda value: value["version"]["endpoints"].update(
            {"token": "https://user@registry.example:18788/auth/token"}
        ),
    ),
)
def test_endpoint_discovery_rejects_unsupported_or_unsafe_links(
    mutate: Any,
) -> None:
    document = copy.deepcopy(ENDPOINT_DOCUMENT)
    mutate(document)
    with pytest.raises(InvalidResponse):
        parse_endpoint_document(document)


def test_client_errors_are_bounded_and_do_not_repeat_server_content() -> None:
    session = Session(
        [Response(503, {"description": "credential-secret-value"})]
    )
    with pytest.raises(exceptions.CommandError) as caught:
        Client(session, "https://registry.example/v1").quota()

    assert "503" in str(caught.value)
    assert "credential-secret-value" not in str(caught.value)


def test_openstackclient_plugin_uses_the_oci_registry_catalog_type() -> None:
    requested: list[tuple[str, dict[str, object]]] = []

    def endpoint(service_type: str, **kwargs: object) -> str:
        requested.append((service_type, kwargs))
        return "https://registry.example/v1"

    manager = SimpleNamespace(
        session=object(),
        interface="public",
        _region_name="RegionOne",
        get_endpoint_for_service_type=endpoint,
    )
    client = plugin.make_client(manager)

    assert isinstance(client, Client)
    assert requested == [
        (
            "oci-registry",
            {"interface": "public", "region_name": "RegionOne"},
        )
    ]


def test_login_passes_secret_only_on_stdin_and_never_through_a_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(
        "cofferclient.osc.commands.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    host = login(
        registry_endpoint="https://registry.example:18788/v2/",
        application_credential_id="app-credential-id",
        secret="credential-secret-value",
        executable="docker",
        runner=runner,
    )

    assert host == "registry.example:18788"
    command_line, kwargs = calls[0]
    assert command_line == [
        "/usr/bin/docker",
        "login",
        "--username",
        "app-credential-id",
        "--password-stdin",
        "registry.example:18788",
    ]
    assert kwargs == {
        "input": "credential-secret-value\n",
        "text": True,
        "check": True,
    }
    assert "credential-secret-value" not in " ".join(command_line)
    assert "shell" not in kwargs


def test_login_uses_helm_registry_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(
        "cofferclient.osc.commands.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    login(
        registry_endpoint="https://registry.example:18788/v2/",
        application_credential_id="app-credential-id",
        secret="credential-secret-value",
        executable="helm",
        runner=lambda command, **_kwargs: calls.append(command),
    )

    assert calls == [
        [
            "/usr/bin/helm",
            "registry",
            "login",
            "--username",
            "app-credential-id",
            "--password-stdin",
            "registry.example:18788",
        ]
    ]


def test_login_rejects_credentials_in_endpoint_and_multiline_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cofferclient.osc.commands.shutil.which",
        lambda value: f"/usr/bin/{value}",
    )
    with pytest.raises(exceptions.CommandError):
        login(
            registry_endpoint="https://user@registry.example/v2/",
            application_credential_id="id",
            secret="secret",
            executable="oras",
        )
    with pytest.raises(exceptions.CommandError, match="not supported"):
        login(
            registry_endpoint="https://registry.example/v2/",
            application_credential_id="id",
            secret="secret",
            executable="unknown",
        )
    with pytest.raises(exceptions.CommandError):
        login(
            registry_endpoint="https://registry.example/v2/",
            application_credential_id="id",
            secret="secret\nsecond",
            executable="oras",
        )


def test_project_metadata_declares_the_exact_openstackclient_commands() -> None:
    document = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '[project.entry-points."openstack.cli.extension"]' in document
    for command_name in (
        "registry_endpoint_show",
        "registry_artifact_list",
        "registry_artifact_show",
        "registry_login",
        "registry_quota_show",
        "registry_repository_create",
        "registry_repository_list",
        "registry_repository_show",
    ):
        assert f"{command_name} =" in document
