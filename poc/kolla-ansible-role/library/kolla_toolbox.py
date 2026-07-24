from __future__ import annotations

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.coffer_contract import (
    load_state,
    record_event,
    save_state,
)


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "container_engine": {"type": "str"},
            "module_name": {"type": "str", "required": True},
            "module_args": {"type": "dict", "required": True},
        },
        supports_check_mode=True,
    )
    module_name = module.params["module_name"]
    module_args = module.params["module_args"]
    if module_name == "openstack.cloud.catalog_service":
        label = (
            f"{module_args.get('name', '')}:"
            f"{module_args.get('service_type', '')}"
        )
    elif module_name == "openstack.cloud.endpoint":
        label = (
            f"{module_args.get('service', '')}:"
            f"{module_args.get('endpoint_interface', '')}:"
            f"{module_args.get('url', '')}"
        )
    else:
        label = str(
            module_args.get("name")
            or module_args.get("service")
            or module_args.get("user")
            or ""
        )
    operation = f"toolbox:{module_name}:{label}"
    state = load_state()
    operations = state.setdefault("operations", [])
    changed = operation not in operations
    if changed and not module.check_mode:
        operations.append(operation)
        save_state(state)
    record_event(action="toolbox", module_name=module_name, label=label)
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
