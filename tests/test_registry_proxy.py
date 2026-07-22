from __future__ import annotations

from coffer.registry_proxy import RegistryEdgeProxy


def test_generic_proxy_preserves_client_host_and_filters_hop_headers() -> None:
    headers = RegistryEdgeProxy._headers(
        {
            "HTTP_HOST": "registry.example:5000",
            "HTTP_AUTHORIZATION": "Bearer example",
            "HTTP_CONNECTION": "keep-alive",
            "CONTENT_TYPE": "application/octet-stream",
            "CONTENT_LENGTH": "17",
        }
    )

    assert headers == {
        "Host": "registry.example:5000",
        "Authorization": "Bearer example",
        "Content-Type": "application/octet-stream",
        "Content-Length": "17",
    }


def test_residual_percent_escape_is_rejected_before_backend_routing() -> None:
    application = RegistryEdgeProxy(lambda _env, _start: [], "http://registry:5000")
    response: dict[str, object] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        response["status"] = status
        response["headers"] = headers

    body = b"".join(
        application(
            {
                "PATH_INFO": "/v2/p%2Fproject%2Frepo%2Fmanifests%2Flatest",
                "REQUEST_METHOD": "PUT",
            },
            start_response,
        )
    )

    assert response["status"] == "400 Bad Request"
    assert b"NAME_INVALID" in body
