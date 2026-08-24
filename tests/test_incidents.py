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


# -- pagination (성능개선 기획서 v2 Phase 5-1) ------------------------------------


def test_incident_list_paginates_past_the_first_page(tmp_path):
    """The tail of the list used to be unreachable, not merely unshown.

    `list_incidents` has always capped at 50 with no offset, so incident 51 could not be
    fetched by any caller."""
    from coworker.monitoring.incidents import IncidentManager

    mgr = IncidentManager(tmp_path)
    created = [mgr.create(f"incident {i}", "P3") for i in range(60)]
    assert all(c["ok"] for c in created)

    first = mgr.list_incidents(limit=50, offset=0)
    second = mgr.list_incidents(limit=50, offset=50)

    assert len(first) == 50
    assert len(second) == 10
    # No overlap and no gap: the two pages together are the whole set.
    ids = [i["id"] for i in first] + [i["id"] for i in second]
    assert len(set(ids)) == 60
    assert mgr.count_incidents() == 60


def test_incident_count_respects_status_filter(tmp_path):
    from coworker.monitoring.incidents import IncidentManager

    mgr = IncidentManager(tmp_path)
    for i in range(5):
        mgr.create(f"open {i}", "P3")
    resolved = mgr.create("closed", "P3")
    mgr.update_status(resolved["incident_id"], "resolved")

    assert mgr.count_incidents() == 6
    assert mgr.count_incidents(status="resolved") == 1
    assert len(mgr.list_incidents(status="resolved")) == 1


def test_dashboard_incidents_reports_whether_more_remain(tmp_path):
    """`has_more`/`total` are what let the UI say the list is truncated."""
    from coworker.server import SessionManager

    manager = SessionManager(workspace=tmp_path, data_dir=tmp_path / "data")
    inc = manager._get_incident_manager()
    for i in range(12):
        inc.create(f"incident {i}", "P3")

    page = manager.dashboard_incidents(limit=5, offset=0)
    assert page["total"] == 12
    assert len(page["incidents"]) == 5
    assert page["has_more"] is True

    last = manager.dashboard_incidents(limit=5, offset=10)
    assert len(last["incidents"]) == 2
    assert last["has_more"] is False

    # A limit past the cap is clamped, not honoured verbatim.
    assert len(manager.dashboard_incidents(limit=10_000)["incidents"]) == 12
