from __future__ import annotations

from typing import Any

from osc_lib import utils

from cofferclient.client import Client


API_NAME = "registry"
API_VERSION_OPTION = "os_registry_api_version"
API_VERSIONS = {
    "1": "cofferclient.client.Client",
    "1.0": "cofferclient.client.Client",
}


def make_client(instance: Any) -> Client:
    endpoint = instance.get_endpoint_for_service_type(
        "oci-registry",
        interface=instance.interface,
        region_name=instance._region_name,
    )
    return Client(instance.session, endpoint)


def build_option_parser(parser: Any) -> Any:
    parser.add_argument(
        "--os-registry-api-version",
        metavar="<registry-api-version>",
        default=utils.env("OS_REGISTRY_API_VERSION", default="1"),
        choices=sorted(API_VERSIONS),
        help=(
            'Registry API version, default="1". '
            "(Env: OS_REGISTRY_API_VERSION)"
        ),
    )
    return parser
