PANEL = "repositories"
PANEL_DASHBOARD = "project"
PANEL_GROUP = "registry"

ADD_INSTALLED_APPS = ["cofferdashboard"]
ADD_JS_FILES = ["cofferdashboard/js/registry-detail.js"]
ADD_SCSS_FILES = ["cofferdashboard/scss/registry-detail.scss"]
ADD_PANEL = (
    "cofferdashboard.dashboards.project.registry.repositories.panel.Repositories"
)
