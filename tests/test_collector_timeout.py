"""수집 병렬도 + 적응형 SSH 타임아웃 (성능개선 기획서 v2 Phase 2-1)."""

from __future__ import annotations

import asyncio

import pytest

from coworker.monitoring.collector import (
    MAX_PARALLEL_WORKERS,
    CollectorConfig,
    MetricCollector,
    TimeoutTracker,
)
from coworker.monitoring.timeseries import TimeSeriesStore


@pytest.fixture
def ts_store(tmp_path):
    return TimeSeriesStore(tmp_path)


# -- 병렬도 설정 --


def test_default_parallel_workers_is_20():
    assert CollectorConfig().parallel_workers == 20


def test_parallel_workers_clamped_to_max():
    assert CollectorConfig(parallel_workers=500).parallel_workers == MAX_PARALLEL_WORKERS


def test_parallel_workers_floor_is_one():
    assert CollectorConfig(parallel_workers=0).parallel_workers == 1


def test_timeout_bounds_normalized():
    """max < min으로 설정하면 min 쪽으로 정규화된다."""
    cfg = CollectorConfig(min_ssh_timeout=20, max_ssh_timeout=5)
    assert cfg.min_ssh_timeout == 20
    assert cfg.max_ssh_timeout == 20


def test_collect_all_respects_parallel_limit(ts_store):
    """동시에 실행되는 수집 수가 parallel_workers를 넘지 않는다."""
    config = CollectorConfig(parallel_workers=3, collect_local=False)
    collector = MetricCollector(ts_store, secrets=None, config=config)

    servers = [{"server_id": f"srv-{i:02d}", "host": "h"} for i in range(12)]
    collector._list_servers = lambda: servers

    peak = 0
    active = 0

    async def fake_collect(server_info):
        nonlocal peak, active
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"ok": True, "server_id": server_info["server_id"],
                "point": {"server_id": server_info["server_id"], "cpu": 1.0}}

    collector._collect_server = fake_collect

    result = asyncio.run(collector.collect_all())

    assert result["collected"] == 12
    assert peak <= 3, f"동시 실행 {peak}개 — 상한 3 초과"


# -- 적응형 타임아웃 --


def test_no_history_uses_configured_timeout():
    tracker = TimeoutTracker(CollectorConfig(ssh_timeout=15))
    assert tracker.timeout_for("web-01") == 15


def test_fast_server_gets_min_timeout():
    """빠른 서버는 하한까지 줄어 장애 시 빨리 포기한다."""
    cfg = CollectorConfig(min_ssh_timeout=5, max_ssh_timeout=30)
    tracker = TimeoutTracker(cfg)
    for _ in range(10):
        tracker.record_success("web-01", 0.2)
    assert tracker.timeout_for("web-01") == 5


def test_slow_server_gets_max_timeout():
    """느린 서버는 상한까지 늘어 정상 응답이 잘리지 않는다."""
    cfg = CollectorConfig(min_ssh_timeout=5, max_ssh_timeout=30)
    tracker = TimeoutTracker(cfg)
    for _ in range(10):
        tracker.record_success("db-01", 25.0)
    assert tracker.timeout_for("db-01") == 30


def test_moderate_server_scales_with_history():
    """중간 속도 서버는 평균의 약 3배를 받는다."""
    cfg = CollectorConfig(min_ssh_timeout=5, max_ssh_timeout=30)
    tracker = TimeoutTracker(cfg)
    for _ in range(20):
        tracker.record_success("web-01", 4.0)
    assert 12 <= tracker.timeout_for("web-01") <= 14


def test_failure_gets_max_timeout_next_time():
    """실패한 서버는 다음 시도에서 상한을 받는다 (느려서 잘렸을 수 있으므로)."""
    cfg = CollectorConfig(min_ssh_timeout=5, max_ssh_timeout=30)
    tracker = TimeoutTracker(cfg)
    for _ in range(10):
        tracker.record_success("web-01", 0.2)
    assert tracker.timeout_for("web-01") == 5

    tracker.record_failure("web-01")
    assert tracker.timeout_for("web-01") == 30


def test_recovery_returns_to_adaptive():
    cfg = CollectorConfig(min_ssh_timeout=5, max_ssh_timeout=30)
    tracker = TimeoutTracker(cfg)
    tracker.record_failure("web-01")
    assert tracker.timeout_for("web-01") == 30

    for _ in range(10):
        tracker.record_success("web-01", 0.2)
    assert tracker.timeout_for("web-01") == 5


def test_adaptive_disabled_uses_fixed_timeout():
    cfg = CollectorConfig(adaptive_timeout=False, ssh_timeout=15)
    tracker = TimeoutTracker(cfg)
    tracker.record_success("web-01", 0.1)
    assert tracker.timeout_for("web-01") == 15
    tracker.record_failure("web-01")
    assert tracker.timeout_for("web-01") == 15


def test_stale_history_pruned(monkeypatch):
    """오래 보이지 않은 서버 이력은 제거된다 (맵 무한 증가 방지)."""
    import coworker.monitoring.collector as mod

    tracker = TimeoutTracker(CollectorConfig())
    tracker.record_success("old-01", 1.0)
    assert tracker.stats()["tracked"] == 1

    # 이력 TTL을 지난 것처럼 시간을 앞당긴다
    real_time = mod.time.time
    monkeypatch.setattr(mod.time, "time", lambda: real_time() + mod._HISTORY_TTL + 1)
    tracker.record_success("new-01", 1.0)

    stats = tracker.stats()
    assert stats["tracked"] == 1
    assert "new-01" in stats["servers"]
    assert "old-01" not in stats["servers"]


def test_timeout_stats_exposed(ts_store):
    collector = MetricCollector(ts_store, secrets=None, config=CollectorConfig())
    collector._timeouts.record_success("web-01", 2.0)
    stats = collector.timeout_stats()
    assert stats["tracked"] == 1
    assert stats["servers"]["web-01"]["avg_seconds"] == 2.0
    assert stats["servers"]["web-01"]["timeout"] == 7
