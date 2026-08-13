"""E2E monitoring pipeline test — server register → collect → alert → incident → resolve.

Tests the full lifecycle of the monitoring subsystem using real (local) components
with temporary data directories.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coworker.monitoring.alerting import AlertEngine, AlertRule
from coworker.monitoring.audit_ops import OpsAuditStore, OpsAuditEntry
from coworker.monitoring.collector import CollectorConfig, MetricCollector
from coworker.monitoring.healthcheck import CheckResult, HealthCheckManager, HealthCheckRule
from coworker.monitoring.incidents import IncidentManager
from coworker.monitoring.remediation import RemediationEngine
from coworker.monitoring.timeseries import TimeSeriesStore
from coworker.wiki.resolver import ServiceResolver


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def ts(data_dir):
    return TimeSeriesStore(data_dir)


@pytest.fixture
def hc(data_dir):
    return HealthCheckManager(data_dir)


@pytest.fixture
def alert(data_dir):
    return AlertEngine(data_dir)


@pytest.fixture
def incidents(data_dir):
    return IncidentManager(data_dir)


@pytest.fixture
def audit(data_dir):
    return OpsAuditStore(data_dir)


@pytest.fixture
def remediation(data_dir):
    return RemediationEngine(data_dir)


# ---------------------------------------------------------------------------
# E2E Scenario 1: 메트릭 수집 → 알림 → 인시던트 → 해결
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_collect_alert_incident_resolve(ts, hc, alert, incidents, audit):
    """Full pipeline: collect metrics → trigger alert → create incident → resolve."""

    # Step 1: 메트릭 수집 (로컬)
    collector = MetricCollector(ts, config=CollectorConfig(collect_local=True))
    result = await collector.collect_all()
    assert result["ok"]
    assert result["collected"] >= 1

    # Step 2: 메트릭 확인
    latest = ts.query_latest()
    assert len(latest) >= 1
    local = latest[0]
    assert "cpu" in local
    assert "memory" in local

    # Step 3: 알림 규칙 등록
    alert.add_rule(AlertRule(
        id="e2e-cpu", name="E2E CPU Alert", metric="cpu",
        operator=">", threshold=80.0, severity="warning",
    ))
    alert.add_rule(AlertRule(
        id="e2e-mem", name="E2E Memory Alert", metric="memory",
        operator=">", threshold=95.0, severity="critical",
    ))

    # Step 4: 정상 메트릭으로 평가 → 알림 없음
    normal_alerts = alert.evaluate(latest)
    # 실제 CPU가 80% 미만이면 알림 없음 (대부분의 테스트 환경)

    # Step 5: 비정상 메트릭 시뮬레이션 → 알림 발생
    fake_metrics = [{"server_id": "__local__", "cpu": 92.0, "memory": 50.0, "disk": 30.0}]
    fired = alert.evaluate(fake_metrics)
    assert len(fired) >= 1
    assert fired[0]["severity"] == "warning"

    # Step 6: 알림 기반 인시던트 생성
    inc_result = incidents.create(
        title=fired[0]["title"],
        severity="P3",
        affected_services=["service:api"],
        related_alerts=[fired[0]["id"]],
    )
    assert inc_result["ok"]
    inc_id = inc_result["incident_id"]

    # Step 7: 인시던트 타임라인 추가
    incidents.add_timeline(inc_id, "action", "CPU 사용률 높은 프로세스 확인", author="sre-agent")
    incidents.update_status(inc_id, "identified", note="배치 작업이 CPU 점유 중")

    # Step 8: 감사 로그 기록
    audit.record(OpsAuditEntry(
        timestamp=time.time(), user="agent:sre", action="process_check",
        target="__local__", command="ps aux --sort=-pcpu | head", result="success",
    ))

    # Step 9: 정상화 → 알림 자동 해제
    normal = [{"server_id": "__local__", "cpu": 20.0, "memory": 50.0, "disk": 30.0}]
    alert.evaluate(normal)
    assert len(alert.active_alerts()) == 0

    # Step 10: 인시던트 해결
    incidents.resolve(inc_id, resolution="배치 작업 완료 후 정상화")
    inc = incidents.get(inc_id)
    assert inc["status"] == "resolved"
    assert len(inc.get("timeline", [])) >= 4  # 생성+식별+액션+해결


# ---------------------------------------------------------------------------
# E2E Scenario 2: 헬스체크 → 실패 → 알림 연동
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_healthcheck_failure_detection(hc, alert, incidents):
    """Health check failure → alert evaluation → incident creation."""

    # Step 1: 헬스체크 규칙 등록
    hc.add_check(HealthCheckRule(
        id="e2e-tcp", name="E2E TCP Check", type="tcp",
        target="127.0.0.1:19999",  # 닫혀 있는 포트
        timeout_seconds=2, retries=1,
    ))
    hc.add_check(HealthCheckRule(
        id="e2e-ping", name="E2E Ping Check", type="ping",
        target="127.0.0.1", timeout_seconds=3, retries=1,
    ))

    # Step 2: 헬스체크 실행
    results = await hc.run_checks()
    assert len(results) == 2

    # Step 3: 결과 분석
    failed = [r for r in results if (r.get("status") if isinstance(r, dict) else r.status) == "fail"]
    passed = [r for r in results if (r.get("status") if isinstance(r, dict) else r.status) == "ok"]
    assert len(failed) >= 1  # TCP 19999는 실패해야 함
    assert len(passed) >= 1  # Ping localhost는 성공해야 함

    # Step 4: 실패한 체크 기반 인시던트 생성
    if failed:
        fail = failed[0]
        check_id = fail.get("check_id") if isinstance(fail, dict) else fail.check_id
        inc = incidents.create(
            title=f"헬스체크 실패: {check_id}",
            severity="P4",
            affected_services=[f"healthcheck:{check_id}"],
        )
        assert inc["ok"]


# ---------------------------------------------------------------------------
# E2E Scenario 3: 시계열 저장 → 다운샘플링 → 보관 정책
# ---------------------------------------------------------------------------


def test_e2e_timeseries_lifecycle(ts):
    """Record → query → downsample → prune lifecycle."""

    # Step 1: 메트릭 다수 기록
    for i in range(10):
        ts.record(
            f"server-{i % 3}",
            cpu=30.0 + i * 2,
            memory=50.0 + i,
            disk=20.0,
            net_rx=1000 * i,
            net_tx=500 * i,
            load_1m=1.0 + i * 0.1,
        )

    # Step 2: 서버 목록 확인
    servers = ts.server_list()
    assert len(servers) == 3

    # Step 3: 최신 메트릭 조회
    latest = ts.query_latest()
    assert len(latest) == 3

    # Step 4: 시간 범위 조회
    now = int(time.time())
    data = ts.query("server-0", now - 3600, now + 3600)
    assert len(data) >= 1

    # Step 5: 테이블 자동 선택
    assert ts.auto_select_table(1800) == "metrics_raw"
    assert ts.auto_select_table(86400) == "metrics_5m"

    # Step 6: 다운샘플링
    ds = ts.downsample()
    assert ds["ok"]

    # Step 7: 보관 정책
    pr = ts.prune()
    assert pr["ok"]


# ---------------------------------------------------------------------------
# E2E Scenario 4: 자동 복구 시드 → 실행
# ---------------------------------------------------------------------------


def test_e2e_remediation_seed_and_execute(remediation):
    """Seed default actions → find by trigger → execute."""

    # Step 1: 기본 액션 시드
    seed = remediation.seed_defaults()
    assert seed["ok"]
    assert seed["registered"] >= 5

    # Step 2: 트리거로 액션 찾기
    action = remediation.find_action_for_trigger("service_down")
    assert action is not None
    assert action["name"]

    # Step 3: 승인 필요 액션 확인
    approval_action = remediation.find_action_for_trigger("disk_95")
    assert approval_action is not None

    result = remediation.execute(approval_action["id"], server_id="web-01")
    # 승인 필요 → approval_required 상태
    assert "approval" in str(result).lower() or result.get("status") == "approval_required"


# ---------------------------------------------------------------------------
# E2E Scenario 5: Wiki 리졸버 통합
# ---------------------------------------------------------------------------


def test_e2e_resolver_with_mock_wiki():
    """ServiceResolver resolves natural-language queries via Wiki."""
    from unittest.mock import MagicMock

    wiki = MagicMock()
    secrets = MagicMock()

    wiki.search_fts.return_value = [
        {"page_id": "db-prod", "name": "DB: production",
         "linked_service": "database:prod", "category": "database"},
    ]
    secrets.get.return_value = {
        "type": "postgresql", "host": "10.0.1.10", "port": 5432,
        "user": "app", "password": "secret",
    }
    secrets.status.return_value = [{"profile": "database:prod"}]
    wiki.list_pages.return_value = [
        {"page_id": "db-prod", "name": "DB: production",
         "linked_service": "database:prod"},
    ]

    resolver = ServiceResolver(wiki, secrets)

    # 자연어 해석
    result = resolver.resolve_natural("production DB")
    assert result["ok"]
    assert result["linked_service"] == "database:prod"
    assert "password" not in (result.get("config") or {})

    # 서비스 목록
    services = resolver.list_services_with_wiki()
    assert len(services) >= 1
    assert services[0]["wiki_page"] == "db-prod"


# ---------------------------------------------------------------------------
# E2E Scenario 6: 감사 로그 전체 플로우
# ---------------------------------------------------------------------------


def test_e2e_audit_full_flow(audit):
    """Record → query → count → export → prune."""
    now = time.time()

    # 다양한 액션 기록
    actions = [
        ("ssh_execute", "ssh:web-01", "uptime"),
        ("docker_restart", "docker:nginx", "docker restart nginx"),
        ("db_query", "database:prod", "SELECT 1"),
        ("k8s_scale", "k8s:api-deploy", "kubectl scale --replicas=3"),
        ("ssh_execute", "ssh:web-02", "df -h"),
    ]
    for action, target, cmd in actions:
        audit.record(OpsAuditEntry(
            timestamp=now, user="agent:sre", action=action,
            target=target, command=cmd, result="success",
        ))

    # 필터 조회
    ssh_only = audit.query(action="ssh_execute")
    assert len(ssh_only) == 2

    # 집계
    counts = audit.count_by_action()
    assert len(counts) >= 3

    # CSV 내보내기
    csv = audit.export_csv()
    assert "ssh_execute" in csv
    assert "docker_restart" in csv

    # 정리
    result = audit.prune(retention_days=0)
    assert result["ok"]
