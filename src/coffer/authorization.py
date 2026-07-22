from __future__ import annotations

from oslo_policy import policy

from coffer.db import RepositoryStore
from coffer.keystone import ApplicationCredentialPrincipal
from coffer.tokens import AccessGrant, ACTION_ORDER, TokenRequest


REGISTRY_ROLES = frozenset({"reader", "member", "admin"})


class RegistryScopeAuthorizer:
    """Resolve requested registry scopes against control-plane authority."""

    def __init__(self, store: RepositoryStore, enforcer: policy.Enforcer) -> None:
        self._store = store
        self._enforcer = enforcer

    def authorize(
        self,
        request: TokenRequest,
        principal: ApplicationCredentialPrincipal,
    ) -> tuple[AccessGrant, ...]:
        credentials = principal.policy_credentials()
        credentials["roles"] = [
            role for role in principal.roles if role in REGISTRY_ROLES
        ]
        grants: list[AccessGrant] = []
        for scope in request.scopes:
            if scope.project_id != principal.project_id:
                continue
            repository = self._store.get_by_name(
                principal.project_id, scope.repository
            )
            if repository is None:
                continue
            target = {
                "project_id": principal.project_id,
                "repository_id": repository.id,
                "repository_name": repository.name,
            }
            granted_actions = tuple(
                action
                for action in ACTION_ORDER
                if action in scope.actions
                and self._enforcer.enforce(
                    f"registry:{action}", target, credentials
                )
            )
            if granted_actions:
                grants.append(
                    AccessGrant(
                        type=scope.type,
                        name=scope.name,
                        actions=granted_actions,
                    )
                )
        return tuple(grants)
