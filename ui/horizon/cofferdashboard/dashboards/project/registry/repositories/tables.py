from django.template.defaultfilters import yesno
from django.utils.translation import gettext_lazy as _
from horizon import tables


def immutable_tags(value):
    return yesno(value, _("Yes,No"))


class CreateRepository(tables.LinkAction):
    name = "create"
    verbose_name = _("Create Repository")
    url = "horizon:project:repositories:create"
    classes = ("ajax-modal",)
    icon = "plus"
    policy_rules = (("oci-registry", "repository:create"),)


class RepositoriesTable(tables.DataTable):
    name = tables.Column(
        "name",
        verbose_name=_("Name"),
        link="horizon:project:repositories:detail",
    )
    immutable_tags = tables.Column(
        "immutable_tags",
        verbose_name=_("Immutable Tags"),
        filters=(immutable_tags,),
    )
    created_at = tables.Column(
        "created_at",
        verbose_name=_("Created"),
    )

    def get_object_id(self, repository):
        return repository.id

    class Meta:
        name = "repositories"
        verbose_name = _("Repositories")
        table_actions = (CreateRepository,)
        row_actions = ()
