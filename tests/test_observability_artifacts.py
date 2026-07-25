from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY_PATH = ROOT / "poc" / "observability" / "topology.json"
RULES_PATH = (
    ROOT
    / "ansible"
    / "roles"
    / "coffer"
    / "templates"
    / "prometheus-coffer.rules.j2"
)
DASHBOARD_PATH = (
    ROOT
    / "ansible"
    / "roles"
    / "coffer"
    / "files"
    / "coffer-operator-dashboard.json"
)
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "observability.md"


def _topology() -> dict:
    return json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))


def _rules() -> list[dict]:
    document = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return [
        rule
        for group in document["groups"]
        for rule in group["rules"]
    ]


def _dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def test_prometheus_rule_names_match_the_versioned_topology() -> None:
    topology = _topology()
    rules = _rules()

    assert [rule["record"] for rule in rules if "record" in rule] == (
        topology["recording_rules"]
    )
    assert [rule["alert"] for rule in rules if "alert" in rule] == (
        topology["alerts"]
    )


def test_alert_metadata_is_bounded_and_runbook_backed() -> None:
    alerts = [rule for rule in _rules() if "alert" in rule]
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    for alert in alerts:
        assert alert["labels"] == {
            "service": "coffer",
            "severity": alert["labels"]["severity"],
        }
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert set(alert["annotations"]) == {"summary", "runbook_url"}
        assert alert["annotations"]["summary"].endswith(".")
        assert alert["annotations"]["runbook_url"].endswith(
            f"#{alert['alert'].lower()}"
        )
        assert f"## {alert['alert']}" in runbook


def test_rules_do_not_create_tenant_or_content_cardinality() -> None:
    serialized = json.dumps(_rules(), sort_keys=True).lower()

    for forbidden in (
        "project_id",
        "repository_id",
        "repository_name",
        "manifest_digest",
        "object_key",
    ):
        assert forbidden not in serialized


def test_dashboard_identity_rows_and_datasource_are_fixed() -> None:
    topology = _topology()
    dashboard = _dashboard()

    assert dashboard["uid"] == "coffer-operator"
    assert dashboard["title"] == "Coffer Operator"
    assert dashboard["schemaVersion"] == 39
    assert dashboard["editable"] is False
    assert set(dashboard["tags"]) == {"coffer", "openstack", "oci-registry"}
    assert [
        panel["title"]
        for panel in dashboard["panels"]
        if panel["type"] == "row"
    ] == topology["dashboard_rows"]
    assert dashboard["templating"]["list"] == [
        {
            "current": {},
            "hide": 0,
            "includeAll": False,
            "label": "Prometheus",
            "multi": False,
            "name": "datasource",
            "options": [],
            "query": "prometheus",
            "refresh": 1,
            "regex": "",
            "skipUrlSync": False,
            "type": "datasource",
        }
    ]


def test_dashboard_uses_every_recording_rule_without_tenant_variables() -> None:
    topology = _topology()
    dashboard = _dashboard()
    expressions = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    serialized = json.dumps(dashboard, sort_keys=True).lower()

    for recording_rule in topology["recording_rules"]:
        assert any(recording_rule in expression for expression in expressions)
    for forbidden in (
        '"name": "project',
        '"name": "repository',
        '"name": "digest',
        "project_id",
        "repository_id",
        "manifest_digest",
    ):
        assert forbidden not in serialized
