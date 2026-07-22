from __future__ import annotations

from collections.abc import Iterator, Mapping
import http.client
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


class HTTPManifestUpstream:
    def __init__(self, upstream_url: str, *, timeout_seconds: float = 15.0) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("the PoC manifest upstream must be one HTTP origin")
        self._host = parsed.hostname
        self._port = parsed.port or 80
        self._timeout = timeout_seconds

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
            if name.lower() not in HOP_BY_HOP | {"content-length", "content-type"}
        }
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
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
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
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
    """Stream non-manifest registry traffic and isolate manifest admission."""

    def __init__(
        self,
        manifest_application: Any,
        upstream_url: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        parsed = urlsplit(upstream_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("the PoC registry upstream must be one HTTP origin")
        self._manifest_application = manifest_application
        self._host = parsed.hostname
        self._port = parsed.port or 80
        self._timeout = timeout_seconds

    @staticmethod
    def _is_manifest_put(environ: Mapping[str, Any]) -> bool:
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

    def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
        if self._has_residual_escape(environ):
            start_response(
                "400 Bad Request",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(ENCODED_PATH_ERROR))),
                ],
            )
            return [ENCODED_PATH_ERROR]
        if self._is_manifest_put(environ):
            return self._manifest_application(environ, start_response)

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

        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
        try:
            connection.request(
                method,
                target,
                body=body,
                headers=headers,
                encode_chunked=encode_chunked,
            )
            response = connection.getresponse()
        except BaseException:
            connection.close()
            raise
        response_headers = [
            (name, value)
            for name, value in response.getheaders()
            if name.lower() not in HOP_BY_HOP
        ]
        start_response(f"{response.status} {response.reason}", response_headers)
        return _ProxyBody(response, connection)
