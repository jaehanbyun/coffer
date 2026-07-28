from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import horizon
import yaml
from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse
from horizon.middleware import HorizonMiddleware
from horizon.test.helpers import RequestFactoryWithMessages
from openstack_auth.user import User

from cofferdashboard.api import coffer
from cofferdashboard.dashboards.project.registry.repositories import (
    forms,
    tables,
    views,
)

PROJECT_ID = "project-id"
REPOSITORY_ID = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
SECOND_REPOSITORY_ID = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
DIGEST = f"sha256:{'a' * 64}"
CATALOG_SERVICE = {
    "type": "oci-registry",
    "name": "coffer",
    "endpoints": [
        {
            "region": "RegionOne",
            "interface": "public",
            "url": "https://registry.example.test/v1",
        }
    ],
}
IDENTITY_SERVICE = {
    "type": "identity",
    "name": "keystone",
    "endpoints": [
        {
            "region": "RegionOne",
            "interface": "public",
            "url": "https://identity.example.test/v3",
        }
    ],
}


def repository(
    repository_id: str = REPOSITORY_ID,
    *,
    name: str = "team/app",
    immutable_tags: bool = True,
) -> coffer.Repository:
    return coffer.Repository(
        id=repository_id,
        project_id=PROJECT_ID,
        name=name,
        immutable_tags=immutable_tags,
        created_at="2026-07-26T05:00:00+00:00",
    )


def quota() -> coffer.Quota:
    return coffer.Quota(
        project_id=PROJECT_ID,
        limit_bytes=10_000,
        used_bytes=4_000,
        reserved_bytes=1_000,
    )


def artifact() -> coffer.Artifact:
    return coffer.Artifact(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        digest=DIGEST,
        media_type="application/vnd.oci.image.manifest.v1+json",
        artifact_type="application/vnd.oci.image.config.v1+json",
        kind="image",
        size_bytes=4170,
        pushed_at="2026-07-28T05:00:00+00:00",
        updated_at="2026-07-28T05:01:00+00:00",
        tags=("latest",),
        tag_count=1,
        tags_truncated=False,
    )


def user(service_catalog=None) -> User:
    return User(
        id="user-id",
        token=SimpleNamespace(
            id="test-scoped-token",
            expires=datetime.now(timezone.utc) + timedelta(hours=1),
            project={"id": PROJECT_ID, "name": "project"},
        ),
        user="member",
        project_id=PROJECT_ID,
        project_name="project",
        service_catalog=service_catalog
        if service_catalog is not None
        else [copy.deepcopy(IDENTITY_SERVICE), copy.deepcopy(CATALOG_SERVICE)],
        roles=[
            {"id": "2", "name": "member"},
            {"id": "3", "name": "reader"},
        ],
        authorized_tenants=[],
        endpoint="https://identity.example.test/v3",
        enabled=True,
    )


class RepositoryPanelTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactoryWithMessages()
        self.index_url = reverse("horizon:project:repositories:index")
        for config in settings.TEST_GLOBAL_MOCKS_ON_PANELS.values():
            parameters = {
                name: config[name]
                for name in ("return_value", "side_effect")
                if name in config
            }
            patcher = mock.patch(config["method"], **parameters)
            patcher.start()
            self.addCleanup(patcher.stop)

    def request(self, method="get", path=None, data=None, catalog=None):
        factory_method = getattr(self.factory, method)
        request = factory_method(path or self.index_url, data=data or {})
        request.user = user(catalog)
        HorizonMiddleware(lambda _: None)._process_request(request)
        dashboard = horizon.get_dashboard("project")
        request.horizon["dashboard"] = dashboard
        request.horizon["panel"] = dashboard.get_panel("repositories")
        return request

    @staticmethod
    def render(response):
        response.render()
        return response

    def test_panel_requires_catalog_service(self):
        panel = horizon.get_dashboard("project").get_panel("repositories")
        self.assertEqual(
            panel.permissions,
            ("openstack.services.oci-registry",),
        )

        absent_request = self.request(catalog=[copy.deepcopy(IDENTITY_SERVICE)])
        self.assertFalse(absent_request.user.has_perms(panel.permissions))

        present_request = self.request()
        self.assertTrue(present_request.user.has_perms(panel.permissions))

    @mock.patch("cofferdashboard.api.coffer.get_quota")
    @mock.patch("cofferdashboard.api.coffer.list_repositories")
    def test_index_renders_repository_page_and_quota(
        self,
        list_repositories,
        get_quota,
    ):
        first = repository()
        second = repository(
            SECOND_REPOSITORY_ID,
            name="team/worker",
            immutable_tags=False,
        )
        list_repositories.return_value = coffer.RepositoryPage(
            repositories=(first, second),
            next_marker=SECOND_REPOSITORY_ID,
        )
        get_quota.return_value = quota()

        response = self.render(views.IndexView.as_view()(self.request()))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "team/app")
        self.assertContains(response, "team/worker")
        self.assertContains(response, "stored and")
        self.assertContains(response, "reserved of")
        table = response.context_data["repositories_table"]
        self.assertTrue(table.has_more_data())
        self.assertFalse(table.has_prev_data())
        list_repositories.assert_called_once_with(
            mock.ANY,
            marker=None,
            limit=coffer.DEFAULT_PAGE_LIMIT,
        )
        get_quota.assert_called_once_with(mock.ANY)

    @mock.patch("cofferdashboard.api.coffer.get_quota")
    @mock.patch("cofferdashboard.api.coffer.list_repositories")
    def test_index_forwards_only_the_current_marker(
        self,
        list_repositories,
        get_quota,
    ):
        list_repositories.return_value = coffer.RepositoryPage((), None)
        get_quota.side_effect = coffer.CofferAPIError("not_found")
        request = self.request(
            path=self.index_url,
            data={
                "marker": REPOSITORY_ID,
                "prev_marker": SECOND_REPOSITORY_ID,
            },
        )

        response = self.render(views.IndexView.as_view()(request))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data["quota_state"],
            "not_configured",
        )
        list_repositories.assert_called_once_with(
            request,
            marker=REPOSITORY_ID,
            limit=coffer.DEFAULT_PAGE_LIMIT,
        )

    @mock.patch("cofferdashboard.api.coffer.get_quota")
    @mock.patch("cofferdashboard.api.coffer.list_repositories")
    def test_index_uses_fixed_safe_failure_messages(
        self,
        list_repositories,
        get_quota,
    ):
        list_repositories.side_effect = coffer.CofferAPIError("unavailable")
        get_quota.side_effect = coffer.CofferAPIError("invalid_response")

        response = self.render(views.IndexView.as_view()(self.request()))

        self.assertContains(
            response,
            "Unable to retrieve the repository list.",
        )
        self.assertContains(
            response,
            "Registry quota usage is temporarily unavailable.",
        )
        self.assertNotContains(response, "invalid_response")

    @mock.patch("cofferdashboard.api.coffer.list_repositories")
    def test_index_requires_reauthentication_on_401(
        self,
        list_repositories,
    ):
        list_repositories.side_effect = coffer.CofferAPIError("authentication_required")

        with self.assertRaises(horizon.exceptions.NotAuthorized):
            views.IndexView.as_view()(self.request())

    @mock.patch("cofferdashboard.api.coffer.create_repository")
    def test_create_repository(self, create_repository):
        created = repository()
        create_repository.return_value = created
        url = reverse("horizon:project:repositories:create")
        request = self.request(
            method="post",
            path=url,
            data={
                "method": "CreateRepository",
                "name": created.name,
                "immutable_tags": "on",
            },
        )

        response = views.CreateView.as_view()(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.index_url)
        create_repository.assert_called_once_with(
            request,
            name=created.name,
            immutable_tags=True,
        )

    @mock.patch("cofferdashboard.api.coffer.create_repository")
    def test_create_conflict_is_a_bounded_field_error(
        self,
        create_repository,
    ):
        create_repository.side_effect = coffer.CofferAPIError("conflict")
        url = reverse("horizon:project:repositories:create")
        request = self.request(
            method="post",
            path=url,
            data={
                "method": "CreateRepository",
                "name": "team/app",
                "immutable_tags": "",
            },
        )

        response = views.CreateView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context_data["form"].errors["name"],
            ["A repository with this name already exists."],
        )
        self.assertNotIn(
            "conflict",
            str(response.context_data["form"].errors),
        )

    @mock.patch("cofferdashboard.api.coffer.create_repository")
    def test_create_forbidden_is_a_bounded_form_error(
        self,
        create_repository,
    ):
        create_repository.side_effect = coffer.CofferAPIError("forbidden")
        url = reverse("horizon:project:repositories:create")
        request = self.request(
            method="post",
            path=url,
            data={
                "method": "CreateRepository",
                "name": "team/app",
                "immutable_tags": "",
            },
        )

        response = views.CreateView.as_view()(request)

        self.assertEqual(
            response.context_data["form"].non_field_errors(),
            ["You are not allowed to create repositories."],
        )

    def test_create_rejects_non_oci_repository_name_locally(self):
        url = reverse("horizon:project:repositories:create")
        request = self.request(
            method="post",
            path=url,
            data={
                "method": "CreateRepository",
                "name": "Team/Invalid",
                "immutable_tags": "",
            },
        )

        response = views.CreateView.as_view()(request)

        self.assertEqual(
            response.context_data["form"].errors["name"],
            [str(forms.REPOSITORY_NAME_ERROR)],
        )

    @mock.patch("cofferdashboard.api.coffer.list_artifacts")
    @mock.patch("cofferdashboard.api.coffer.get_repository")
    def test_detail_renders_artifacts_and_safe_connection_guide(
        self,
        get_repository,
        list_artifacts,
    ):
        item = repository()
        get_repository.return_value = item
        list_artifacts.return_value = coffer.ArtifactPage(
            artifacts=(artifact(),),
            next_marker=DIGEST,
        )
        url = reverse(
            "horizon:project:repositories:detail",
            kwargs={"repository_id": item.id},
        )

        response = self.render(
            views.DetailView.as_view()(
                self.request(path=url),
                repository_id=item.id,
            )
        )

        self.assertContains(response, item.name)
        self.assertContains(response, item.id)
        self.assertContains(response, item.project_id)
        self.assertContains(response, "Images &amp; Artifacts")
        self.assertContains(response, "latest")
        self.assertContains(response, DIGEST)
        self.assertContains(
            response,
            "registry.example.test/p/project-id/team/app:latest",
        )
        self.assertContains(response, "How to connect")
        self.assertContains(response, "--client docker")
        self.assertContains(response, "--client podman")
        self.assertContains(response, "--client helm")
        self.assertContains(response, "--client oras")
        self.assertContains(response, 'helm create "app"')
        self.assertContains(
            response,
            '"oci://registry.example.test/p/project-id/team"',
        )
        self.assertNotContains(response, "test-scoped-token")
        self.assertNotContains(response, "application-credential-secret")
        get_repository.assert_called_once_with(mock.ANY, item.id)
        list_artifacts.assert_called_once_with(
            mock.ANY,
            item.id,
            marker=None,
            query=None,
            limit=coffer.MAX_ARTIFACT_PAGE_LIMIT,
        )

    @mock.patch("cofferdashboard.api.coffer.list_artifacts")
    @mock.patch("cofferdashboard.api.coffer.get_repository")
    def test_detail_not_found_uses_fixed_redirect(
        self,
        get_repository,
        list_artifacts,
    ):
        get_repository.side_effect = coffer.CofferAPIError("not_found")
        url = reverse(
            "horizon:project:repositories:detail",
            kwargs={"repository_id": REPOSITORY_ID},
        )

        with self.assertRaises(
            horizon.exceptions.Http302,
        ) as failure:
            views.DetailView.as_view()(
                self.request(path=url),
                repository_id=REPOSITORY_ID,
            ).render()

        self.assertEqual(failure.exception.location, self.index_url)
        self.assertEqual(
            str(failure.exception.message),
            "The repository was not found.",
        )
        list_artifacts.assert_not_called()

    @mock.patch("cofferdashboard.api.coffer.list_artifacts")
    @mock.patch("cofferdashboard.api.coffer.get_repository")
    def test_detail_unavailable_uses_fixed_redirect(
        self,
        get_repository,
        list_artifacts,
    ):
        get_repository.side_effect = coffer.CofferAPIError("unavailable")
        url = reverse(
            "horizon:project:repositories:detail",
            kwargs={"repository_id": REPOSITORY_ID},
        )

        with self.assertRaises(horizon.exceptions.Http302) as failure:
            views.DetailView.as_view()(
                self.request(path=url),
                repository_id=REPOSITORY_ID,
            ).render()

        self.assertEqual(failure.exception.location, self.index_url)
        self.assertEqual(
            str(failure.exception.message),
            "Unable to retrieve the repository.",
        )
        list_artifacts.assert_not_called()

    @mock.patch("cofferdashboard.api.coffer.list_artifacts")
    @mock.patch("cofferdashboard.api.coffer.get_repository")
    def test_detail_keeps_repository_usable_when_artifacts_are_unavailable(
        self,
        get_repository,
        list_artifacts,
    ):
        item = repository()
        get_repository.return_value = item
        list_artifacts.side_effect = coffer.CofferAPIError("unavailable")
        url = reverse(
            "horizon:project:repositories:detail",
            kwargs={"repository_id": item.id},
        )

        response = self.render(
            views.DetailView.as_view()(
                self.request(
                    path=url,
                    data={"query": "latest"},
                ),
                repository_id=item.id,
            )
        )

        self.assertContains(response, item.name)
        self.assertContains(
            response,
            "Artifact information is temporarily unavailable.",
            count=2,
        )
        self.assertContains(response, "How to connect")

    def test_table_exposes_no_destructive_action(self):
        self.assertEqual(
            tables.RepositoriesTable._meta.table_actions,
            (tables.CreateRepository,),
        )
        self.assertEqual(tables.RepositoriesTable._meta.row_actions, ())


def test_policy_mirror_is_bounded_to_the_ui_operations():
    policy_path = __file__.rsplit("/tests/", 1)[0] + "/conf/coffer_policy.yaml"
    with open(policy_path, encoding="utf-8") as stream:
        rules = yaml.safe_load(stream)

    assert rules == {
        "repository:create": "role:member or role:admin",
        "repository:list": "role:reader or role:member or role:admin",
        "repository:get": "role:reader or role:member or role:admin",
        "artifact:list": "role:reader or role:member or role:admin",
        "artifact:get": "role:reader or role:member or role:admin",
        "quota:get": "role:reader or role:member or role:admin",
    }


def test_default_policy_metadata_matches_the_policy_mirror():
    policy_root = __file__.rsplit("/tests/", 1)[0] + "/conf"
    with open(
        policy_root + "/coffer_policy.yaml",
        encoding="utf-8",
    ) as stream:
        rules = yaml.safe_load(stream)
    with open(
        policy_root + "/default_policies/coffer.yaml",
        encoding="utf-8",
    ) as stream:
        defaults = yaml.safe_load(stream)

    assert {item["name"]: item["check_str"] for item in defaults} == rules
    assert all(item["scope_types"] == ["project"] for item in defaults)
    assert all(item["description"] for item in defaults)
