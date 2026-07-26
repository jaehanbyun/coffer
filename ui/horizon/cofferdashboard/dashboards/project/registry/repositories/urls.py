from django.urls import re_path

from cofferdashboard.dashboards.project.registry.repositories import views

urlpatterns = [
    re_path(r"^$", views.IndexView.as_view(), name="index"),
    re_path(r"^create/$", views.CreateView.as_view(), name="create"),
    re_path(
        r"^(?P<repository_id>[^/]+)/$",
        views.DetailView.as_view(),
        name="detail",
    ),
]
