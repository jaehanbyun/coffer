from __future__ import annotations

import re
from typing import Any

import falcon
from oslo_policy import policy

from coffer.db import (
    InvalidRepositoryMarker,
    RepositoryAlreadyExists,
    RepositoryStore,
)
from coffer.identity import Identity
from coffer.quota import QuotaNotConfigured, QuotaStore


REPOSITORY_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)
DEFAULT_REPOSITORY_LIMIT = 100
MAX_REPOSITORY_LIMIT = 1000


def _authorize(
    enforcer: policy.Enforcer,
    rule: str,
    identity: Identity,
    target: dict[str, Any],
) -> None:
    if not enforcer.enforce(rule, target, identity.policy_credentials()):
        raise falcon.HTTPForbidden()


class RepositoryCollectionResource:
    def __init__(self, store: RepositoryStore, enforcer: policy.Enforcer) -> None:
        self._store = store
        self._enforcer = enforcer

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        identity = Identity.from_environ(req.env)
        target = {"project_id": identity.project_id}
        _authorize(self._enforcer, "repository:create", identity, target)

        document = req.get_media()
        if not isinstance(document, dict):
            raise falcon.HTTPBadRequest(title="JSON object required")
        name = document.get("name")
        if not isinstance(name, str) or not REPOSITORY_NAME.fullmatch(name):
            raise falcon.HTTPBadRequest(
                title="Invalid repository name",
                description=(
                    "Use lowercase alphanumeric path components separated by '/', "
                    "with '.', '_' or '-' inside a component."
                ),
            )

        immutable_tags = document.get("immutable_tags", False)
        if not isinstance(immutable_tags, bool):
            raise falcon.HTTPBadRequest(title="immutable_tags must be a boolean")

        try:
            repository = self._store.create(
                identity.project_id, name, immutable_tags=immutable_tags
            )
        except RepositoryAlreadyExists as exc:
            raise falcon.HTTPConflict(
                title="Repository already exists",
                description=f"Repository {exc.args[0]!r} already exists in this project.",
            ) from exc

        resp.status = falcon.HTTP_201
        resp.location = f"/v1/repositories/{repository.id}"
        resp.media = {"repository": repository.to_dict()}

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        identity = Identity.from_environ(req.env)
        target = {"project_id": identity.project_id}
        _authorize(self._enforcer, "repository:list", identity, target)
        limit = req.get_param_as_int(
            "limit",
            required=False,
            min_value=1,
            max_value=MAX_REPOSITORY_LIMIT,
        )
        marker = req.get_param("marker", required=False)
        try:
            page = self._store.list_page(
                identity.project_id,
                limit=limit or DEFAULT_REPOSITORY_LIMIT,
                marker=marker,
            )
        except InvalidRepositoryMarker as exc:
            raise falcon.HTTPBadRequest(
                title="Invalid repository marker",
                description=(
                    "The marker must identify a repository in the current project."
                ),
            ) from exc
        resp.media = {
            "repositories": [
                repository.to_dict()
                for repository in page.repositories
            ],
            "next_marker": page.next_marker,
        }


class RepositoryResource:
    def __init__(self, store: RepositoryStore, enforcer: policy.Enforcer) -> None:
        self._store = store
        self._enforcer = enforcer

    def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        repository_id: str,
    ) -> None:
        identity = Identity.from_environ(req.env)
        target = {
            "project_id": identity.project_id,
            "repository_id": repository_id,
        }
        _authorize(self._enforcer, "repository:get", identity, target)
        repository = self._store.get(identity.project_id, repository_id)
        if repository is None:
            raise falcon.HTTPNotFound()
        resp.media = {"repository": repository.to_dict()}


class QuotaResource:
    def __init__(self, store: QuotaStore, enforcer: policy.Enforcer) -> None:
        self._store = store
        self._enforcer = enforcer

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        identity = Identity.from_environ(req.env)
        target = {"project_id": identity.project_id}
        _authorize(self._enforcer, "quota:get", identity, target)
        try:
            usage = self._store.usage(identity.project_id)
        except QuotaNotConfigured as exc:
            raise falcon.HTTPNotFound(
                title="Quota not configured",
                description=(
                    "No registry quota is configured for the current project."
                ),
            ) from exc
        resp.media = {"quota": usage.to_dict()}
