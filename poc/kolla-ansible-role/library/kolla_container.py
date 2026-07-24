from __future__ import annotations

import os

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.coffer_contract import (
    load_state,
    record_event,
    save_state,
)


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "common_options": {"type": "dict", "default": {}},
            "action": {"type": "str", "required": True},
            "api_version": {"type": "str"},
            "auth_email": {"type": "str"},
            "auth_password": {"type": "str", "no_log": True},
            "auth_registry": {"type": "str"},
            "auth_username": {"type": "str"},
            "command": {"type": "str"},
            "container_engine": {"type": "str"},
            "detach": {"type": "bool", "default": True},
            "labels": {"type": "dict", "default": {}},
            "name": {"type": "str"},
            "environment": {"type": "dict"},
            "healthcheck": {"type": "dict"},
            "image": {"type": "str"},
            "ipc_mode": {"type": "str"},
            "cap_add": {"type": "list", "default": []},
            "security_opt": {"type": "list", "default": []},
            "pid_mode": {"type": "str"},
            "cgroupns_mode": {"type": "str"},
            "privileged": {"type": "bool", "default": False},
            "graceful_timeout": {"type": "int"},
            "remove_on_exit": {"type": "bool", "default": True},
            "restart_policy": {"type": "str"},
            "restart_retries": {"type": "int"},
            "state": {"type": "str", "default": "running"},
            "tls_verify": {"type": "bool", "default": False},
            "tls_cert": {"type": "str"},
            "tls_key": {"type": "str"},
            "tls_cacert": {"type": "str"},
            "tmpfs": {"type": "list"},
            "volumes": {"type": "list"},
            "volumes_from": {"type": "list"},
            "dimensions": {"type": "dict", "default": {}},
            "tty": {"type": "bool", "default": False},
            "client_timeout": {"type": "int"},
            "ignore_missing": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    action = module.params["action"]
    name = module.params.get("name")
    image = module.params.get("image")
    state = load_state()
    containers = state.setdefault("containers", {})
    changed = False

    if action == "compare_container":
        changed = name not in containers
    elif action in {"recreate_or_restart_container", "restart_container"}:
        containers[name] = {"image": image, "state": "running"}
        changed = True
    elif action == "start_container":
        if (
            name == "bootstrap_coffer"
            and os.environ.get("COFFER_STUB_FAIL_BOOTSTRAP") == "1"
        ):
            module.fail_json(msg="bounded bootstrap failure")
        operation = f"{action}:{name}"
        changed = operation not in state.setdefault("operations", [])
        if changed:
            state["operations"].append(operation)
    elif action in {"stop_container", "stop_and_remove_container"}:
        changed = name in containers
        containers.pop(name, None)
    elif action == "pull_image":
        operation = f"{action}:{image}"
        changed = operation not in state.setdefault("operations", [])
        if changed:
            state["operations"].append(operation)
    else:
        operation = f"{action}:{name or image or ''}"
        changed = operation not in state.setdefault("operations", [])
        if changed:
            state["operations"].append(operation)

    record_event(action=action, image=image, name=name)
    if not module.check_mode:
        save_state(state)
    module.exit_json(changed=changed)


if __name__ == "__main__":
    main()
