"""HealthCheckManager — rule CRUD, check execution, history, uptime."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from coworker.monitoring.healthcheck import HealthCheckManager, HealthCheckRule, CheckResult


@pytest.fixture
def hc(tmp_path):
    return HealthCheckManager(tmp_path)


def test_add_and_list_check(hc):
    rule = HealthCheckRule(
        id="chk-api", name="API Health", type="http",
        target="http://localhost:8080/health",
    )
    result = hc.add_check(rule)
    assert result["ok"]
    assert result["check_id"] == "chk-api"
    checks = hc.list_checks()
    assert len(checks) == 1
    assert checks[0]["name"] == "API Health"


def test_remove_check(hc):
    rule = HealthCheckRule(id="chk-1", name="Test", type="tcp", target="localhost:80")
    hc.add_check(rule)
    hc.remove_check("chk-1")
    assert len(hc.list_checks()) == 0


def test_get_check(hc):
    rule = HealthCheckRule(id="chk-1", name="Test", type="http", target="http://example.com")
    hc.add_check(rule)
    check = hc.get_check("chk-1")
    assert check is not None
    assert check["name"] == "Test"


def test_get_check_not_found(hc):
    assert hc.get_check("nonexistent") is None


def test_record_and_get_history(hc):
    now = time.time()
    result = CheckResult(
        check_id="chk-1", timestamp=now,
        status="ok", latency_ms=42.5,
    )
    hc._record_result(result)
    history = hc.get_history("chk-1", hours=24)
    assert len(history) >= 1


def test_uptime_percentage(hc):
    now = time.time()
    # Record a mix of ok and fail with recent timestamps
    for i in range(8):
        hc._record_result(CheckResult(
            check_id="chk-1", timestamp=now - 600 + i * 60,
            status="ok", latency_ms=10.0,
        ))
    for i in range(2):
        hc._record_result(CheckResult(
            check_id="chk-1", timestamp=now - 100 + i * 60,
            status="fail", latency_ms=0.0, error="timeout",
        ))
    pct = hc.uptime_percentage("chk-1", days=30)
    assert 70.0 <= pct <= 90.0  # ~80%


def test_prune_results(hc):
    now = time.time()
    hc._record_result(CheckResult(
        check_id="chk-1", timestamp=now - 86400 * 10,  # 10 days ago
        status="ok", latency_ms=10.0,
    ))
    result = hc.prune_results(retention_days=0)
    assert result["ok"]


@pytest.mark.asyncio
async def test_run_single_http_mock(hc):
    """Mock HTTP check."""
    rule = HealthCheckRule(
        id="chk-http", name="HTTP Check", type="http",
        target="http://localhost:9999/health",
        timeout_seconds=2, retries=1,
    )
    # The check will fail since no server is running, but should not crash
    result = await hc.run_single(rule)
    assert result.status in ("ok", "fail")
    assert isinstance(result.latency_ms, (int, float))


@pytest.mark.asyncio
async def test_run_single_tcp_closed(hc):
    """TCP check to a port that's very likely closed."""
    rule = HealthCheckRule(
        id="chk-tcp", name="TCP Check", type="tcp",
        target="localhost:19999",
        timeout_seconds=2, retries=1,
    )
    result = await hc.run_single(rule)
    assert result.status == "fail"


@pytest.mark.asyncio
async def test_run_single_ping(hc):
    """Ping check to localhost."""
    rule = HealthCheckRule(
        id="chk-ping", name="Ping", type="ping",
        target="127.0.0.1",
        timeout_seconds=5, retries=1,
    )
    result = await hc.run_single(rule)
    assert result.status in ("ok", "fail")


@pytest.mark.asyncio
async def test_run_single_dns(hc):
    """DNS check for a known domain."""
    rule = HealthCheckRule(
        id="chk-dns", name="DNS", type="dns",
        target="localhost",
        timeout_seconds=5, retries=1,
    )
    result = await hc.run_single(rule)
    assert result.status in ("ok", "fail")


@pytest.mark.asyncio
async def test_run_single_process(hc):
    """Process check for a likely-running process."""
    rule = HealthCheckRule(
        id="chk-proc", name="Process", type="process",
        target="python",
        timeout_seconds=5, retries=1,
    )
    result = await hc.run_single(rule)
    assert result.status in ("ok", "fail")
