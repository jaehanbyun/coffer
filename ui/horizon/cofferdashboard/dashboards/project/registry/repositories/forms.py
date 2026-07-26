from django.utils.translation import gettext_lazy as _
from horizon import exceptions, forms, messages

from cofferdashboard.api import coffer

REPOSITORY_NAME_ERROR = _(
    "Use lowercase letters and numbers separated by '.', '_', or '-'; "
    "use '/' between path segments."
)


class CreateRepository(forms.SelfHandlingForm):
    name = forms.RegexField(
        max_length=255,
        label=_("Repository Name"),
        regex=coffer.REPOSITORY_NAME,
        error_messages={"invalid": REPOSITORY_NAME_ERROR},
    )
    immutable_tags = forms.BooleanField(
        label=_("Prevent tag replacement"),
        required=False,
        help_text=_(
            "When enabled, an existing tag cannot be moved to another manifest."
        ),
    )

    def handle(self, request, data):
        try:
            repository = coffer.create_repository(
                request,
                name=data["name"],
                immutable_tags=data["immutable_tags"],
            )
        except coffer.CofferAPIError as error:
            if error.result == "authentication_required":
                raise exceptions.NotAuthorized
            if error.result == "forbidden":
                self.api_error(_("You are not allowed to create repositories."))
            elif error.result == "conflict":
                self.add_error(
                    "name",
                    _("A repository with this name already exists."),
                )
            else:
                self.api_error(_("Unable to create the repository."))
            return False
        except ValueError:
            self.api_error(_("Unable to create the repository."))
            return False
        messages.success(
            request,
            _("Repository %(name)s was created.") % {"name": repository.name},
        )
        return repository
