"""DiskMaintenance — 일 1회 디스크 관리 (성능개선 기획서 v2 Phase 6-2).

스케줄러는 30초마다 돌지만 다운샘플링·보관정책·WAL 체크포인트는 그보다
훨씬 드물게 하면 된다. 이 클래스가 자체적으로 주기를 판단하므로 호출부는
매 틱 ``run()``을 부르기만 하면 된다.

실행 순서는 다운샘플링 → 정리 → 체크포인트다. 정리로 지워질 데이터를 먼저
집계하고, 삭제로 생긴 빈 공간을 마지막에 회수하기 위해서다.

각 단계는 독립적으로 예외를 처리한다. 저장소 하나가 실패해도 나머지
정리는 진행돼야 하기 때문이다. 실패는 결과 dict의 ``errors``에 모인다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class MaintenanceConfig:
    """유지보수 주기와 보관 기간."""

    interval_seconds: float = 86400.0  # 일 1회
    ops_audit_retention_days: int = 365
    audit_retention_days: int = 90
    db_warn_bytes: int = 1024 * 1024 * 1024  # 1GB 초과 시 경고


class DiskMaintenance:
    """다운샘플링·보관정책·백업 정리·WAL 체크포인트를 주기 실행한다."""

    def __init__(self, config: MaintenanceConfig | None = None) -> None:
        self._config = config or MaintenanceConfig()
        self._last_run = 0.0

    @property
    def last_run(self) -> float:
        return self._last_run

    def due(self, now: float | None = None) -> bool:
        """다음 실행 시점이 됐는지."""
        now = time.time() if now is None else now
        return now - self._last_run >= self._config.interval_seconds

    def run(
        self,
        *,
        ts: Any = None,
        ops_audit: Any = None,
        audit: Any = None,
        backups: Any = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """유지보수 1회 실행. 주기가 안 됐으면 ``skipped``를 반환한다.

        모든 대상은 선택적이며 None이면 해당 단계를 건너뛴다.
        """
        if not force and not self.due():
            return {"ok": True, "skipped": True}

        self._last_run = time.time()
        steps: dict[str, Any] = {}
        errors: list[dict[str, str]] = []

        def step(name: str, fn: Any) -> None:
            try:
                steps[name] = fn()
            except Exception as exc:  # 한 단계 실패가 나머지를 막지 않는다
                log.warning("maintenance step %s failed: %s", name, exc)
                errors.append({"step": name, "error": str(exc)})

        # 1. 집계 — 정리로 사라질 raw 데이터를 먼저 요약한다
        if ts is not None:
            step("downsample", ts.downsample)
            step("prune_metrics", ts.prune)

        # 2. 보관정책 — 감사 로그는 체인 앵커를 갱신하며 삭제된다
        if ops_audit is not None:
            step(
                "prune_ops_audit",
                lambda: ops_audit.prune(self._config.ops_audit_retention_days),
            )
        if audit is not None:
            step(
                "prune_audit_events",
                lambda: audit.prune(self._config.audit_retention_days),
            )

        # 3. 백업 정리
        if backups is not None:
            step("prune_backups", backups.prune)

        # 4. 삭제로 생긴 공간 회수
        if ts is not None:
            step("checkpoint", ts.checkpoint)
            step("db_size", lambda: self._db_size(ts))

        result: dict[str, Any] = {"ok": not errors, "skipped": False, "steps": steps}
        if errors:
            result["errors"] = errors
        warning = steps.get("db_size", {}).get("warning") if steps.get("db_size") else None
        if warning:
            result["warning"] = warning
        return result

    def _db_size(self, ts: Any) -> dict[str, Any]:
        size = ts.db_size_bytes()
        info: dict[str, Any] = {"bytes": size, "mb": round(size / 1024 / 1024, 1)}
        if size > self._config.db_warn_bytes:
            info["warning"] = (
                f"monitoring.db {info['mb']}MB — "
                f"{self._config.db_warn_bytes // 1024 // 1024}MB 임계값 초과"
            )
            log.warning(info["warning"])
        return info
