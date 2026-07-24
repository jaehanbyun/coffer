from __future__ import annotations

from jinja2.filters import pass_context
from jinja2.runtime import Undefined

from kolla_ansible.kolla_address import kolla_address as upstream_kolla_address
from kolla_ansible.kolla_url import kolla_url
from kolla_ansible.put_address_in_context import put_address_in_context


@pass_context
def contract_kolla_address(
    context,
    network_name: str,
    hostname: str | None = None,
    override_var: str | None = None,
) -> str:
    """Use an explicit fixture address before delegating to Kolla's filter.

    macOS network facts represent IPv4 addresses as a list, while Kolla's
    production filter deliberately consumes the Linux dictionary shape. The
    contract harness supplies ``api_interface_address`` as an extra variable
    and keeps this compatibility shim outside the product role.
    """

    if hostname is None:
        hostname = context.get("inventory_hostname")
    hostvars = context.get("hostvars")
    if (
        not isinstance(hostname, Undefined)
        and hostvars is not None
        and not isinstance(hostvars, Undefined)
    ):
        host = hostvars.get(hostname)
        if host is not None and not isinstance(host, Undefined):
            explicit_address = host.get(f"{network_name}_interface_address")
            if explicit_address:
                return explicit_address
    return upstream_kolla_address(
        context,
        network_name,
        hostname=hostname,
        override_var=override_var,
    )


class FilterModule:
    def filters(self):
        return {
            "kolla_address": contract_kolla_address,
            "kolla_url": kolla_url,
            "put_address_in_context": put_address_in_context,
        }
