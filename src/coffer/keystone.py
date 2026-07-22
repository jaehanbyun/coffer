from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from keystoneauth1 import exceptions as keystone_exceptions
from keystoneauth1 import session as keystone_session
from keystoneauth1.identity import v3
from oslo_config import cfg
from oslo_log import log


LOG = log.getLogger(__name__)


class InvalidApplicationCredential(Exception):
    """The credential was rejected or produced an unusable project identity."""


class KeystoneUnavailable(Exception):
    """Keystone could not complete authentication."""


@dataclass(frozen=True, slots=True)
class ApplicationCredentialPrincipal:
    application_credential_id: str
    user_id: str
    project_id: str
    roles: tuple[str, ...]
    expires_at: datetime
    audit_ids: tuple[str, ...]

    def policy_credentials(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "project_id": self.project_id,
            "roles": list(self.roles),
        }


PluginFactory = Callable[..., Any]
SessionFactory = Callable[..., Any]


def _discarded_exchange_error(error_type: type[Exception], message: str) -> Exception:
    """Create a mapped error without retaining the Keystone exception graph."""

    return error_type(message)


class ApplicationCredentialAuthenticator:
    """Authenticate one finite application credential without retaining its secret."""

    __slots__ = (
        "_auth_url",
        "_plugin_factory",
        "_session_factory",
        "_timeout",
        "_verify",
    )

    def __init__(
        self,
        *,
        auth_url: str,
        verify: bool | str,
        timeout: float,
        plugin_factory: PluginFactory = v3.ApplicationCredential,
        session_factory: SessionFactory = keystone_session.Session,
    ) -> None:
        if not auth_url:
            raise ValueError("Keystone auth_url is required")
        self._auth_url = auth_url
        self._verify = verify
        self._timeout = timeout
        self._plugin_factory = plugin_factory
        self._session_factory = session_factory

    def authenticate(
        self, application_credential_id: str, application_credential_secret: str
    ) -> ApplicationCredentialPrincipal:
        if not application_credential_id or not application_credential_secret:
            del application_credential_secret
            raise InvalidApplicationCredential("application credential is required")

        access, exchange_error = self._exchange(
            application_credential_id, application_credential_secret
        )
        del application_credential_secret
        if exchange_error is not None:
            raise exchange_error
        assert access is not None

        access_rules = getattr(
            access, "application_credential_access_rules", None
        )
        if access_rules is not None:
            raise InvalidApplicationCredential(
                "application credentials with access rules are not supported"
            )

        authenticated_id = access.application_credential_id
        if authenticated_id != application_credential_id:
            raise InvalidApplicationCredential(
                "authenticated application credential does not match the request"
            )
        if not access.project_scoped or not access.project_id:
            raise InvalidApplicationCredential(
                "application credential must produce a project-scoped token"
            )
        if not access.user_id or access.expires is None:
            raise InvalidApplicationCredential("Keystone identity response is incomplete")

        audit_ids = tuple(
            audit_id
            for audit_id in (access.audit_id, access.audit_chain_id)
            if audit_id
        )
        principal = ApplicationCredentialPrincipal(
            application_credential_id=authenticated_id,
            user_id=access.user_id,
            project_id=access.project_id,
            roles=tuple(access.role_names),
            expires_at=access.expires,
            audit_ids=audit_ids,
        )
        LOG.info(
            "Authenticated application credential %(credential_id)s for project "
            "%(project_id)s and user %(user_id)s",
            {
                "credential_id": principal.application_credential_id,
                "project_id": principal.project_id,
                "user_id": principal.user_id,
            },
        )
        return principal

    def _exchange(
        self, application_credential_id: str, application_credential_secret: str
    ) -> tuple[Any | None, Exception | None]:
        """Contain dependency exceptions and the request-local secret in one frame."""

        try:
            plugin = self._plugin_factory(
                auth_url=self._auth_url,
                application_credential_id=application_credential_id,
                application_credential_secret=application_credential_secret,
                include_catalog=False,
            )
            session = self._session_factory(
                auth=plugin,
                verify=self._verify,
                timeout=self._timeout,
                app_name="coffer",
                app_version="0.1.0",
            )
            access = plugin.get_access(session)
        except (
            keystone_exceptions.ConnectFailure,
            keystone_exceptions.DiscoveryFailure,
            keystone_exceptions.RequestTimeout,
        ):
            LOG.error(
                "Keystone unavailable during application-credential authentication"
            )
            return None, _discarded_exchange_error(
                KeystoneUnavailable, "Keystone authentication unavailable"
            )
        except (
            keystone_exceptions.Unauthorized,
            keystone_exceptions.AuthorizationFailure,
            keystone_exceptions.NotFound,
        ):
            LOG.warning("Keystone rejected application credential")
            return None, _discarded_exchange_error(
                InvalidApplicationCredential,
                "application credential was rejected",
            )
        except keystone_exceptions.ClientException:
            LOG.error("Keystone application-credential authentication failed")
            return None, _discarded_exchange_error(
                KeystoneUnavailable, "Keystone authentication unavailable"
            )
        except Exception:
            LOG.error("Unexpected Keystone application-credential authentication failure")
            return None, _discarded_exchange_error(
                KeystoneUnavailable, "Keystone authentication unavailable"
            )
        return access, None


def create_authenticator(conf: cfg.ConfigOpts) -> ApplicationCredentialAuthenticator:
    if conf.keystone.insecure:
        verify: bool | str = False
    else:
        verify = conf.keystone.cafile or True
    return ApplicationCredentialAuthenticator(
        auth_url=conf.keystone.auth_url,
        verify=verify,
        timeout=conf.keystone.timeout,
    )
