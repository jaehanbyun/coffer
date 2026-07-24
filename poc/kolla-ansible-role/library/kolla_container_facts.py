from __future__ import annotations

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.coffer_contract import load_state, record_event


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "action": {"type": "str", "required": True},
            "container_engine": {"type": "str"},
            "name": {"type": "list", "elements": "str"},
        },
        supports_check_mode=True,
    )
    requested = module.params.get("name") or []
    state = load_state()
    containers = {
        name: details
        for name, details in state.get("containers", {}).items()
        if not requested or name in requested
    }
    record_event(action="get_containers", names=sorted(requested))
    module.exit_json(changed=False, containers=containers)


if __name__ == "__main__":
    main()
