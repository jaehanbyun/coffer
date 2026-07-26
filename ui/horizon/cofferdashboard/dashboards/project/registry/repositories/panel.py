import horizon
from django.utils.translation import gettext_lazy as _
from openstack_dashboard.dashboards.project import dashboard


class Repositories(horizon.Panel):
    name = _("Repositories")
    slug = "repositories"
    permissions = ("openstack.services.oci-registry",)


dashboard.Project.register(Repositories)
