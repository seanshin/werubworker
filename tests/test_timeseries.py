"""TimeSeriesStore — record, query, downsample, prune."""

from __future__ import annotations

import time

import pytest

from coworker.monitoring.timeseries import TimeSeriesStore


@pytest.fixture
def ts_store(tmp_path):
    return TimeSeriesStore(tmp_path)


def test_record_and_query(ts_store):
    ts_store.record("web-01", cpu=45.0, memory=60.0, disk=30.0)
    rows = ts_store.query_latest("web-01")
    assert len(rows) == 1
    assert rows[0]["server_id"] == "web-01"
    assert rows[0]["cpu"] == 45.0


def test_record_batch(ts_store):
    points = [
        {"server_id": "web-01", "cpu": 50.0, "memory": 70.0, "disk": 40.0},
        {"server_id": "db-01", "cpu": 30.0, "memory": 80.0, "disk": 55.0},
    ]
    result = ts_store.record_batch(points)
    assert result["ok"]
    assert result["inserted"] == 2
    latest = ts_store.query_latest()
    assert len(latest) >= 2


def test_query_time_range(ts_store):
    now = int(time.time()) // 60 * 60
    ts_store.record("web-01", cpu=10.0, memory=20.0, disk=30.0)
    rows = ts_store.query("web-01", now - 3600, now + 3600)
    assert len(rows) >= 1


def test_auto_select_table(ts_store):
    assert ts_store.auto_select_table(3600) == "metrics_raw"       # 1h
    assert ts_store.auto_select_table(7200) == "metrics_raw"       # 2h
    assert ts_store.auto_select_table(86400) == "metrics_5m"       # 1d
    assert ts_store.auto_select_table(604800) == "metrics_5m"      # 7d
    assert ts_store.auto_select_table(7776000) == "metrics_1h"     # 90d
    assert ts_store.auto_select_table(31536000) == "metrics_1d"    # 1y


def test_server_list(ts_store):
    ts_store.record("web-01", cpu=10.0, memory=20.0, disk=30.0)
    ts_store.record("db-01", cpu=20.0, memory=30.0, disk=40.0)
    servers = ts_store.server_list()
    assert "web-01" in servers
    assert "db-01" in servers


def test_downsample(ts_store):
    # Insert enough raw data for a 5m bucket
    ts_store.record("web-01", cpu=50.0, memory=60.0, disk=30.0)
    result = ts_store.downsample()
    assert result["ok"]


def test_prune(ts_store):
    ts_store.record("web-01", cpu=10.0, memory=20.0, disk=30.0)
    result = ts_store.prune()
    assert result["ok"]


def test_query_latest_all_servers(ts_store):
    ts_store.record("web-01", cpu=10.0, memory=20.0, disk=30.0)
    ts_store.record("web-02", cpu=20.0, memory=30.0, disk=40.0)
    latest = ts_store.query_latest()
    server_ids = {r["server_id"] for r in latest}
    assert "web-01" in server_ids
    assert "web-02" in server_ids


def test_record_with_custom_fields(ts_store):
    ts_store.record("gpu-01", cpu=10.0, memory=20.0, disk=30.0,
                    custom={"gpu_util": 85.0, "gpu_temp": 72.0})
    rows = ts_store.query_latest("gpu-01")
    assert len(rows) == 1
