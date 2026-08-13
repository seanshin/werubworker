"""RemediationEngine — register, execute, cooldown, seed defaults."""

from __future__ import annotations

import pytest

from coworker.monitoring.remediation import (
    RemediationEngine,
    RemediationAction,
    RemediationStep,
)


@pytest.fixture
def engine(tmp_path):
    return RemediationEngine(tmp_path)


def test_register_and_list(engine):
    action = RemediationAction(
        id="rem-1", name="Disk Cleanup", trigger="disk_full",
        steps=[RemediationStep(type="ssh_command", target="web-01", command="rm -rf /tmp/*")],
    )
    result = engine.register(action)
    assert result["ok"]
    actions = engine.list_actions(enabled_only=False)
    assert len(actions) >= 1
    assert actions[0]["name"] == "Disk Cleanup"


def test_remove(engine):
    action = RemediationAction(id="rem-x", name="Test", trigger="test")
    engine.register(action)
    engine.remove("rem-x")
    assert engine.get_action("rem-x") is None


def test_find_action_for_trigger(engine):
    action = RemediationAction(
        id="rem-svc", name="Restart Service", trigger="service_down",
    )
    engine.register(action)
    found = engine.find_action_for_trigger("service_down")
    assert found is not None
    assert found["id"] == "rem-svc"
    assert engine.find_action_for_trigger("nonexistent") is None


def test_execute_requires_approval(engine):
    action = RemediationAction(
        id="rem-a", name="Approval Needed", trigger="test",
        requires_approval=True,
        steps=[RemediationStep(type="notify", target="", command="test")],
    )
    engine.register(action)
    result = engine.execute("rem-a", server_id="web-01")
    assert result.get("status") == "approval_required" or "approval" in str(result).lower()


def test_execute_cooldown(engine):
    action = RemediationAction(
        id="rem-c", name="Cooldown Test", trigger="test",
        cooldown_seconds=9999,
        steps=[RemediationStep(type="notify", target="", command="log only")],
    )
    engine.register(action)
    r1 = engine.execute("rem-c", server_id="s1")
    # Second execution within cooldown
    r2 = engine.execute("rem-c", server_id="s1")
    assert r2.get("status") == "skipped" or "cooldown" in str(r2).lower() or "skipped" in str(r2).lower()


def test_list_executions(engine):
    action = RemediationAction(
        id="rem-e", name="Exec Test", trigger="test",
        steps=[RemediationStep(type="notify", target="", command="test")],
    )
    engine.register(action)
    engine.execute("rem-e", server_id="web-01")
    execs = engine.list_executions()
    assert len(execs) >= 1


def test_seed_defaults(engine):
    result = engine.seed_defaults()
    assert result["ok"]
    actions = engine.list_actions(enabled_only=False)
    assert len(actions) >= 5  # at least 5 default actions
