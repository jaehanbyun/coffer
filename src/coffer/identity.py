from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import falcon


@dataclass(frozen=True, slots=True)
class Identity:
    project_id: str
    user_id: str
    roles: tuple[str, ...]

    @classmethod
    def from_environ(cls, environ: dict[str, Any]) -> "Identity":
        if environ.get("HTTP_X_IDENTITY_STATUS") != "Confirmed":
            raise falcon.HTTPUnauthorized()

        token_auth = environ.get("keystone.token_auth")
        user_auth = getattr(token_auth, "user", None)
        if not getattr(user_auth, "project_scoped", False):
            raise falcon.HTTPForbidden(
                title="Project scope required",
                description=(
                    "Coffer repository operations require a project-scoped token."
                ),
            )

        project_id = environ.get("HTTP_X_PROJECT_ID")
        if not project_id or getattr(user_auth, "project_id", None) != project_id:
            raise falcon.HTTPForbidden(title="Project scope required")

        user_id = environ.get("HTTP_X_USER_ID")
        if not user_id:
            raise falcon.HTTPUnauthorized()

        roles = tuple(
            role.strip()
            for role in environ.get("HTTP_X_ROLES", "").split(",")
            if role.strip()
        )
        return cls(
            project_id=project_id,
            user_id=user_id,
            roles=roles,
        )

    def policy_credentials(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "user_id": self.user_id,
            "roles": list(self.roles),
        }
