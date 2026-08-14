"""Performance / stress tests — verify monitoring subsystem under load.

Simulates 100 servers with concurrent metric writes, health checks,
alert evaluations, and incident creation to verify SQLite performance
and data integrity.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from coworker.monitoring.alerting import AlertEngine, AlertRule
from coworker.monitoring.healthcheck import HealthCheckManager, HealthCheckRule
from coworker.monitoring.incidents import IncidentManager
from coworker.monitoring.timeseries import TimeSeriesStore


@pytest.fixture
def ts(tmp_path):
    return TimeSeriesStore(tmp_path)


@pytest.fixture
def alert(tmp_path):
    return AlertEngine(tmp_path)


@pytest.fixture
def hc(tmp_path):
    return HealthCheckManager(tmp_path)


@pytest.fixture
def inc(tmp_path):
    return IncidentManager(tmp_path)


# ---------------------------------------------------------------------------
# 1. 대량 메트릭 쓰기 성능
# ---------------------------------------------------------------------------


def test_bulk_metric_write_100_servers(ts):
    """100개 서버 메트릭 일괄 기록 — 1초 이내."""
    points = [
        {
            "server_id": f"server-{i:03d}",
            "cpu": 10.0 + (i % 90),
            "memory": 20.0 + (i % 70),
            "disk": 5.0 + (i % 30),
            "net_rx": i * 1000,
            "net_tx": i * 500,
            "load_1m": 0.5 + (i % 10) * 0.1,
        }
        for i in range(100)
    ]

    start = time.monotonic()
    result = ts.record_batch(points)
    elapsed = time.monotonic() - start

    assert result["ok"]
    assert result["inserted"] == 100
    assert elapsed < 1.0, f"Batch write took {elapsed:.2f}s (expected <1s)"

    # 서버 목록 확인
    servers = ts.server_list()
    assert len(servers) == 100


def test_bulk_metric_write_1000_points(ts):
    """1000개 데이터 포인트 기록 — 2초 이내."""
    points = [
        {
            "server_id": f"server-{i % 50:03d}",
            "cpu": float(i % 100),
            "memory": float(i % 80),
            "disk": float(i % 40),
        }
        for i in range(1000)
    ]

    start = time.monotonic()
    result = ts.record_batch(points)
    elapsed = time.monotonic() - start

    assert result["ok"]
    assert elapsed < 2.0, f"1000 points took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# 2. 대량 쿼리 성능
# ---------------------------------------------------------------------------


def test_query_latest_100_servers(ts):
    """100개 서버 최신 메트릭 조회 — 0.5초 이내."""
    # 데이터 투입
    points = [
        {"server_id": f"srv-{i:03d}", "cpu": float(i), "memory": 50.0, "disk": 20.0}
        for i in range(100)
    ]
    ts.record_batch(points)

    start = time.monotonic()
    latest = ts.query_latest()
    elapsed = time.monotonic() - start

    assert len(latest) == 100
    assert elapsed < 0.5, f"Query latest took {elapsed:.2f}s"


def test_time_range_query(ts):
    """시간 범위 쿼리 성능."""
    # 데이터 투입
    for i in range(50):
        ts.record(f"web-{i % 5}", cpu=float(i), memory=50.0, disk=20.0)

    now = int(time.time())
    start = time.monotonic()
    data = ts.query("web-0", now - 86400, now + 86400)
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, f"Range query took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# 3. 다운샘플링 + 보관 정책 성능
# ---------------------------------------------------------------------------


def test_downsample_performance(ts):
    """다운샘플링 성능 — 100개 서버 데이터."""
    points = [
        {"server_id": f"s-{i:03d}", "cpu": float(i), "memory": 50.0, "disk": 20.0}
        for i in range(100)
    ]
    ts.record_batch(points)

    start = time.monotonic()
    result = ts.downsample()
    elapsed = time.monotonic() - start

    assert result["ok"]
    assert elapsed < 2.0, f"Downsample took {elapsed:.2f}s"


def test_prune_performance(ts):
    """보관 정책 적용 성능."""
    points = [
        {"server_id": f"s-{i:03d}", "cpu": float(i), "memory": 50.0, "disk": 20.0}
        for i in range(100)
    ]
    ts.record_batch(points)

    start = time.monotonic()
    result = ts.prune()
    elapsed = time.monotonic() - start

    assert result["ok"]
    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# 4. 알림 규칙 대량 평가
# ---------------------------------------------------------------------------


def test_alert_evaluation_50_rules_100_servers(alert):
    """50개 규칙 × 100개 서버 메트릭 평가 — 1초 이내."""
    # 50개 규칙 등록
    for i in range(50):
        alert.add_rule(AlertRule(
            id=f"rule-{i:03d}",
            name=f"Rule {i}",
            metric="cpu" if i % 3 == 0 else "memory" if i % 3 == 1 else "disk",
            operator=">",
            threshold=95.0,  # 높은 임계값 → 대부분 알림 안 남
            severity="warning",
        ))

    # 100개 서버 메트릭
    metrics = [
        {"server_id": f"srv-{i:03d}", "cpu": 50.0, "memory": 60.0, "disk": 30.0}
        for i in range(100)
    ]

    start = time.monotonic()
    alerts = alert.evaluate(metrics)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"Evaluation took {elapsed:.2f}s"
    assert len(alerts) == 0  # 임계값 미달


def test_alert_mass_firing(alert):
    """대량 알림 발생 시 성능."""
    alert.add_rule(AlertRule(
        id="mass-rule", name="Mass Alert", metric="cpu",
        operator=">", threshold=10.0, severity="critical",
    ))

    metrics = [
        {"server_id": f"srv-{i:03d}", "cpu": 90.0, "memory": 50.0, "disk": 30.0}
        for i in range(50)
    ]

    start = time.monotonic()
    alerts = alert.evaluate(metrics)
    elapsed = time.monotonic() - start

    assert len(alerts) == 50
    assert elapsed < 2.0, f"Mass firing took {elapsed:.2f}s"

    # 전부 자동 해제
    normal = [
        {"server_id": f"srv-{i:03d}", "cpu": 5.0, "memory": 50.0, "disk": 30.0}
        for i in range(50)
    ]
    alert.evaluate(normal)
    assert len(alert.active_alerts()) == 0


# ---------------------------------------------------------------------------
# 5. 헬스체크 병렬 실행
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthcheck_parallel_20(hc):
    """20개 헬스체크 병렬 실행 — 5초 이내."""
    for i in range(10):
        hc.add_check(HealthCheckRule(
            id=f"hc-tcp-{i}", name=f"TCP {i}", type="tcp",
            target=f"127.0.0.1:{19900 + i}", timeout_seconds=1, retries=1,
        ))
    for i in range(10):
        hc.add_check(HealthCheckRule(
            id=f"hc-dns-{i}", name=f"DNS {i}", type="dns",
            target="localhost", timeout_seconds=2, retries=1,
        ))

    start = time.monotonic()
    results = await hc.run_checks()
    elapsed = time.monotonic() - start

    assert len(results) == 20
    assert elapsed < 5.0, f"20 checks took {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# 6. 인시던트 대량 생성
# ---------------------------------------------------------------------------


def test_incident_bulk_create(inc):
    """50개 인시던트 생성 + 타임라인 추가 — 2초 이내."""
    start = time.monotonic()
    ids = []
    for i in range(50):
        r = inc.create(f"Incident {i}", f"P{(i % 4) + 1}")
        ids.append(r["incident_id"])
        inc.add_timeline(ids[-1], "action", f"Step {i}", author="test")

    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"50 incidents took {elapsed:.2f}s"

    # 목록 조회
    all_inc = inc.list_incidents(limit=100)
    assert len(all_inc) == 50

    # 활성 인시던트
    active = inc.active_incidents()
    assert len(active) == 50


# ---------------------------------------------------------------------------
# 7. 동시 쓰기 안정성 (SQLite WAL)
# ---------------------------------------------------------------------------


def test_concurrent_writes(ts):
    """멀티스레드 동시 쓰기 — WAL 모드 안정성."""
    import threading

    errors = []

    def writer(thread_id: int):
        try:
            for i in range(20):
                ts.record(
                    f"thread-{thread_id}-srv-{i}",
                    cpu=float(i), memory=50.0, disk=20.0,
                )
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(errors) == 0, f"Concurrent write errors: {errors}"

    # 데이터 무결성 확인
    servers = ts.server_list()
    assert len(servers) == 100  # 5 threads × 20 servers
