"""Correctness tests for batched writes (성능개선 기획서 v2 Phase 1-1).

Covers:
- BatchWriter flush triggers (size, interval, explicit, close)
- TimeSeriesStore batch_writes mode and read-after-write consistency
- Hash chain integrity across batched audit writes
"""

import threading
import time

import pytest

from coworker.audit import AuditStore
from coworker.monitoring.audit_ops import OpsAuditEntry, OpsAuditStore
from coworker.monitoring.batch_writer import BatchWriter
from coworker.monitoring.timeseries import TimeSeriesStore

# -- BatchWriter --


def test_flushes_on_size():
    """버퍼가 flush_size에 도달하면 즉시 플러시된다."""
    flushed = []
    w = BatchWriter(flushed.append, flush_size=3, flush_interval=0)
    w.enqueue(1)
    w.enqueue(2)
    assert flushed == []
    assert w.pending == 2
    w.enqueue(3)
    assert flushed == [[1, 2, 3]]
    assert w.pending == 0


def test_flushes_on_interval():
    """flush_size에 못 미쳐도 flush_interval 경과 후 타이머가 플러시한다."""
    flushed = []
    w = BatchWriter(flushed.append, flush_size=100, flush_interval=0.05)
    w.enqueue("a")
    assert flushed == []
    deadline = time.monotonic() + 2.0
    while not flushed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert flushed == [["a"]]


def test_explicit_flush_and_close():
    """flush()는 남은 버퍼를 비우고, close()는 플러시 후 입력을 막는다."""
    flushed = []
    w = BatchWriter(flushed.append, flush_size=100, flush_interval=0)
    w.enqueue("x")
    assert w.flush() == 1
    assert flushed == [["x"]]
    assert w.flush() == 0  # 빈 버퍼는 no-op

    w.enqueue("y")
    w.close()
    assert flushed == [["x"], ["y"]]
    with pytest.raises(RuntimeError):
        w.enqueue("z")


def test_enqueue_many():
    """enqueue_many도 임계값 규칙을 동일하게 따른다."""
    flushed = []
    w = BatchWriter(flushed.append, flush_size=3, flush_interval=0)
    w.enqueue_many([1, 2, 3, 4])
    assert flushed == [[1, 2, 3, 4]]


def test_flush_failure_drops_batch_and_counts():
    """플러시 실패 시 배치는 폐기되고 dropped에 누적된다 (버퍼 무한 증가 방지)."""
    def boom(_batch):
        raise RuntimeError("db down")

    w = BatchWriter(boom, flush_size=2, flush_interval=0)
    w.enqueue(1)
    w.enqueue(2)
    assert w.dropped == 2
    assert w.pending == 0  # 재버퍼링하지 않는다


def test_context_manager_flushes_on_exit():
    flushed = []
    with BatchWriter(flushed.append, flush_size=100, flush_interval=0) as w:
        w.enqueue("v")
    assert flushed == [["v"]]


# -- TimeSeriesStore 배치 모드 --


def test_batch_mode_buffers_then_flushes(tmp_path):
    """batch_writes 모드에서 record()는 버퍼에 쌓였다가 임계값에서 기록된다."""
    ts = TimeSeriesStore(tmp_path, batch_writes=True, flush_size=5, flush_interval=0)
    for i in range(4):
        assert ts.record(f"srv-{i}", cpu=10.0, memory=20.0, disk=30.0)["ok"]
    assert ts._writer.pending == 4
    ts.record("srv-4", cpu=10.0, memory=20.0, disk=30.0)
    assert ts._writer.pending == 0
    assert len(ts.server_list()) == 5


def test_batch_mode_read_after_write(tmp_path):
    """조회 메서드는 진입 시 버퍼를 플러시하므로 즉시 조회된다."""
    ts = TimeSeriesStore(tmp_path, batch_writes=True, flush_size=100, flush_interval=0)
    ts.record("web-01", cpu=55.0, memory=40.0, disk=70.0)
    rows = ts.query_latest("web-01")
    assert len(rows) == 1
    assert rows[0]["cpu"] == 55.0


def test_batch_mode_off_by_default(tmp_path):
    """기본값은 즉시 쓰기 — 버퍼 없이 바로 조회된다."""
    ts = TimeSeriesStore(tmp_path)
    ts.record("web-01", cpu=1.0, memory=2.0, disk=3.0)
    assert ts._writer is None
    assert ts.flush() == 0
    assert len(ts.query_latest("web-01")) == 1


def test_record_batch_reports_bad_points(tmp_path):
    """잘못된 포인트는 errors로 보고하고 정상 포인트는 모두 기록한다."""
    ts = TimeSeriesStore(tmp_path)
    result = ts.record_batch([
        {"server_id": "ok-1", "cpu": 1.0},
        {"cpu": 2.0},  # server_id 누락
        {"server_id": "ok-2", "cpu": 3.0},
    ])
    assert result["ok"]
    assert result["inserted"] == 2
    assert len(result["errors"]) == 1
    assert sorted(ts.server_list()) == ["ok-1", "ok-2"]


def test_close_flushes_pending(tmp_path):
    ts = TimeSeriesStore(tmp_path, batch_writes=True, flush_size=100, flush_interval=0)
    ts.record("web-01", cpu=9.0, memory=9.0, disk=9.0)
    ts.close()
    assert len(TimeSeriesStore(tmp_path).query_latest("web-01")) == 1


# -- 해시체인 배치 무결성 --


def test_ops_record_many_preserves_chain(tmp_path):
    """record_many로 기록해도 해시체인이 유효하다."""
    store = OpsAuditStore(tmp_path)
    now = time.time()
    entries = [
        OpsAuditEntry(
            timestamp=now + i,
            user="agent:ops",
            action="ssh_execute",
            target=f"ssh:web-{i:02d}",
            command="uptime",
            result="success",
        )
        for i in range(50)
    ]
    result = store.record_many(entries)
    assert result["ok"] and result["inserted"] == 50
    ok, bad_index = store.verify_chain()
    assert ok, f"chain broken at index {bad_index}"


def test_ops_record_many_chains_with_single_records(tmp_path):
    """단건 record()와 record_many()를 섞어도 체인이 이어진다."""
    store = OpsAuditStore(tmp_path)
    now = time.time()

    def entry(i):
        return OpsAuditEntry(
            timestamp=now + i, user="u", action="a",
            target=f"t{i}", command="c", result="success",
        )

    store.record(entry(0))
    store.record_many([entry(1), entry(2)])
    store.record(entry(3))
    store.record_many([entry(4)])

    ok, bad_index = store.verify_chain()
    assert ok, f"chain broken at index {bad_index}"
    assert store.chain_head() == store.recent(limit=1)[0]["hash"]


def test_ops_record_many_empty(tmp_path):
    store = OpsAuditStore(tmp_path)
    assert store.record_many([]) == {"ok": True, "inserted": 0}


def test_audit_append_many_preserves_chain(tmp_path):
    """AuditStore.append_many도 체인 무결성을 유지한다."""
    store = AuditStore(tmp_path / "audit.db")
    events = [
        {
            "session_id": "s1",
            "tool": "shell_exec",
            "stage": "post",
            "status": "ok",
            "arguments": {"command": f"echo {i}"},
        }
        for i in range(100)
    ]
    assert store.append_many(events) == 100
    ok, bad_index = store.verify_chain()
    assert ok, f"chain broken at index {bad_index}"
    assert len(store.list(limit=200)) == 100


def test_audit_append_many_matches_single_append(tmp_path):
    """append_many와 append를 섞어도 체인이 이어진다."""
    store = AuditStore(tmp_path / "audit.db")
    event = {
        "session_id": "s1", "tool": "shell_exec",
        "stage": "post", "status": "ok", "arguments": {},
    }
    store.append(event)
    store.append_many([event, event])
    store.append(event)
    ok, bad_index = store.verify_chain()
    assert ok, f"chain broken at index {bad_index}"


def test_audit_append_many_empty(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    assert store.append_many([]) == 0


# -- 동시성 --


def test_concurrent_writes_20_threads(tmp_path):
    """20스레드 동시 쓰기 — 유실 없이 전부 기록된다."""
    ts = TimeSeriesStore(tmp_path)
    errors: list[Exception] = []

    def worker(tid: int):
        try:
            for i in range(25):
                ts.record(f"srv-{tid:02d}-{i:02d}", cpu=1.0, memory=2.0, disk=3.0)
        except Exception as exc:  # pragma: no cover - 실패 시에만
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writes raised: {errors}"
    assert len(ts.server_list()) == 20 * 25


def test_concurrent_audit_writes_chain_intact(tmp_path):
    """20스레드가 동시에 감사 로그를 써도 체인이 깨지지 않는다."""
    store = OpsAuditStore(tmp_path)

    def worker(tid: int):
        for i in range(20):
            store.record(OpsAuditEntry(
                timestamp=time.time(),
                user=f"agent:{tid}",
                action="ssh_execute",
                target=f"ssh:web-{tid:02d}",
                command=f"cmd {i}",
                result="success",
            ))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok, bad_index = store.verify_chain()
    assert ok, f"chain broken at index {bad_index}"
