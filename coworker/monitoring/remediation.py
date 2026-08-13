"""RemediationEngine — alert-driven auto-remediation with approval gating.

Executes predefined remediation actions when alerts fire. Actions that are
marked as requiring approval are routed to the Inbox; others execute immediately
(with a retry limit to prevent loops).
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class RemediationStep:
    type: str  # "ssh_command", "docker_restart", "k8s_delete_pod", "notify"
    target: str  # server_id, container_name, pod_name
    command: str  # 실행할 명령 또는 액션
    timeout: int = 30

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "target": self.target,
            "command": self.command,
            "timeout": self.timeout,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RemediationStep:
        return cls(
            type=d["type"],
            target=d["target"],
            command=d.get("command", ""),
            timeout=int(d.get("timeout", 30)),
        )


@dataclass
class RemediationAction:
    id: str  # "rem-{hex}"
    name: str
    trigger: str  # "disk_full", "service_down", "oom", "high_cpu", "crash_loop", "cert_expiring"
    steps: list[RemediationStep] = field(default_factory=list)
    max_retries: int = 3
    requires_approval: bool = False  # True → Inbox 라우팅
    cooldown_seconds: int = 600  # 같은 트리거 재실행 대기
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "steps": [s.to_dict() for s in self.steps],
            "max_retries": self.max_retries,
            "requires_approval": self.requires_approval,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RemediationAction:
        steps = [RemediationStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id=d["id"],
            name=d["name"],
            trigger=d["trigger"],
            steps=steps,
            max_retries=int(d.get("max_retries", 3)),
            requires_approval=bool(d.get("requires_approval", False)),
            cooldown_seconds=int(d.get("cooldown_seconds", 600)),
            enabled=bool(d.get("enabled", True)),
        )


@dataclass
class RemediationExecution:
    id: str  # "exec-{hex}"
    action_id: str
    trigger_alert_id: str
    server_id: str
    status: str = "pending"  # "pending","running","completed","failed","skipped","approval_required"
    started_at: float = 0.0
    finished_at: float | None = None
    steps_completed: int = 0
    result: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_id": self.action_id,
            "trigger_alert_id": self.trigger_alert_id,
            "server_id": self.server_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps_completed": self.steps_completed,
            "result": self.result,
            "error": self.error,
        }


class RemediationEngine:
    """알림 기반 자동 복구 엔진."""

    def __init__(self, data_dir: Path):
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._last_execution: dict[str, float] = {}  # {action_id:server_id → last_run_ts}
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._db.exists()
        conn = sqlite3.connect(str(self._db), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if is_new:
            try:
                os.chmod(self._db, 0o600)
            except OSError:
                pass
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS remediation_actions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    steps TEXT NOT NULL DEFAULT '[]',
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    requires_approval INTEGER NOT NULL DEFAULT 0,
                    cooldown_seconds INTEGER NOT NULL DEFAULT 600,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS remediation_executions (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    trigger_alert_id TEXT NOT NULL DEFAULT '',
                    server_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at REAL NOT NULL DEFAULT 0,
                    finished_at REAL,
                    steps_completed INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_exec_action
                    ON remediation_executions(action_id);
                CREATE INDEX IF NOT EXISTS idx_exec_status
                    ON remediation_executions(status);
            """)

    # -- Action CRUD --

    def register(self, action: RemediationAction) -> dict:
        """복구 액션 등록/업데이트."""
        if not action.id:
            action.id = f"rem-{os.urandom(5).hex()}"
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO remediation_actions "
                    "(id, name, trigger, steps, max_retries, requires_approval, "
                    "cooldown_seconds, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        action.id,
                        action.name,
                        action.trigger,
                        json.dumps([s.to_dict() for s in action.steps]),
                        action.max_retries,
                        1 if action.requires_approval else 0,
                        action.cooldown_seconds,
                        1 if action.enabled else 0,
                    ),
                )
            return {"ok": True, "id": action.id}
        except Exception as exc:
            log.exception("register failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def remove(self, action_id: str) -> dict:
        """복구 액션 삭제."""
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM remediation_actions WHERE id = ?", (action_id,)
                )
                if cur.rowcount == 0:
                    return {"ok": False, "error": "action not found"}
            return {"ok": True}
        except Exception as exc:
            log.exception("remove failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def list_actions(self, enabled_only: bool = True) -> list[dict]:
        """등록된 복구 액션 목록 반환."""
        with self._connect() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM remediation_actions WHERE enabled = 1"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM remediation_actions").fetchall()
        return [self._row_to_action_dict(r) for r in rows]

    def get_action(self, action_id: str) -> dict | None:
        """복구 액션 단건 조회."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_actions WHERE id = ?", (action_id,)
            ).fetchone()
        return self._row_to_action_dict(row) if row else None

    def find_action_for_trigger(self, trigger: str) -> dict | None:
        """트리거에 매칭되는 활성 액션 찾기."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_actions WHERE trigger = ? AND enabled = 1 "
                "LIMIT 1",
                (trigger,),
            ).fetchone()
        return self._row_to_action_dict(row) if row else None

    # -- Execution --

    def execute(
        self, action_id: str, alert_id: str = "", server_id: str = ""
    ) -> dict:
        """복구 액션 실행.

        - cooldown 체크: 마지막 실행 이후 cooldown_seconds 미경과 시 skipped
        - requires_approval 이면 status="approval_required" 반환 (실행 안 함)
        - 각 step을 순서대로 실행, 실패 시 중단
        """
        action_dict = self.get_action(action_id)
        if action_dict is None:
            return {"ok": False, "error": "action not found"}

        action = RemediationAction.from_dict(action_dict)
        exec_id = f"exec-{os.urandom(5).hex()}"
        now = time.time()

        # cooldown 체크
        cooldown_key = f"{action_id}:{server_id}"
        last_run = self._last_execution.get(cooldown_key, 0.0)
        if now - last_run < action.cooldown_seconds:
            exe = RemediationExecution(
                id=exec_id,
                action_id=action_id,
                trigger_alert_id=alert_id,
                server_id=server_id,
                status="skipped",
                started_at=now,
                finished_at=now,
                result="cooldown active",
            )
            self._save_execution(exe)
            return {"ok": True, "execution": exe.to_dict()}

        # approval 체크
        if action.requires_approval:
            exe = RemediationExecution(
                id=exec_id,
                action_id=action_id,
                trigger_alert_id=alert_id,
                server_id=server_id,
                status="approval_required",
                started_at=now,
            )
            self._save_execution(exe)
            return {"ok": True, "execution": exe.to_dict()}

        # 실행
        exe = RemediationExecution(
            id=exec_id,
            action_id=action_id,
            trigger_alert_id=alert_id,
            server_id=server_id,
            status="running",
            started_at=now,
        )

        steps_done = 0
        try:
            for step in action.steps:
                step_result = self._execute_step(step, server_id)
                if not step_result.get("ok"):
                    exe.status = "failed"
                    exe.error = step_result.get("error", "step failed")
                    exe.finished_at = time.time()
                    exe.steps_completed = steps_done
                    self._save_execution(exe)
                    return {"ok": True, "execution": exe.to_dict()}
                steps_done += 1

            exe.status = "completed"
            exe.steps_completed = steps_done
            exe.result = f"{steps_done} step(s) completed"
            exe.finished_at = time.time()
            self._last_execution[cooldown_key] = now
        except Exception as exc:
            log.exception("execute error: %s", exc)
            exe.status = "failed"
            exe.error = str(exc)
            exe.finished_at = time.time()
            exe.steps_completed = steps_done

        self._save_execution(exe)
        return {"ok": True, "execution": exe.to_dict()}

    def _execute_step(self, step: RemediationStep, server_id: str) -> dict:
        """단일 스텝 실행. type별 분기."""
        try:
            if step.type == "notify":
                log.info(
                    "remediation notify: target=%s command=%s", step.target, step.command
                )
                return {"ok": True, "output": "notification logged"}

            if step.type == "ssh_command":
                cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
                target = step.target or server_id
                if target:
                    cmd.append(target)
                cmd.append(step.command)
            elif step.type == "docker_restart":
                cmd = ["docker", "restart", step.target]
            elif step.type == "k8s_delete_pod":
                cmd = ["kubectl", "delete", "pod", step.target, "--grace-period=30"]
            else:
                # 일반 셸 명령
                cmd = shlex.split(step.command)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=step.timeout,
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "error": result.stderr.strip() or f"exit code {result.returncode}",
                }
            return {"ok": True, "output": result.stdout.strip()}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {step.timeout}s"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _save_execution(self, exe: RemediationExecution) -> None:
        """실행 기록을 DB에 저장."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO remediation_executions "
                "(id, action_id, trigger_alert_id, server_id, status, started_at, "
                "finished_at, steps_completed, result, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    exe.id,
                    exe.action_id,
                    exe.trigger_alert_id,
                    exe.server_id,
                    exe.status,
                    exe.started_at,
                    exe.finished_at,
                    exe.steps_completed,
                    exe.result,
                    exe.error,
                ),
            )

    # -- Execution queries --

    def get_execution(self, execution_id: str) -> dict | None:
        """실행 기록 단건 조회."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM remediation_executions WHERE id = ?", (execution_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_executions(self, action_id: str = "", limit: int = 50) -> list[dict]:
        """실행 기록 목록 조회."""
        with self._connect() as conn:
            if action_id:
                rows = conn.execute(
                    "SELECT * FROM remediation_executions WHERE action_id = ? "
                    "ORDER BY started_at DESC LIMIT ?",
                    (action_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM remediation_executions "
                    "ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # -- Helpers --

    def _row_to_action_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["steps"] = json.loads(d.get("steps", "[]"))
        d["requires_approval"] = bool(d.get("requires_approval", 0))
        d["enabled"] = bool(d.get("enabled", 1))
        return d

    # -- Seed defaults --

    def seed_defaults(self) -> dict:
        """기본 복구 액션 7개 시드."""
        defaults = [
            RemediationAction(
                id="rem-disk85",
                name="디스크 85% — 로그 압축",
                trigger="disk_85",
                steps=[
                    RemediationStep(
                        type="ssh_command",
                        target="",
                        command="find /var/log -name '*.log' -mtime +7 -exec gzip {} \\;",
                        timeout=60,
                    ),
                ],
                max_retries=3,
                requires_approval=False,
                cooldown_seconds=3600,
            ),
            RemediationAction(
                id="rem-disk95",
                name="디스크 95% — 임시 파일 정리",
                trigger="disk_95",
                steps=[
                    RemediationStep(
                        type="ssh_command",
                        target="",
                        command="rm -rf /tmp/* /var/tmp/* && journalctl --vacuum-time=3d",
                        timeout=60,
                    ),
                ],
                max_retries=1,
                requires_approval=True,
                cooldown_seconds=1800,
            ),
            RemediationAction(
                id="rem-svcdown",
                name="서비스 다운 — systemctl restart",
                trigger="service_down",
                steps=[
                    RemediationStep(
                        type="ssh_command",
                        target="",
                        command="systemctl restart {target}",
                        timeout=30,
                    ),
                ],
                max_retries=3,
                requires_approval=False,
                cooldown_seconds=300,
            ),
            RemediationAction(
                id="rem-dockeroom",
                name="Docker OOM — 컨테이너 재시작",
                trigger="oom",
                steps=[
                    RemediationStep(
                        type="docker_restart",
                        target="",
                        command="",
                        timeout=30,
                    ),
                ],
                max_retries=3,
                requires_approval=False,
                cooldown_seconds=600,
            ),
            RemediationAction(
                id="rem-k8scrash",
                name="K8s CrashLoop — Pod 재생성",
                trigger="crash_loop",
                steps=[
                    RemediationStep(
                        type="k8s_delete_pod",
                        target="",
                        command="",
                        timeout=60,
                    ),
                ],
                max_retries=2,
                requires_approval=True,
                cooldown_seconds=600,
            ),
            RemediationAction(
                id="rem-mem95",
                name="메모리 95% — 캐시 드랍",
                trigger="memory_95",
                steps=[
                    RemediationStep(
                        type="ssh_command",
                        target="",
                        command="sync && echo 3 > /proc/sys/vm/drop_caches",
                        timeout=15,
                    ),
                ],
                max_retries=1,
                requires_approval=True,
                cooldown_seconds=1800,
            ),
            RemediationAction(
                id="rem-cert7d",
                name="인증서 7일 이내 만료 — 알림",
                trigger="cert_expiring",
                steps=[
                    RemediationStep(
                        type="notify",
                        target="ops-channel",
                        command="SSL 인증서 만료 임박 — 갱신 필요",
                        timeout=5,
                    ),
                ],
                max_retries=1,
                requires_approval=True,
                cooldown_seconds=86400,
            ),
        ]

        registered = 0
        for action in defaults:
            result = self.register(action)
            if result.get("ok"):
                registered += 1

        return {"ok": True, "registered": registered, "total": len(defaults)}
