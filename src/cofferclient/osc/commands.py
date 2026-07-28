from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import getpass
import os
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

from cliff import lister, show
from osc_lib import exceptions
from osc_lib.command import command

from cofferclient.client import Client


REPOSITORY_COLUMNS = (
    "id",
    "name",
    "project_id",
    "immutable_tags",
    "created_at",
)
QUOTA_COLUMNS = (
    "project_id",
    "limit_bytes",
    "used_bytes",
    "reserved_bytes",
)
ARTIFACT_COLUMNS = (
    "digest",
    "tags",
    "kind",
    "media_type",
    "artifact_type",
    "size_bytes",
    "pushed_at",
)
LOGIN_SUBCOMMANDS = {
    "docker": ("login",),
    "helm": ("registry", "login"),
    "oras": ("login",),
    "podman": ("login",),
}


def _values(
    document: Mapping[str, object],
    columns: Sequence[str],
) -> tuple[Any, ...]:
    return tuple(document.get(column) for column in columns)


def _client(osc_command: command.Command) -> Client:
    return osc_command.app.client_manager.registry


def login(
    *,
    registry_endpoint: str,
    application_credential_id: str,
    secret: str,
    executable: str,
    runner: Callable[..., Any] = subprocess.run,
) -> str:
    parsed = urlsplit(registry_endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path != "/v2/"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise exceptions.CommandError("Registry endpoint is not a safe HTTPS URL")
    if (
        not application_credential_id
        or len(application_credential_id) > 255
        or any(character.isspace() for character in application_credential_id)
    ):
        raise exceptions.CommandError(
            "A valid application credential ID is required"
        )
    if (
        not secret
        or len(secret) > 4096
        or "\x00" in secret
        or "\n" in secret
        or "\r" in secret
    ):
        raise exceptions.CommandError(
            "A single-line application credential secret is required"
        )
    subcommands = LOGIN_SUBCOMMANDS.get(executable)
    if subcommands is None:
        raise exceptions.CommandError("OCI client is not supported")
    program = shutil.which(executable)
    if program is None:
        raise exceptions.CommandError(f"{executable} is not installed")
    runner(
        [
            program,
            *subcommands,
            "--username",
            application_credential_id,
            "--password-stdin",
            parsed.netloc,
        ],
        input=f"{secret}\n",
        text=True,
        check=True,
    )
    return parsed.netloc


class ShowEndpoint(show.ShowOne):
    """Show the public control, token, and OCI endpoints."""

    def take_action(
        self,
        _parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        endpoints = _client(self).endpoints()
        columns = ("control", "registry", "token")
        return columns, tuple(getattr(endpoints, column) for column in columns)


class CreateRepository(show.ShowOne):
    """Create a project-scoped registry repository."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument("name", metavar="<name>")
        parser.add_argument(
            "--immutable-tags",
            action="store_true",
            help="Prevent an existing tag from being replaced.",
        )
        return parser

    def take_action(
        self,
        parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        repository = _client(self).create_repository(
            parsed_args.name,
            immutable_tags=parsed_args.immutable_tags,
        )
        return REPOSITORY_COLUMNS, _values(repository, REPOSITORY_COLUMNS)


class ListRepositories(lister.Lister):
    """List project-scoped registry repositories."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            choices=range(1, 1001),
            metavar="<1-1000>",
        )
        parser.add_argument("--marker", metavar="<repository-id>")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Follow all bounded repository pages.",
        )
        return parser

    def take_action(
        self,
        parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
        registry = _client(self)
        marker = parsed_args.marker
        seen_markers: set[str] = set()
        rows: list[tuple[Any, ...]] = []
        for _page in range(1000):
            repositories, next_marker = registry.repositories(
                limit=parsed_args.limit,
                marker=marker,
            )
            rows.extend(
                _values(repository, REPOSITORY_COLUMNS)
                for repository in repositories
            )
            if not parsed_args.all or next_marker is None:
                return REPOSITORY_COLUMNS, tuple(rows)
            if next_marker in seen_markers:
                raise exceptions.CommandError(
                    "Registry repeated a repository page marker"
                )
            seen_markers.add(next_marker)
            marker = next_marker
        raise exceptions.CommandError("Registry pagination exceeded 1000 pages")


class ShowRepository(show.ShowOne):
    """Show one project-scoped registry repository."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository-id>")
        return parser

    def take_action(
        self,
        parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        repository = _client(self).repository(parsed_args.repository)
        return REPOSITORY_COLUMNS, _values(repository, REPOSITORY_COLUMNS)


class ListArtifacts(lister.Lister):
    """List digest-addressed artifacts in one project repository."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository-id>")
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            choices=range(1, 101),
            metavar="<1-100>",
        )
        parser.add_argument("--marker", metavar="<artifact-digest>")
        parser.add_argument("--query", metavar="<tag-or-digest>")
        parser.add_argument(
            "--all",
            action="store_true",
            help="Follow all bounded artifact pages.",
        )
        return parser

    def take_action(
        self,
        parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[tuple[Any, ...], ...]]:
        registry = _client(self)
        marker = parsed_args.marker
        seen_markers: set[str] = set()
        rows: list[tuple[Any, ...]] = []
        for _page in range(10_000):
            artifacts, next_marker = registry.artifacts(
                parsed_args.repository,
                limit=parsed_args.limit,
                marker=marker,
                query=parsed_args.query,
            )
            rows.extend(
                _values(artifact, ARTIFACT_COLUMNS)
                for artifact in artifacts
            )
            if not parsed_args.all or next_marker is None:
                return ARTIFACT_COLUMNS, tuple(rows)
            if next_marker in seen_markers:
                raise exceptions.CommandError(
                    "Registry repeated an artifact page marker"
                )
            seen_markers.add(next_marker)
            marker = next_marker
        raise exceptions.CommandError(
            "Registry artifact pagination exceeded 10000 pages"
        )


class ShowArtifact(show.ShowOne):
    """Show one digest-addressed repository artifact."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument("repository", metavar="<repository-id>")
        parser.add_argument("digest", metavar="<sha256-digest>")
        return parser

    def take_action(
        self,
        parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        artifact = _client(self).artifact(
            parsed_args.repository,
            parsed_args.digest,
        )
        return ARTIFACT_COLUMNS, _values(artifact, ARTIFACT_COLUMNS)


class ShowQuota(show.ShowOne):
    """Show registry quota and usage for the scoped project."""

    def take_action(
        self,
        _parsed_args: Any,
    ) -> tuple[tuple[str, ...], tuple[Any, ...]]:
        quota = _client(self).quota()
        return QUOTA_COLUMNS, _values(quota, QUOTA_COLUMNS)


class Login(command.Command):
    """Authenticate an OCI client with a finite application credential."""

    def get_parser(self, prog_name: str) -> Any:
        parser = super().get_parser(prog_name)
        parser.add_argument(
            "--application-credential-id",
            default=os.environ.get("OS_APPLICATION_CREDENTIAL_ID"),
            metavar="<application-credential-id>",
            help=(
                "Finite project-scoped application credential ID. "
                "(Env: OS_APPLICATION_CREDENTIAL_ID)"
            ),
        )
        parser.add_argument(
            "--client",
            choices=tuple(LOGIN_SUBCOMMANDS),
            default="docker",
        )
        return parser

    def take_action(self, parsed_args: Any) -> None:
        if sys.stdin.isatty():
            secret = getpass.getpass("Application credential secret: ")
        else:
            secret = sys.stdin.read(4097).removesuffix("\n")
        endpoints = _client(self).endpoints()
        try:
            host = login(
                registry_endpoint=endpoints.registry,
                application_credential_id=parsed_args.application_credential_id,
                secret=secret,
                executable=parsed_args.client,
            )
        except subprocess.CalledProcessError as exc:
            raise exceptions.CommandError(
                f"{parsed_args.client} login failed"
            ) from exc
        finally:
            secret = ""
        self.app.stdout.write(
            f"Authenticated {parsed_args.client} to {host}\n"
        )
