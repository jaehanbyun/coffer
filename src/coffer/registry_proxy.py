from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
import http.client
import ipaddress
import re
import ssl
from typing import Any
from urllib.parse import urlsplit

from coffer.quota_admission import (
    DescriptorNotAuthorized,
    DescriptorNotFound,
    UpstreamResponse,
)


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
ENCODED_PATH_ERROR = (
    b'{"errors":[{"code":"NAME_INVALID",'
    b'"message":"encoded registry path is not allowed"}]}'
)
ROUTE_NOT_FOUND = (
    b'{"errors":[{"code":"NOT_FOUND","message":"route not found"}]}'
)
UPSTREAM_UNAVAILABLE = (
    b'{"errors":[{"code":"UNAVAILABLE",'
    b'"message":"upstream dependency unavailable"}]}'
)
MANIFEST_PUT = re.compile(r"/v2/(.+)/manifests/([^/]+)")
MANIFEST_PATH_ERROR = (
    b'{"errors":[{"code":"MANIFEST_INVALID",'
    b'"message":"manifest route is invalid"}]}'
)


def _is_loopback(hostname: str | None) -> bool:
    if hostname is None:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class UpstreamOrigin:
    scheme: str
    host: str
    port: int
    timeout_seconds: float
    ssl_context: ssl.SSLContext | None

    @classmethod
    def from_url(
        cls,
        upstream_url: str,
        *,
        label: str,
        timeout_seconds: float,
        cafile: str | None = None,
        allow_insecure_http: bool = False,
        allow_non_loopback_fixture: bool = False,
    ) -> UpstreamOrigin:
        parsed = urlsplit(upstream_url)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ValueError(f"{label} origin has an invalid port") from exc
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{label} must be one credential-free origin")
        if parsed.scheme == "https":
            context = ssl.create_default_context(cafile=cafile)
            port = parsed_port or 443
        elif parsed.scheme == "http":
            if not allow_insecure_http:
                raise ValueError(
                    f"plaintext {label} requires the explicit fixture switch"
                )
            if not _is_loopback(parsed.hostname) and not allow_non_loopback_fixture:
                raise ValueError(
                    f"plaintext {label} is restricted to loopback fixtures"
                )
            if cafile:
                raise ValueError(f"{label} CA file requires an HTTPS origin")
            context = None
            port = parsed_port or 80
        else:
            raise ValueError(f"{label} must use HTTP(S)")
        return cls(
            scheme=parsed.scheme,
            host=parsed.hostname,
            port=port,
            timeout_seconds=timeout_seconds,
            ssl_context=context,
        )

    def connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            )
        return http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=self.timeout_seconds,
        )


class HTTPManifestUpstream:
    def __init__(self, origin: UpstreamOrigin) -> None:
        self._origin = origin

    def descriptor_size(
        self,
        *,
        repository: str,
        digest: str,
        manifest: bool,
        headers: Mapping[str, str],
    ) -> int:
        kind = "manifests" if manifest else "blobs"
        forwarded = {
            name: value
            for name, value in headers.items()
            if name.lower() not in HOP_BY_HOP
            | {"content-length", "content-type"}
        }
        connection = self._origin.connect()
        try:
            connection.request(
                "HEAD", f"/v2/{repository}/{kind}/{digest}", headers=forwarded
            )
            response = connection.getresponse()
            try:
                if response.status in {401, 403}:
                    raise DescriptorNotAuthorized(digest)
                if response.status == 404:
                    raise DescriptorNotFound(digest)
                if response.status != 200:
                    raise OSError(
                        f"descriptor metadata returned HTTP {response.status}"
                    )
                content_length = response.getheader("Content-Length")
                if content_length is None:
                    raise OSError("descriptor metadata omitted Content-Length")
                size = int(content_length)
                if size < 0:
                    raise OSError("descriptor metadata returned a negative size")
                return size
            finally:
                response.read()
        finally:
            connection.close()

    def put_manifest(
        self,
        *,
        repository: str,
        reference: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> UpstreamResponse:
        connection = self._origin.connect()
        forwarded = {
            name: value
            for name, value in headers.items()
            if name.lower() not in HOP_BY_HOP | {"content-length"}
        }
        forwarded["Content-Length"] = str(len(body))
        try:
            connection.request(
                "PUT",
                f"/v2/{repository}/manifests/{reference}",
                body=body,
                headers=forwarded,
            )
            response = connection.getresponse()
            return UpstreamResponse(
                status=response.status,
                headers=tuple(response.getheaders()),
                body=response.read(),
            )
        finally:
            connection.close()


class _ProxyBody:
    def __init__(
        self,
        response: http.client.HTTPResponse,
        connection: http.client.HTTPConnection,
    ) -> None:
        self._response = response
        self._connection = connection

    def __iter__(self) -> Iterator[bytes]:
        try:
            while chunk := self._response.read(64 * 1024):
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        self._response.close()
        self._connection.close()


class RegistryEdgeProxy:
    """Closed, streaming router with isolated manifest admission."""

    def __init__(
        self,
        manifest_application: Any,
        registry_origin: UpstreamOrigin,
        *,
        api_origin: UpstreamOrigin | None = None,
    ) -> None:
        self._manifest_application = manifest_application
        self._registry_origin = registry_origin
        self._api_origin = api_origin

    @staticmethod
    def _is_manifest_put(environ: Mapping[str, Any]) -> bool:
        path = environ.get("PATH_INFO", "")
        return (
            environ.get("REQUEST_METHOD") == "PUT"
            and isinstance(path, str)
            and MANIFEST_PUT.fullmatch(path) is not None
        )

    @staticmethod
    def _is_manifest_put_candidate(environ: Mapping[str, Any]) -> bool:
        path = environ.get("PATH_INFO", "")
        return (
            environ.get("REQUEST_METHOD") == "PUT"
            and isinstance(path, str)
            and path.startswith("/v2/")
            and "/manifests/" in path
        )

    @staticmethod
    def _has_residual_escape(environ: Mapping[str, Any]) -> bool:
        path = environ.get("PATH_INFO", "")
        return isinstance(path, str) and "%" in path

    @staticmethod
    def _headers(environ: Mapping[str, Any]) -> dict[str, str]:
        headers: dict[str, str] = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                name = key[5:].replace("_", "-").title()
                if name.lower() not in HOP_BY_HOP:
                    headers[name] = str(value)
        if environ.get("CONTENT_TYPE"):
            headers["Content-Type"] = str(environ["CONTENT_TYPE"])
        if environ.get("CONTENT_LENGTH"):
            headers["Content-Length"] = str(environ["CONTENT_LENGTH"])
        return headers

    @staticmethod
    def _chunked_body(stream: Any) -> Iterator[bytes]:
        while chunk := stream.read(64 * 1024):
            yield chunk

    @staticmethod
    def _fixed_response(
        start_response: Any,
        status: str,
        body: bytes,
        *,
        retry_after: str | None = None,
    ) -> list[bytes]:
        headers = [
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
        ]
        if retry_after is not None:
            headers.append(("Retry-After", retry_after))
        start_response(status, headers)
        return [body]

    @staticmethod
    def _origin_for_path(
        path: str,
        *,
        api_origin: UpstreamOrigin | None,
        registry_origin: UpstreamOrigin,
    ) -> UpstreamOrigin | None:
        if path == "/auth/token" or path == "/v1" or path.startswith("/v1/"):
            return api_origin
        if path == "/v2" or path.startswith("/v2/"):
            return registry_origin
        return None

    def _proxy(
        self,
        environ: dict[str, Any],
        start_response: Any,
        origin: UpstreamOrigin,
    ) -> Any:
        target = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        if query:
            target = f"{target}?{query}"
        method = environ.get("REQUEST_METHOD", "GET")
        headers = self._headers(environ)
        content_length = headers.get("Content-Length")
        body: Any = None
        encode_chunked = False
        if method in {"POST", "PUT", "PATCH"}:
            body = environ["wsgi.input"]
            if content_length is None:
                body = self._chunked_body(body)
                encode_chunked = True

        connection = origin.connect()
        try:
            connection.request(
                method,
                target,
                body=body,
                headers=headers,
                encode_chunked=encode_chunked,
            )
            response = connection.getresponse()
        except Exception:
            connection.close()
            return self._fixed_response(
                start_response,
                "503 Service Unavailable",
                UPSTREAM_UNAVAILABLE,
                retry_after="5",
            )
        response_headers = [
            (name, value)
            for name, value in response.getheaders()
            if name.lower() not in HOP_BY_HOP
        ]
        try:
            reason = HTTPStatus(response.status).phrase
        except ValueError:
            reason = "Unknown"
        start_response(f"{response.status} {reason}", response_headers)
        return _ProxyBody(response, connection)

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
        if self._has_residual_escape(environ):
            return self._fixed_response(
                start_response, "400 Bad Request", ENCODED_PATH_ERROR
            )
        if self._is_manifest_put(environ):
            return self._manifest_application(environ, start_response)
        if self._is_manifest_put_candidate(environ):
            return self._fixed_response(
                start_response, "400 Bad Request", MANIFEST_PATH_ERROR
            )

        path = environ.get("PATH_INFO", "")
        if not isinstance(path, str):
            path = ""
        origin = self._origin_for_path(
            path,
            api_origin=self._api_origin,
            registry_origin=self._registry_origin,
        )
        if origin is None:
            return self._fixed_response(
                start_response, "404 Not Found", ROUTE_NOT_FOUND
            )
        return self._proxy(environ, start_response, origin)
