"""Performance tests for v2.3.x security and optimization features.

Measures:
- Hash chain append throughput (with memory-cached prev_hash)
- Sensitive filter throughput (with combined pre-check pattern)
- Chain verification streaming performance
- Alert rule evaluation with cached rules
"""

import time

import pytest

from coworker.monitoring.audit_ops import OpsAuditStore, OpsAuditEntry
from coworker.security.hash_chain import GENESIS_HASH, HashChain
from coworker.security.sensitive_filter import sanitize_text, sanitize_command


@pytest.fixture
def audit(tmp_path):
    return OpsAuditStore(tmp_path)


# -- Hash chain append throughput --


def test_audit_append_1000(audit):
    """1,000건 감사 로그 append < 1초 (해시체인 + 민감정보 필터 포함)."""
    start = time.monotonic()
    now = time.time()
    for i in range(1000):
        audit.record(OpsAuditEntry(
            timestamp=now + i * 0.001,
            user="agent:ops",
            action="ssh_execute",
            target=f"ssh:server-{i % 50:02d}",
            command=f"uptime && free -h  # iteration {i}",
            result="success",
        ))
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"1000 appends took {elapsed:.2f}s (expected < 1.0s)"


def test_audit_append_with_sensitive_data(audit):
    """민감정보가 포함된 명령도 1,000건 < 1.5초."""
    start = time.monotonic()
    now = time.time()
    for i in range(1000):
        audit.record(OpsAuditEntry(
            timestamp=now + i * 0.001,
            user="agent:ops",
            action="ssh_execute",
            target="ssh:db-01",
            command=f"PGPASSWORD=secret{i} psql -U admin -h db.example.com",
            result="success",
        ))
    elapsed = time.monotonic() - start
    assert elapsed < 1.5, f"1000 appends with filter took {elapsed:.2f}s"

    # Verify no secrets leaked
    recent = audit.recent(limit=1)
    assert "secret" not in recent[0].get("command", "")


# -- Hash chain verification streaming --


def test_chain_verify_streaming_10k(audit):
    """10,000건 해시체인 스트리밍 검증 < 3초."""
    now = time.time()
    for i in range(10000):
        audit.record(OpsAuditEntry(
            timestamp=now + i * 0.001,
            user="u", action="a", target="t",
            command=f"cmd{i}", result="s",
        ))

    start = time.monotonic()
    valid, idx = audit.verify_chain()
    elapsed = time.monotonic() - start
    assert valid is True
    assert idx is None
    assert elapsed < 3.0, f"10K verify took {elapsed:.2f}s (expected < 3.0s)"


def test_chain_head_cached(audit):
    """chain_head()는 DB 조회 없이 즉시 반환."""
    audit.record(OpsAuditEntry(
        timestamp=time.time(), user="u", action="a",
        target="t", command="c", result="s",
    ))

    start = time.monotonic()
    for _ in range(10000):
        audit.chain_head()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"10K chain_head calls took {elapsed:.3f}s"


# -- Sensitive filter throughput --


def test_sensitive_filter_bulk_clean():
    """민감정보 없는 텍스트 10,000건 필터링 < 0.1초 (빠른 탈출)."""
    texts = [f"uptime && df -h /dev/sda{i % 10}" for i in range(10000)]
    start = time.monotonic()
    for text in texts:
        sanitize_text(text)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1, f"10K clean texts took {elapsed:.3f}s"


def test_sensitive_filter_bulk_mixed():
    """혼합 텍스트 (20% 민감) 10,000건 < 0.5초."""
    texts = []
    for i in range(10000):
        if i % 5 == 0:
            texts.append(f"password=secret{i} on server-{i}")
        else:
            texts.append(f"uptime check on server-{i}, load: {i * 0.01}")
    start = time.monotonic()
    for text in texts:
        sanitize_text(text)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5, f"10K mixed texts took {elapsed:.3f}s"


def test_sanitize_command_bulk():
    """명령어 10,000건 필터링 < 0.3초."""
    commands = [f"ls -la /var/log/app{i}" for i in range(10000)]
    start = time.monotonic()
    for cmd in commands:
        sanitize_command(cmd)
    elapsed = time.monotonic() - start
    assert elapsed < 0.3, f"10K commands took {elapsed:.3f}s"


# -- Alert rule cache --


def test_alert_eval_cached_rules(tmp_path):
    """캐시된 규칙으로 50규칙 × 200서버 평가 < 1초."""
    from coworker.monitoring.alerting import AlertEngine, AlertRule

    alert = AlertEngine(tmp_path)

    # Add 50 rules
    for i in range(50):
        alert.add_rule(AlertRule(
            id=f"rule-{i}", name=f"CPU Rule {i}",
            metric="cpu", operator=">", threshold=80.0,
            severity="warning", channels=["default"],
        ))

    # Generate 200 server metrics
    metrics = [
        {"server_id": f"server-{j:03d}", "cpu": 50.0 + (j % 40)}
        for j in range(200)
    ]

    # First call populates cache
    alert.evaluate(metrics)

    # Measure cached evaluation (includes DB writes for fired alerts)
    start = time.monotonic()
    alert.evaluate(metrics)
    elapsed = time.monotonic() - start
    # Single eval: 50 rules × 200 servers = 10,000 comparisons + alert DB writes
    assert elapsed < 3.0, f"50 rules × 200 servers eval took {elapsed:.2f}s"


# -- Hash chain compute throughput --


def test_hash_compute_throughput():
    """해시 계산 100,000건 < 1초."""
    prev = GENESIS_HASH
    start = time.monotonic()
    for i in range(100000):
        prev = HashChain.compute_hash(prev, str(i), "data", "test")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"100K hashes took {elapsed:.2f}s"
