"""OpsAuditStore — record, query, export."""

from __future__ import annotations

import time

import pytest

from coworker.monitoring.audit_ops import OpsAuditStore, OpsAuditEntry


@pytest.fixture
def store(tmp_path):
    return OpsAuditStore(tmp_path)


def test_record_and_recent(store):
    entry = OpsAuditEntry(
        timestamp=time.time(), user="agent:ops", action="ssh_execute",
        target="ssh:web-01", command="uptime", result="success",
    )
    result = store.record(entry)
    assert result["ok"]
    recent = store.recent(limit=10)
    assert len(recent) >= 1
    assert recent[0]["action"] == "ssh_execute"


def test_query_filter(store):
    now = time.time()
    store.record(OpsAuditEntry(
        timestamp=now, user="agent:ops", action="docker_restart",
        target="docker:nginx", command="docker restart nginx", result="success",
    ))
    store.record(OpsAuditEntry(
        timestamp=now, user="agent:ops", action="ssh_execute",
        target="ssh:web-01", command="ls", result="success",
    ))
    # Filter by action
    results = store.query(action="docker_restart")
    assert len(results) == 1
    assert results[0]["target"] == "docker:nginx"


def test_count_by_action(store):
    now = time.time()
    for _ in range(3):
        store.record(OpsAuditEntry(
            timestamp=now, user="u", action="ssh_execute",
            target="t", command="c", result="success",
        ))
    store.record(OpsAuditEntry(
        timestamp=now, user="u", action="docker_restart",
        target="t", command="c", result="success",
    ))
    counts = store.count_by_action()
    ssh_count = next((c for c in counts if c["action"] == "ssh_execute"), None)
    assert ssh_count is not None
    assert ssh_count["count"] == 3


def test_export_csv(store):
    store.record(OpsAuditEntry(
        timestamp=time.time(), user="admin", action="k8s_scale",
        target="k8s:deploy/api", command="kubectl scale --replicas=3",
        result="success",
    ))
    csv_output = store.export_csv()
    assert "k8s_scale" in csv_output
    assert "admin" in csv_output


def test_prune(store):
    # Record old entry
    store.record(OpsAuditEntry(
        timestamp=time.time() - 400 * 86400,  # 400 days ago
        user="u", action="a", target="t", command="c", result="s",
    ))
    result = store.prune(retention_days=365)
    assert result["ok"]
