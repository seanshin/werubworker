"""IncidentManager — create, update, timeline, resolve."""

from __future__ import annotations

import pytest

from coworker.monitoring.incidents import IncidentManager


@pytest.fixture
def mgr(tmp_path):
    return IncidentManager(tmp_path)


def test_create_incident(mgr):
    result = mgr.create("DB 연결 실패", "P2", affected_services=["database:prod"])
    assert result["ok"]
    assert result["incident_id"].startswith("inc-")


def test_get_incident(mgr):
    r = mgr.create("서버 다운", "P1")
    inc = mgr.get(r["incident_id"])
    assert inc is not None
    assert inc["title"] == "서버 다운"
    assert inc["severity"] == "P1"
    assert inc["status"] == "investigating"
    assert len(inc.get("timeline", [])) >= 1  # 생성 시 자동 타임라인


def test_update_status(mgr):
    r = mgr.create("이슈", "P3")
    mgr.update_status(r["incident_id"], "identified", note="원인 파악됨")
    inc = mgr.get(r["incident_id"])
    assert inc["status"] == "identified"


def test_add_timeline(mgr):
    r = mgr.create("이슈", "P3")
    mgr.add_timeline(r["incident_id"], "action", "서버 재시작", author="ops-agent")
    inc = mgr.get(r["incident_id"])
    assert len(inc.get("timeline", [])) >= 2


def test_assign(mgr):
    r = mgr.create("이슈", "P3")
    mgr.assign(r["incident_id"], "admin")
    inc = mgr.get(r["incident_id"])
    assert inc["assignee"] == "admin"


def test_resolve(mgr):
    r = mgr.create("이슈", "P3")
    mgr.resolve(r["incident_id"], resolution="수동 복구 완료")
    inc = mgr.get(r["incident_id"])
    assert inc["status"] == "resolved"
    assert inc["resolved_at"] is not None


def test_active_incidents(mgr):
    mgr.create("이슈1", "P2")
    mgr.create("이슈2", "P3")
    r3 = mgr.create("이슈3", "P4")
    mgr.resolve(r3["incident_id"])
    active = mgr.active_incidents()
    assert len(active) == 2


def test_list_incidents(mgr):
    mgr.create("A", "P1")
    mgr.create("B", "P2")
    all_inc = mgr.list_incidents()
    assert len(all_inc) == 2


def test_link_postmortem(mgr):
    r = mgr.create("이슈", "P1")
    mgr.link_postmortem(r["incident_id"], "postmortem-123")
    inc = mgr.get(r["incident_id"])
    assert inc["postmortem_page_id"] == "postmortem-123"
