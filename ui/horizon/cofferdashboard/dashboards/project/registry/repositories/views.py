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

    @memoized.memoized_method
    def _get_artifacts(self):
        marker = self.request.GET.get("artifact_marker") or None
        query = self.request.GET.get("query") or None
        try:
            page = coffer.list_artifacts(
                self.request,
                self.kwargs["repository_id"],
                marker=marker,
                query=query,
                limit=coffer.MAX_ARTIFACT_PAGE_LIMIT,
            )
        except (coffer.CofferAPIError, ValueError) as error:
            if isinstance(error, coffer.CofferAPIError):
                _raise_if_authentication_failure(error)
                if error.result == "forbidden":
                    messages.warning(
                        self.request,
                        _(
                            "You are not allowed to view artifacts in this "
                            "repository."
                        ),
                    )
                    return "forbidden", None
            messages.warning(
                self.request,
                _("Artifact information is temporarily unavailable."),
            )
            return "unavailable", None
        return "available", page

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        repository = self._get_repository()
        artifact_state, artifact_page = self._get_artifacts()
        registry_host = coffer.registry_host(self.request)
        repository_path = (
            f"p/{repository.project_id}/{repository.name}"
        )
        context.update(
            {
                "repository": repository,
                "artifact_state": artifact_state,
                "artifacts": (
                    artifact_page.artifacts
                    if artifact_page is not None
                    else ()
                ),
                "artifact_next_marker": (
                    artifact_page.next_marker
                    if artifact_page is not None
                    else None
                ),
                "artifact_query": self.request.GET.get("query", ""),
                "registry_host": registry_host,
                "repository_path": repository_path,
                "repository_reference": (
                    f"{registry_host}/{repository_path}"
                ),
                "repository_oci_url": (
                    f"oci://{registry_host}/{repository_path}"
                ),
            }
        )
        return context
