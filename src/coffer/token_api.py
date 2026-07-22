from __future__ import annotations

import logging
import time
from typing import Protocol
from urllib.parse import parse_qs
import uuid

import falcon

from coffer.credentials import (
    InvalidBasicCredentials,
    parse_basic_application_credential,
)
from coffer.keystone import (
    ApplicationCredentialPrincipal,
    InvalidApplicationCredential,
    KeystoneUnavailable,
)
from coffer.tokens import (
    AccessGrant,
    CredentialExpiresTooSoon,
    InvalidTokenRequest,
    TokenIssuer,
    TokenRequest,
    parse_token_request,
)


LOG = logging.getLogger(__name__)
MAX_QUERY_STRING_BYTES = 16 * 1024
MAX_QUERY_FIELDS = 32
BASIC_CHALLENGE = 'Basic realm="Coffer registry token"'


class Authenticator(Protocol):
    def authenticate(
        self, application_credential_id: str, application_credential_secret: str
    ) -> ApplicationCredentialPrincipal: ...


class ScopeAuthorizer(Protocol):
    def authorize(
        self,
        request: TokenRequest,
        principal: ApplicationCredentialPrincipal,
    ) -> tuple[AccessGrant, ...]: ...


class TokenMetrics(Protocol):
    def observe_token_decision(
        self, result: str, duration_seconds: float
    ) -> None: ...


class TokenRealmResource:
    def __init__(
        self,
        authenticator: Authenticator,
        scope_authorizer: ScopeAuthorizer,
        issuer: TokenIssuer,
        metrics: TokenMetrics | None = None,
    ) -> None:
        self._authenticator = authenticator
        self._scope_authorizer = scope_authorizer
        self._issuer = issuer
        self._metrics = metrics

    def _observe(self, result: str, started: float) -> None:
        if self._metrics is not None:
            self._metrics.observe_token_decision(
                result, max(0.0, time.monotonic() - started)
            )

    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        started = time.monotonic()
        request_id = f"req-{uuid.uuid4()}"
        resp.set_header("X-Openstack-Request-Id", request_id)
        resp.set_header("Cache-Control", "no-store")
        resp.set_header("Pragma", "no-cache")
        authorization = req.env.pop("HTTP_AUTHORIZATION", None)
        try:
            if len(req.query_string.encode("utf-8")) > MAX_QUERY_STRING_BYTES:
                raise InvalidTokenRequest("token request query is too large")
            parameters = parse_qs(
                req.query_string,
                keep_blank_values=True,
                max_num_fields=MAX_QUERY_FIELDS,
            )
            token_request = parse_token_request(
                parameters, expected_service=self._issuer.service
            )
        except (InvalidTokenRequest, ValueError):
            del authorization
            LOG.info(
                "Registry token decision request_id=%s result=invalid_request",
                request_id,
            )
            resp.status = falcon.HTTP_400
            resp.media = {"title": "Invalid token request"}
            self._observe("invalid_request", started)
            return

        try:
            basic = parse_basic_application_credential(authorization)
        except InvalidBasicCredentials:
            del authorization
            LOG.info(
                "Registry token decision request_id=%s result=invalid_credential",
                request_id,
            )
            resp.status = falcon.HTTP_401
            resp.set_header("WWW-Authenticate", BASIC_CHALLENGE)
            resp.media = {"title": "Authentication required"}
            self._observe("invalid_credential", started)
            return
        del authorization

        try:
            principal = self._authenticator.authenticate(
                basic.application_credential_id,
                basic.application_credential_secret,
            )
        except InvalidApplicationCredential:
            del basic
            LOG.info(
                "Registry token decision request_id=%s result=invalid_credential",
                request_id,
            )
            resp.status = falcon.HTTP_401
            resp.set_header("WWW-Authenticate", BASIC_CHALLENGE)
            resp.media = {"title": "Authentication required"}
            self._observe("invalid_credential", started)
            return
        except KeystoneUnavailable:
            del basic
            LOG.warning(
                "Registry token decision request_id=%s result=identity_unavailable",
                request_id,
            )
            resp.status = falcon.HTTP_503
            resp.media = {"title": "Identity service unavailable"}
            self._observe("identity_unavailable", started)
            return
        del basic

        access = self._scope_authorizer.authorize(token_request, principal)
        try:
            issued = self._issuer.issue(principal, access)
        except CredentialExpiresTooSoon:
            LOG.info(
                "Registry token decision request_id=%s project_id=%s user_id=%s "
                "audit_ids=%s result=credential_expires_too_soon",
                request_id,
                principal.project_id,
                principal.user_id,
                list(principal.audit_ids),
            )
            resp.status = falcon.HTTP_401
            resp.set_header("WWW-Authenticate", BASIC_CHALLENGE)
            resp.media = {"title": "Authentication required"}
            self._observe("credential_expires_too_soon", started)
            return

        LOG.info(
            "Registry token decision request_id=%(request_id)s jti=%(jti)s "
            "project_id=%(project_id)s user_id=%(user_id)s "
            "audit_ids=%(audit_ids)s requested=%(requested)s granted=%(granted)s "
            "result=issued",
            {
                "request_id": request_id,
                "jti": issued.jti,
                "project_id": principal.project_id,
                "user_id": principal.user_id,
                "audit_ids": list(principal.audit_ids),
                "requested": [
                    {"name": scope.name, "actions": list(scope.actions)}
                    for scope in token_request.scopes
                ],
                "granted": [grant.to_claim() for grant in issued.access],
            },
        )
        resp.media = issued.response()
        self._observe("issued", started)


def build_token_application(
    authenticator: Authenticator,
    scope_authorizer: ScopeAuthorizer,
    issuer: TokenIssuer,
    metrics: TokenMetrics | None = None,
) -> falcon.App:
    application = falcon.App()
    application.add_route(
        "/auth/token",
        TokenRealmResource(authenticator, scope_authorizer, issuer, metrics),
    )
    return application
