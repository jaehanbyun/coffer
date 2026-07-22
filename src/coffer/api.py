from __future__ import annotations

import re
from typing import Any

import falcon
from oslo_policy import policy

from coffer.db import RepositoryAlreadyExists, RepositoryStore
from coffer.identity import Identity


REPOSITORY_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$"
)


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
        resp.media = {
            "repositories": [
                repository.to_dict()
                for repository in self._store.list(identity.project_id)
            ]
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
