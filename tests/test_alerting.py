"""AlertEngine — rule CRUD, evaluate, acknowledge, resolve."""

from __future__ import annotations

import pytest

from coworker.monitoring.alerting import AlertEngine, AlertRule


@pytest.fixture
def engine(tmp_path):
    return AlertEngine(tmp_path)


def test_add_and_list_rule(engine):
    rule = AlertRule(id="", name="High CPU", metric="cpu", operator=">", threshold=90.0)
    result = engine.add_rule(rule)
    assert result["ok"]
    rules = engine.list_rules()
    assert len(rules) == 1
    assert rules[0]["name"] == "High CPU"


def test_remove_rule(engine):
    rule = AlertRule(id="test-rule", name="Test", metric="cpu", operator=">", threshold=50.0)
    engine.add_rule(rule)
    engine.remove_rule("test-rule")
    assert len(engine.list_rules()) == 0


def test_evaluate_fires_alert(engine):
    rule = AlertRule(
        id="cpu-rule", name="CPU Alert", metric="cpu",
        operator=">", threshold=80.0, severity="warning",
    )
    engine.add_rule(rule)
    metrics = [{"server_id": "web-01", "cpu": 95.0, "memory": 50.0, "disk": 30.0}]
    alerts = engine.evaluate(metrics)
    assert len(alerts) == 1
    assert alerts[0]["server_id"] == "web-01"
    assert alerts[0]["state"] == "firing"


def test_evaluate_no_alert_below_threshold(engine):
    rule = AlertRule(
        id="cpu-rule", name="CPU Alert", metric="cpu",
        operator=">", threshold=80.0,
    )
    engine.add_rule(rule)
    metrics = [{"server_id": "web-01", "cpu": 50.0}]
    alerts = engine.evaluate(metrics)
    assert len(alerts) == 0


def test_evaluate_auto_resolve(engine):
    rule = AlertRule(
        id="cpu-rule", name="CPU Alert", metric="cpu",
        operator=">", threshold=80.0,
    )
    engine.add_rule(rule)
    # Fire
    engine.evaluate([{"server_id": "web-01", "cpu": 95.0}])
    assert len(engine.active_alerts()) == 1
    # Resolve
    engine.evaluate([{"server_id": "web-01", "cpu": 50.0}])
    assert len(engine.active_alerts()) == 0


def test_acknowledge(engine):
    rule = AlertRule(id="r1", name="Test", metric="cpu", operator=">", threshold=80.0)
    engine.add_rule(rule)
    alerts = engine.evaluate([{"server_id": "s1", "cpu": 95.0}])
    alert_id = alerts[0]["id"]
    result = engine.acknowledge(alert_id, user="admin")
    assert result["ok"]
    active = engine.active_alerts()
    assert any(a["state"] == "acknowledged" for a in active)


def test_resolve(engine):
    rule = AlertRule(id="r1", name="Test", metric="cpu", operator=">", threshold=80.0)
    engine.add_rule(rule)
    alerts = engine.evaluate([{"server_id": "s1", "cpu": 95.0}])
    engine.resolve(alerts[0]["id"])
    assert len(engine.active_alerts()) == 0


def test_cooldown_prevents_duplicate(engine):
    rule = AlertRule(
        id="r1", name="Test", metric="cpu", operator=">",
        threshold=80.0, cooldown_seconds=9999,
    )
    engine.add_rule(rule)
    alerts1 = engine.evaluate([{"server_id": "s1", "cpu": 95.0}])
    assert len(alerts1) == 1
    # Second evaluation within cooldown → no new alert
    alerts2 = engine.evaluate([{"server_id": "s1", "cpu": 95.0}])
    assert len(alerts2) == 0


def test_alert_history(engine):
    rule = AlertRule(id="r1", name="Test", metric="cpu", operator=">", threshold=80.0)
    engine.add_rule(rule)
    engine.evaluate([{"server_id": "s1", "cpu": 95.0}])
    history = engine.alert_history()
    assert len(history) >= 1


def test_prune_alerts(engine):
    result = engine.prune_alerts(retention_days=0)
    assert result["ok"]


def test_server_filter(engine):
    rule = AlertRule(
        id="r1", name="Test", metric="cpu", operator=">",
        threshold=80.0, server_id="web-01",
    )
    engine.add_rule(rule)
    # Different server → no alert
    alerts = engine.evaluate([{"server_id": "db-01", "cpu": 95.0}])
    assert len(alerts) == 0
    # Matching server → alert
    alerts = engine.evaluate([{"server_id": "web-01", "cpu": 95.0}])
    assert len(alerts) == 1
