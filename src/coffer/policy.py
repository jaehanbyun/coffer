from __future__ import annotations

from oslo_config import cfg
from oslo_policy import policy


RULES = [
    policy.DocumentedRuleDefault(
        name="repository:create",
        check_str="role:member or role:admin",
        description="Create a repository in the scoped project.",
        operations=[{"path": "/v1/repositories", "method": "POST"}],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name="repository:list",
        check_str="role:reader or role:member or role:admin",
        description="List repositories in the scoped project.",
        operations=[{"path": "/v1/repositories", "method": "GET"}],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name="repository:get",
        check_str="role:reader or role:member or role:admin",
        description="Read a repository in the scoped project.",
        operations=[{"path": "/v1/repositories/{repository_id}", "method": "GET"}],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name="registry:pull",
        check_str="role:reader or role:member or role:admin",
        description="Pull content from an existing project repository.",
        operations=[{"path": "/v2/{repository}", "method": "GET"}],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name="registry:push",
        check_str="role:member or role:admin",
        description="Push content to an existing project repository.",
        operations=[{"path": "/v2/{repository}", "method": "POST"}],
        scope_types=["project"],
    ),
    policy.DocumentedRuleDefault(
        name="registry:delete",
        check_str="role:admin",
        description="Delete content from an existing project repository.",
        operations=[{"path": "/v2/{repository}", "method": "DELETE"}],
        scope_types=["project"],
    ),
]


def create_enforcer(conf: cfg.ConfigOpts) -> policy.Enforcer:
    enforcer = policy.Enforcer(conf)
    enforcer.register_defaults(RULES)
    enforcer.load_rules()
    return enforcer
