from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from falcon import testing
from keystoneauth1 import loading

from coffer.config import new_config
from coffer.db import RepositoryStore
from coffer.wsgi import build_application


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-url", required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--fixture-file", type=Path, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--database-file", type=Path, required=True)
    return parser.parse_args()


def middleware_config(
    args: argparse.Namespace,
    credential_id: str,
    credential_secret: str,
    *,
    auth_url: str | None = None,
) -> dict[str, object]:
    endpoint = auth_url or args.auth_url
    return {
        "www_authenticate_uri": endpoint,
        "auth_url": endpoint,
        "auth_type": "v3applicationcredential",
        "application_credential_id": credential_id,
        "application_credential_secret": credential_secret,
        "cafile": str(args.ca_file),
        "delay_auth_decision": False,
        "include_service_catalog": False,
        "interface": "public",
        "service_type": "oci-registry",
        "service_token_roles": "service",
        "service_token_roles_required": True,
        "token_cache_time": 2,
        "http_connect_timeout": 1.0,
        "http_request_max_retries": 0,
    }


def client_for(config: dict[str, object], database_file: Path) -> testing.TestClient:
    conf = new_config()
    conf(args=[])
    plugin_loader = loading.get_plugin_loader(str(config["auth_type"]))
    conf.register_opts(
        loading.get_auth_plugin_conf_options(plugin_loader),
        group="keystone_authtoken",
    )
    for name, value in config.items():
        conf.set_override(name, value, group="keystone_authtoken")
    middleware = build_application(
        conf,
        store=RepositoryStore(f"sqlite:///{database_file}"),
    )

    def wsgi_app(environ: dict[str, Any], start_response: Any) -> Any:
        return middleware(environ, start_response)

    return testing.TestClient(wsgi_app)


def revoke_project_token(instance: str) -> None:
    subprocess.run(
        [
            "limactl",
            "shell",
            instance,
            "/tmp/guest-verify.sh",
            "revoke-control-project-token",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> None:
    args = parse_args()
    fixture = json.loads(args.fixture_file.read_text())
    project_token = fixture.pop("project_token")
    domain_token = fixture.pop("domain_token")
    system_token = fixture.pop("system_token")
    service_token = fixture.pop("service_token")
    credential_id = fixture.pop("service_credential_id")
    credential_secret = fixture.pop("service_credential_secret")

    client = client_for(
        middleware_config(args, credential_id, credential_secret),
        args.database_file,
    )
    created = client.simulate_post(
        "/v1/repositories",
        headers={"X-Auth-Token": project_token},
        json={"name": "real-control-middleware"},
    )
    assert created.status_code == 201, created.text
    assert (
        client.simulate_get(
            "/v1/repositories", headers={"X-Auth-Token": domain_token}
        ).status_code
        == 403
    )
    assert (
        client.simulate_get(
            "/v1/repositories", headers={"X-Auth-Token": system_token}
        ).status_code
        == 403
    )
    assert client.simulate_get("/v1/repositories").status_code == 401
    assert (
        client.simulate_get(
            "/v1/repositories",
            headers={
                "X-Auth-Token": project_token,
                "X-Service-Token": service_token,
            },
        ).status_code
        == 200
    )
    assert (
        client.simulate_get(
            "/v1/repositories",
            headers={
                "X-Auth-Token": project_token,
                "X-Service-Token": project_token,
            },
        ).status_code
        == 401
    )

    revoke_project_token(args.instance)
    cached = client.simulate_get(
        "/v1/repositories", headers={"X-Auth-Token": project_token}
    )
    assert cached.status_code == 200, cached.text
    time.sleep(3)
    expired_cache = client.simulate_get(
        "/v1/repositories", headers={"X-Auth-Token": project_token}
    )
    assert expired_cache.status_code == 401, expired_cache.text

    unavailable = client_for(
        middleware_config(
            args,
            credential_id,
            credential_secret,
            auth_url="https://127.0.0.1:1/v3",
        ),
        args.database_file.with_name("coffer-unavailable.sqlite"),
    ).simulate_get(
        "/v1/repositories", headers={"X-Auth-Token": project_token}
    )
    assert unavailable.status_code == 503, unavailable.text

    retained = repr(client) + repr(fixture)
    assert credential_secret not in retained
    assert project_token not in retained
    assert domain_token not in retained
    assert system_token not in retained
    assert service_token not in retained
    print(
        json.dumps(
            {
                "cache_ttl_seconds": 2,
                "control_project_token": "accepted",
                "domain_token": "project_api_denied",
                "keystone_outage": "failed_closed",
                "revoked_token_after_cache_ttl": "rejected",
                "service_token_role": "enforced",
                "system_token": "project_api_denied",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
