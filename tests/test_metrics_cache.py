"""Tests for MetricsCache and TimeSeriesStore cache integration (Phase 3-1).

Covers:
- latest 캐시 히트/무효화/TTL
- 알림 평가 정확도를 지키는 TTL 상한
- 닫힌 집계 구간만 range 캐시에 담기는지
- 유지보수 작업의 캐시 무효화
"""

import time

from coworker.monitoring.cache import ALL_SERVERS, MAX_LATEST_TTL, MetricsCache
from coworker.monitoring.timeseries import TimeSeriesStore

# -- MetricsCache 단위 --


def test_latest_hit_and_miss():
    cache = MetricsCache()
    assert cache.get_latest("web-01") is None
    cache.set_latest("web-01", [{"server_id": "web-01", "cpu": 10.0}])
    assert cache.get_latest("web-01") == [{"server_id": "web-01", "cpu": 10.0}]
    assert cache.stats()["hits"] == 1
    assert cache.stats()["misses"] == 1


def test_latest_ttl_expires():
    cache = MetricsCache(latest_ttl=0.05)
    cache.set_latest("web-01", [{"cpu": 1.0}])
    assert cache.get_latest("web-01") is not None
    time.sleep(0.06)
    assert cache.get_latest("web-01") is None


def test_latest_ttl_is_capped():
    """TTL 상한 — query_latest()가 알림 평가 경로에 있어 낡은 값을 쓰면 안 된다."""
    cache = MetricsCache(latest_ttl=600.0)
    assert cache.stats()["latest_ttl"] == MAX_LATEST_TTL


def test_invalidate_latest_drops_server_and_all_key():
    cache = MetricsCache()
    cache.set_latest("web-01", [{"cpu": 1.0}])
    cache.set_latest("web-02", [{"cpu": 2.0}])
    cache.set_latest(ALL_SERVERS, [{"cpu": 1.0}, {"cpu": 2.0}])

    cache.invalidate_latest({"web-01"})

    assert cache.get_latest("web-01") is None
    assert cache.get_latest(ALL_SERVERS) is None  # 전체 조회도 함께 무효화
    assert cache.get_latest("web-02") is not None  # 무관한 서버는 유지


def test_returned_rows_are_copies():
    """호출자가 결과를 수정해도 캐시가 오염되지 않는다."""
    cache = MetricsCache()
    cache.set_latest("web-01", [{"cpu": 10.0}])
    rows = cache.get_latest("web-01")
    rows[0]["cpu"] = 999.0
    assert cache.get_latest("web-01")[0]["cpu"] == 10.0


def test_range_lru_eviction():
    cache = MetricsCache(max_range_entries=2)
    cache.set_range(("a", 0, 1, "metrics_5m"), [{"ts": 0}])
    cache.set_range(("b", 0, 1, "metrics_5m"), [{"ts": 1}])
    cache.get_range(("a", 0, 1, "metrics_5m"))  # a를 최근 사용으로
    cache.set_range(("c", 0, 1, "metrics_5m"), [{"ts": 2}])

    assert cache.get_range(("b", 0, 1, "metrics_5m")) is None  # 가장 오래된 b 축출
    assert cache.get_range(("a", 0, 1, "metrics_5m")) is not None
    assert cache.get_range(("c", 0, 1, "metrics_5m")) is not None


# -- TimeSeriesStore 통합 --


def test_query_latest_uses_cache(tmp_path):
    ts = TimeSeriesStore(tmp_path)
    ts.record("web-01", cpu=50.0, memory=40.0, disk=30.0)

    first = ts.query_latest("web-01")
    before = ts.cache_stats()["hits"]
    second = ts.query_latest("web-01")

    assert first == second
    assert ts.cache_stats()["hits"] == before + 1


def test_write_invalidates_latest(tmp_path):
    """쓰기 후 조회는 캐시가 아니라 새 값을 돌려준다."""
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) // 60 * 60
    ts.record_batch([{"server_id": "web-01", "ts": base, "cpu": 10.0}])
    assert ts.query_latest("web-01")[0]["cpu"] == 10.0

    ts.record_batch([{"server_id": "web-01", "ts": base + 60, "cpu": 90.0}])
    assert ts.query_latest("web-01")[0]["cpu"] == 90.0


def test_write_invalidates_all_servers_view(tmp_path):
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) // 60 * 60
    ts.record_batch([{"server_id": "web-01", "ts": base, "cpu": 10.0}])
    assert len(ts.query_latest()) == 1

    ts.record_batch([{"server_id": "web-02", "ts": base, "cpu": 20.0}])
    assert len(ts.query_latest()) == 2


def test_cache_disabled(tmp_path):
    ts = TimeSeriesStore(tmp_path, cache_enabled=False)
    ts.record("web-01", cpu=1.0, memory=2.0, disk=3.0)
    ts.query_latest("web-01")
    ts.query_latest("web-01")
    assert ts.cache_stats() == {"enabled": False}


def test_invalidate_cache_forces_reread(tmp_path):
    """외부 프로세스 쓰기를 시뮬레이션 — 무효화 후 새 값이 보인다."""
    reader = TimeSeriesStore(tmp_path)
    writer = TimeSeriesStore(tmp_path)
    base = int(time.time()) // 60 * 60

    writer.record_batch([{"server_id": "web-01", "ts": base, "cpu": 10.0}])
    assert reader.query_latest("web-01")[0]["cpu"] == 10.0

    writer.record_batch([{"server_id": "web-01", "ts": base + 60, "cpu": 90.0}])
    # reader 캐시는 아직 옛 값 (다른 인스턴스의 쓰기는 감지하지 못한다)
    assert reader.query_latest("web-01")[0]["cpu"] == 10.0

    reader.invalidate_cache()
    assert reader.query_latest("web-01")[0]["cpu"] == 90.0


# -- range 캐시 --


def _seed_aggregates(ts: TimeSeriesStore, base: int, count: int = 30) -> None:
    ts.record_batch([
        {"server_id": "web-01", "ts": base + i * 60, "cpu": 10.0 + i}
        for i in range(count)
    ])
    ts.downsample()


def test_settled_range_is_cached(tmp_path):
    """하루 전 5분 집계 구간은 다시 계산되지 않으므로 캐시된다."""
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) - 86400
    _seed_aggregates(ts, base)

    first = ts.query("web-01", base - 3600, base + 3600, table="metrics_5m")
    assert first, "집계 결과가 있어야 한다"
    before = ts.cache_stats()["hits"]
    second = ts.query("web-01", base - 3600, base + 3600, table="metrics_5m")

    assert first == second
    assert ts.cache_stats()["hits"] == before + 1


def test_forming_bucket_is_not_cached(tmp_path):
    """현재 형성 중인 구간은 캐시하지 않는다."""
    ts = TimeSeriesStore(tmp_path)
    now = int(time.time())
    _seed_aggregates(ts, now - 1800)

    ts.query("web-01", now - 3600, now, table="metrics_5m")
    before = ts.cache_stats()["hits"]
    ts.query("web-01", now - 3600, now, table="metrics_5m")
    assert ts.cache_stats()["hits"] == before  # 히트 없음


def test_raw_table_is_not_cached(tmp_path):
    """raw 테이블은 계속 쓰이므로 range 캐시 대상이 아니다."""
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) - 86400
    ts.record_batch([{"server_id": "web-01", "ts": base, "cpu": 1.0}])

    ts.query("web-01", base - 60, base + 60, table="metrics_raw")
    before = ts.cache_stats()["hits"]
    ts.query("web-01", base - 60, base + 60, table="metrics_raw")
    assert ts.cache_stats()["hits"] == before


def test_downsample_invalidates_ranges(tmp_path):
    """다운샘플링은 과거 버킷을 추가할 수 있으므로 range 캐시를 비운다."""
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) - 86400
    _seed_aggregates(ts, base)

    ts.query("web-01", base - 3600, base + 3600, table="metrics_5m")
    assert ts.cache_stats()["range_entries"] == 1

    ts.downsample()
    assert ts.cache_stats()["range_entries"] == 0


def test_prune_invalidates_everything(tmp_path):
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) - 86400
    _seed_aggregates(ts, base)
    ts.query("web-01", base - 3600, base + 3600, table="metrics_5m")
    ts.query_latest("web-01")

    ts.prune()

    stats = ts.cache_stats()
    assert stats["range_entries"] == 0
    assert stats["latest_entries"] == 0
