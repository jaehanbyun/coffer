from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from horizon import exceptions, forms, messages, tables, views
from horizon.utils import memoized

from cofferdashboard.api import coffer
from cofferdashboard.dashboards.project.registry.repositories import (
    forms as repository_forms,
)
from cofferdashboard.dashboards.project.registry.repositories import (
    tables as repository_tables,
)


def _raise_if_authentication_failure(error):
    if error.result == "authentication_required":
        raise exceptions.NotAuthorized


class IndexView(tables.PagedTableMixin, tables.DataTableView):
    table_class = repository_tables.RepositoriesTable
    template_name = "cofferdashboard/repositories/index.html"
    page_title = _("Repositories")

    def get_data(self):
        marker = self.request.GET.get("marker")
        try:
            page = coffer.list_repositories(
                self.request,
                marker=marker,
                limit=coffer.DEFAULT_PAGE_LIMIT,
            )
        except (coffer.CofferAPIError, ValueError) as error:
            if isinstance(error, coffer.CofferAPIError):
                _raise_if_authentication_failure(error)
            messages.error(
                self.request,
                _("Unable to retrieve the repository list."),
            )
            self._has_more_data = False
            self._has_prev_data = False
            return []
        self._has_more_data = page.next_marker is not None
        self._has_prev_data = False
        return list(page.repositories)

    @memoized.memoized_method
    def _get_quota(self):
        try:
            return "available", coffer.get_quota(self.request)
        except coffer.CofferAPIError as error:
            _raise_if_authentication_failure(error)
            if error.result == "not_found":
                return "not_configured", None
            messages.warning(
                self.request,
                _("Registry quota usage is temporarily unavailable."),
            )
            return "unavailable", None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quota_state, quota = self._get_quota()
        context["quota_state"] = quota_state
        context["quota"] = quota
        return context


class CreateView(forms.ModalFormView):
    form_class = repository_forms.CreateRepository
    template_name = "cofferdashboard/repositories/create.html"
    submit_url = reverse_lazy("horizon:project:repositories:create")
    success_url = reverse_lazy("horizon:project:repositories:index")
    submit_label = page_title = _("Create Repository")


class DetailView(views.HorizonTemplateView):
    template_name = "cofferdashboard/repositories/detail.html"
    page_title = _("Repository Details")

    @memoized.memoized_method
    def _get_repository(self):
        try:
            return coffer.get_repository(
                self.request,
                self.kwargs["repository_id"],
            )
        except (coffer.CofferAPIError, ValueError) as error:
            redirect = reverse("horizon:project:repositories:index")
            if isinstance(error, coffer.CofferAPIError):
                _raise_if_authentication_failure(error)
                if error.result == "not_found":
                    raise exceptions.Http302(
                        redirect,
                        _("The repository was not found."),
                    )
            raise exceptions.Http302(
                redirect,
                _("Unable to retrieve the repository."),
            )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["repository"] = self._get_repository()
        return context
