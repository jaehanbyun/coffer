from pathlib import Path

import openstack_dashboard.enabled
from openstack_dashboard.test.settings import *  # noqa: F403
from openstack_dashboard.utils import settings

import cofferdashboard.enabled

HORIZON_CONFIG.pop("dashboards", None)  # noqa: F405
HORIZON_CONFIG.pop("default_dashboard", None)  # noqa: F405

settings.update_dashboards(
    [openstack_dashboard.enabled, cofferdashboard.enabled],
    HORIZON_CONFIG,  # noqa: F405
    INSTALLED_APPS,  # noqa: F405
)

INSTALLED_APPS = list(set(INSTALLED_APPS))  # noqa: F405

POLICY_FILES.update({"oci-registry": "coffer_policy.yaml"})  # noqa: F405
DEFAULT_POLICY_FILES.update(  # noqa: F405
    {"oci-registry": "coffer_policy.yaml"}
)
POLICY_FILES_PATH = str(Path(__file__).parents[1] / "conf")


OPENSTACK_SSL_NO_VERIFY = False
OPENSTACK_SSL_CACERT = None
