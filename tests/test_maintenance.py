"""디스크 관리 자동화 + 체인 앵커 (성능개선 기획서 v2 Phase 6-2, 1-2 잔여).

정리(prune)는 감사 로그의 오래된 기록을 지우므로 해시체인의 시작점이
사라진다. 앵커를 저장하지 않으면 이후 verify_chain()이 영구 실패한다 —
자동 정리를 켠 뒤 이 회귀가 재발하지 않도록 여기서 고정한다.
"""

from __future__ import annotations

import time

from coworker.audit import AuditStore
from coworker.monitoring.audit_ops import OpsAuditEntry, OpsAuditStore
from coworker.monitoring.maintenance import DiskMaintenance, MaintenanceConfig
from coworker.monitoring.timeseries import TimeSeriesStore
from coworker.security.hash_chain import GENESIS_HASH

# -- 체인 앵커: 정리 후에도 검증이 유효한가 --


def _ops_entries(store: OpsAuditStore, base: float, count: int, prefix: str) -> None:
    for i in range(count):
        store.record(OpsAuditEntry(
            timestamp=base + i, user="u", action="a",
            target=f"{prefix}{i}", command="c", result="s",
        ))


def test_ops_prune_keeps_chain_verifiable(tmp_path):
    store = OpsAuditStore(tmp_path)
    now = time.time()
    _ops_entries(store, now - 400 * 86400, 10, "old")
    _ops_entries(store, now, 10, "new")
    assert store.verify_chain() == (True, None)

    result = store.prune(retention_days=365)

    assert result["ok"] and result["deleted"] == 10
    assert store.verify_chain() == (True, None), "정리 후에도 체인이 검증돼야 한다"
    assert store.chain_anchor() != GENESIS_HASH


def test_ops_prune_anchor_survives_reopen(tmp_path):
    """앵커는 DB에 저장되므로 재기동 후에도 검증이 유효하다."""
    store = OpsAuditStore(tmp_path)
    now = time.time()
    _ops_entries(store, now - 400 * 86400, 5, "old")
    _ops_entries(store, now, 5, "new")
    store.prune(retention_days=365)
    anchor = store.chain_anchor()

    reopened = OpsAuditStore(tmp_path)
    assert reopened.chain_anchor() == anchor
    assert reopened.verify_chain() == (True, None)


def test_ops_prune_nothing_deleted_keeps_genesis(tmp_path):
    store = OpsAuditStore(tmp_path)
    _ops_entries(store, time.time(), 5, "new")
    result = store.prune(retention_days=365)
    assert result["deleted"] == 0
    assert store.chain_anchor() == GENESIS_HASH


def test_ops_prune_everything_anchors_to_head(tmp_path):
    """전부 지워도 이후 기록이 head에 연결되므로 체인이 이어진다."""
    store = OpsAuditStore(tmp_path)
    now = time.time()
    _ops_entries(store, now - 400 * 86400, 5, "old")
    head = store.chain_head()

    store.prune(retention_days=365)
    assert store.chain_anchor() == head

    _ops_entries(store, now, 3, "new")
    assert store.verify_chain() == (True, None)


def _audit_events(store: AuditStore, count: int) -> None:
    for i in range(count):
        store.append({
            "session_id": "s1", "tool": "shell_exec", "stage": "post",
            "status": "ok", "arguments": {"command": f"echo {i}"},
        })


def test_audit_prune_keeps_chain_verifiable(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    _audit_events(store, 10)
    # 앞의 5건을 보관 기간 밖으로 밀어낸다
    store._conn.execute(
        "UPDATE audit_events SET timestamp = datetime('now', '-200 days') WHERE id <= 5"
    )
    store._conn.commit()
    assert store.verify_chain() == (True, None)

    result = store.prune(retention_days=90)

    assert result["ok"] and result["deleted"] == 5
    assert store.verify_chain() == (True, None)
    assert store.chain_anchor() != GENESIS_HASH
    assert len(store.list(limit=100)) == 5


def test_audit_prune_anchor_survives_reopen(tmp_path):
    db = tmp_path / "audit.db"
    store = AuditStore(db)
    _audit_events(store, 6)
    store._conn.execute(
        "UPDATE audit_events SET timestamp = datetime('now', '-200 days') WHERE id <= 3"
    )
    store._conn.commit()
    store.prune(retention_days=90)
    anchor = store.chain_anchor()
    store.close()

    reopened = AuditStore(db)
    assert reopened.chain_anchor() == anchor
    assert reopened.verify_chain() == (True, None)


def test_audit_prune_nothing_deleted(tmp_path):
    store = AuditStore(tmp_path / "audit.db")
    _audit_events(store, 3)
    result = store.prune(retention_days=90)
    assert result["deleted"] == 0
    assert store.chain_anchor() == GENESIS_HASH


# -- WAL 체크포인트 --


def test_checkpoint_truncates_wal(tmp_path):
    ts = TimeSeriesStore(tmp_path)
    base = int(time.time()) // 60 * 60
    for tick in range(20):
        ts.record_batch([
            {"server_id": f"srv-{i:03d}", "ts": base - tick * 60, "cpu": 1.0}
            for i in range(50)
        ])

    result = ts.checkpoint()
    assert result["ok"], result
    wal = tmp_path / "monitoring.db-wal"
    assert not wal.exists() or wal.stat().st_size == 0


def test_db_size_bytes(tmp_path):
    ts = TimeSeriesStore(tmp_path)
    ts.record("web-01", cpu=1.0, memory=2.0, disk=3.0)
    assert ts.db_size_bytes() > 0


# -- DiskMaintenance --


class _Recorder:
    """호출 순서를 기록하는 더미 저장소."""

    def __init__(self, log: list[str], name: str, fail: bool = False):
        self._log = log
        self._name = name
        self._fail = fail

    def _call(self, step: str):
        self._log.append(f"{self._name}.{step}")
        if self._fail:
            raise RuntimeError(f"{self._name} down")
        return {"ok": True}

    def downsample(self):
        return self._call("downsample")

    def prune(self, *args):
        return self._call("prune")

    def checkpoint(self):
        return self._call("checkpoint")

    def db_size_bytes(self):
        self._log.append(f"{self._name}.db_size_bytes")
        return 1234


def test_first_run_is_due():
    assert DiskMaintenance().due()


def test_second_run_is_skipped():
    m = DiskMaintenance()
    assert m.run()["skipped"] is False
    assert m.run()["skipped"] is True


def test_force_overrides_interval():
    m = DiskMaintenance()
    m.run()
    assert m.run(force=True)["skipped"] is False


def test_interval_elapsed_makes_it_due():
    m = DiskMaintenance(MaintenanceConfig(interval_seconds=0.05))
    m.run()
    assert not m.due()
    time.sleep(0.06)
    assert m.due()


def test_step_order_is_downsample_prune_checkpoint():
    """정리로 지워질 데이터를 먼저 집계하고, 회수는 마지막에."""
    calls: list[str] = []
    ts = _Recorder(calls, "ts")
    m = DiskMaintenance()
    m.run(ts=ts, force=True)

    assert calls == [
        "ts.downsample", "ts.prune", "ts.checkpoint", "ts.db_size_bytes",
    ]


def test_audit_pruned_before_checkpoint():
    calls: list[str] = []
    ts = _Recorder(calls, "ts")
    m = DiskMaintenance()
    m.run(
        ts=ts,
        ops_audit=_Recorder(calls, "ops"),
        audit=_Recorder(calls, "audit"),
        backups=_Recorder(calls, "backup"),
        force=True,
    )

    assert calls.index("ops.prune") < calls.index("ts.checkpoint")
    assert calls.index("audit.prune") < calls.index("ts.checkpoint")
    assert calls.index("backup.prune") < calls.index("ts.checkpoint")


def test_missing_components_are_skipped():
    result = DiskMaintenance().run(force=True)
    assert result["ok"] and result["steps"] == {}


def test_one_failing_store_does_not_stop_others():
    """저장소 하나가 죽어도 나머지 정리는 진행돼야 한다."""
    calls: list[str] = []
    m = DiskMaintenance()
    result = m.run(
        ts=_Recorder(calls, "ts"),
        ops_audit=_Recorder(calls, "ops", fail=True),
        backups=_Recorder(calls, "backup"),
        force=True,
    )

    assert result["ok"] is False
    assert result["errors"] == [{"step": "prune_ops_audit", "error": "ops down"}]
    assert "backup.prune" in calls
    assert "ts.checkpoint" in calls


def test_db_size_warning_over_threshold():
    calls: list[str] = []
    m = DiskMaintenance(MaintenanceConfig(db_warn_bytes=100))
    result = m.run(ts=_Recorder(calls, "ts"), force=True)
    assert "warning" in result
    assert "임계값 초과" in result["warning"]


def test_no_warning_under_threshold():
    calls: list[str] = []
    m = DiskMaintenance(MaintenanceConfig(db_warn_bytes=10_000))
    result = m.run(ts=_Recorder(calls, "ts"), force=True)
    assert "warning" not in result


def test_retention_days_passed_through(tmp_path):
    """설정한 보관 기간이 각 저장소에 전달된다."""
    received: dict[str, int] = {}

    class Store:
        def __init__(self, name):
            self.name = name

        def prune(self, days):
            received[self.name] = days
            return {"ok": True}

    m = DiskMaintenance(MaintenanceConfig(
        ops_audit_retention_days=200, audit_retention_days=30,
    ))
    m.run(ops_audit=Store("ops"), audit=Store("audit"), force=True)

    assert received == {"ops": 200, "audit": 30}


def test_scheduler_wiring_accessors_exist():
    """스케줄러 틱이 호출하는 접근자 이름을 고정한다.

    _monitoring_tick()은 예외를 debug 로그로만 남기고 삼키므로, 이름이 틀려도
    운영 중에는 조용히 유지보수가 멈춘다. 오타를 여기서 잡는다.
    """
    from coworker.server.manager import SessionManager

    for name in (
        "_get_ts_store", "_get_audit_store", "_get_backup_manager",
        "_daily_maintenance",
    ):
        assert hasattr(SessionManager, name), f"SessionManager.{name} 없음"


def test_maintenance_contract_matches_stores(tmp_path):
    """DiskMaintenance가 호출하는 메서드가 실제 저장소에 모두 존재한다."""
    ts = TimeSeriesStore(tmp_path)
    ops = OpsAuditStore(tmp_path)
    audit = AuditStore(tmp_path / "audit.db")

    for obj, methods in (
        (ts, ("downsample", "prune", "checkpoint", "db_size_bytes")),
        (ops, ("prune",)),
        (audit, ("prune",)),
    ):
        for method in methods:
            assert callable(getattr(obj, method, None)), (
                f"{type(obj).__name__}.{method} 없음"
            )


def test_end_to_end_with_real_stores(tmp_path):
    """실제 저장소로 한 사이클 — 체인이 유지되고 WAL이 정리된다."""
    ts = TimeSeriesStore(tmp_path)
    ops = OpsAuditStore(tmp_path)
    audit = AuditStore(tmp_path / "audit.db")

    base = int(time.time()) // 60 * 60
    ts.record_batch([{"server_id": "web-01", "ts": base, "cpu": 1.0}])
    _ops_entries(ops, time.time() - 400 * 86400, 5, "old")
    _ops_entries(ops, time.time(), 5, "new")
    _audit_events(audit, 5)

    result = DiskMaintenance().run(ts=ts, ops_audit=ops, audit=audit, force=True)

    assert result["ok"], result
    assert result["steps"]["prune_ops_audit"]["deleted"] == 5
    assert result["steps"]["checkpoint"]["ok"]
    assert result["steps"]["db_size"]["bytes"] > 0
    assert ops.verify_chain() == (True, None)
    assert audit.verify_chain() == (True, None)
