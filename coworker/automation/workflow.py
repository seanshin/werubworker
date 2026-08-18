"""Workflow — conditional multi-step automation engine.

Supports if/then/else branching based on metric values, time conditions,
and previous step results.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class WorkflowCondition:
    """워크플로우 조건식."""
    type: str = "metric"  # metric, time, result, always
    metric: str = ""      # cpu, memory, disk 등
    operator: str = ">"   # >, <, >=, <=, ==
    value: float = 0.0
    server_id: str = ""
    time_range: str = ""  # "09:00-18:00" (business hours)


@dataclass
class WorkflowStep:
    """워크플로우 단계."""
    id: str = ""
    name: str = ""
    action: str = ""           # shell, ssh, notify, remediate, check
    target: str = ""           # 서버 ID 또는 명령
    command: str = ""
    condition: WorkflowCondition | None = None  # 실행 조건
    on_success: str = ""       # 다음 step ID (성공 시)
    on_failure: str = ""       # 다음 step ID (실패 시)
    timeout: int = 60


@dataclass
class Workflow:
    """워크플로우 정의."""
    id: str = ""
    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    entry_step: str = ""       # 시작 step ID
    enabled: bool = True
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class WorkflowExecution:
    """워크플로우 실행 기록."""
    id: str = ""
    workflow_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    status: str = "running"    # running, completed, failed
    steps_executed: list[dict] = field(default_factory=list)
    error: str = ""


class WorkflowEngine:
    """조건부 워크플로우 실행 엔진."""

    def __init__(self, data_dir: str | Path) -> None:
        import sqlite3
        self._db_path = Path(data_dir) / "workflows.db"
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                steps TEXT NOT NULL DEFAULT '[]',
                entry_step TEXT DEFAULT '',
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                started_at REAL,
                finished_at REAL,
                status TEXT DEFAULT 'running',
                steps_executed TEXT DEFAULT '[]',
                error TEXT DEFAULT ''
            );
        """)
        self._db.commit()

    def create(self, name: str, description: str, steps: list[dict], entry_step: str = "") -> dict:
        """워크플로우 생성."""
        import secrets as _secrets
        wf_id = f"wf-{_secrets.token_hex(5)}"
        now = time.time()
        if not entry_step and steps:
            entry_step = steps[0].get("id", "step-1")
        self._db.execute(
            "INSERT INTO workflows (id, name, description, steps, entry_step, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (wf_id, name, description, json.dumps(steps), entry_step, now, now),
        )
        self._db.commit()
        return {"ok": True, "id": wf_id}

    def get(self, workflow_id: str) -> dict | None:
        row = self._db.execute("SELECT id, name, description, steps, entry_step, enabled, created_at, updated_at FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "description": row[2], "steps": json.loads(row[3]), "entry_step": row[4], "enabled": bool(row[5]), "created_at": row[6], "updated_at": row[7]}

    def list_workflows(self) -> list[dict]:
        rows = self._db.execute("SELECT id, name, description, entry_step, enabled, created_at, updated_at FROM workflows ORDER BY updated_at DESC").fetchall()
        return [{"id": r[0], "name": r[1], "description": r[2], "entry_step": r[3], "enabled": bool(r[4]), "created_at": r[5], "updated_at": r[6]} for r in rows]

    def delete(self, workflow_id: str) -> dict:
        self._db.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        self._db.commit()
        return {"ok": True}

    def update(self, workflow_id: str, **kwargs) -> dict:
        sets = []
        params = []
        for key in ("name", "description", "enabled"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                params.append(kwargs[key] if key != "enabled" else int(kwargs[key]))
        if "steps" in kwargs:
            sets.append("steps = ?")
            params.append(json.dumps(kwargs["steps"]))
        if "entry_step" in kwargs:
            sets.append("entry_step = ?")
            params.append(kwargs["entry_step"])
        if sets:
            sets.append("updated_at = ?")
            params.append(time.time())
            params.append(workflow_id)
            self._db.execute(f"UPDATE workflows SET {', '.join(sets)} WHERE id = ?", params)
            self._db.commit()
        return {"ok": True}

    async def execute(self, workflow_id: str, context: dict | None = None) -> dict:
        """워크플로우를 실행한다."""
        import secrets as _secrets
        wf = self.get(workflow_id)
        if not wf:
            return {"ok": False, "error": "workflow not found"}
        if not wf.get("enabled"):
            return {"ok": False, "error": "workflow disabled"}

        exec_id = f"wfr-{_secrets.token_hex(5)}"
        now = time.time()
        self._db.execute(
            "INSERT INTO workflow_executions (id, workflow_id, started_at, status) VALUES (?, ?, ?, 'running')",
            (exec_id, workflow_id, now),
        )
        self._db.commit()

        steps_map = {s.get("id", f"step-{i}"): s for i, s in enumerate(wf["steps"])}
        current_step_id = wf.get("entry_step") or (wf["steps"][0].get("id") if wf["steps"] else "")
        steps_executed = []
        ctx = context or {}
        final_status = "completed"
        error = ""

        while current_step_id and current_step_id in steps_map:
            step = steps_map[current_step_id]

            # 조건 평가
            condition = step.get("condition")
            if condition and not self._evaluate_condition(condition, ctx):
                steps_executed.append({"step_id": current_step_id, "status": "skipped", "reason": "condition not met"})
                current_step_id = step.get("on_failure", "")
                continue

            # 단계 실행
            try:
                result = await self._execute_step(step, ctx)
                steps_executed.append({"step_id": current_step_id, "status": "ok", "result": str(result.get("output", ""))[:500]})
                ctx["last_result"] = result
                current_step_id = step.get("on_success", "")
            except Exception as e:
                steps_executed.append({"step_id": current_step_id, "status": "failed", "error": str(e)})
                error = str(e)
                current_step_id = step.get("on_failure", "")
                if not current_step_id:
                    final_status = "failed"
                    break

            # 무한 루프 방지
            if len(steps_executed) > 50:
                final_status = "failed"
                error = "max steps exceeded"
                break

        self._db.execute(
            "UPDATE workflow_executions SET finished_at = ?, status = ?, steps_executed = ?, error = ? WHERE id = ?",
            (time.time(), final_status, json.dumps(steps_executed), error, exec_id),
        )
        self._db.commit()

        return {"ok": True, "execution_id": exec_id, "status": final_status, "steps_executed": steps_executed, "error": error}

    def _evaluate_condition(self, condition: dict, ctx: dict) -> bool:
        """조건식을 평가한다."""
        ctype = condition.get("type", "always")
        if ctype == "always":
            return True
        if ctype == "result":
            last = ctx.get("last_result", {})
            return last.get("ok", False)
        if ctype == "metric":
            # ctx에서 메트릭 값 조회
            metric_val = ctx.get("metrics", {}).get(condition.get("server_id", ""), {}).get(condition.get("metric", ""), 0)
            op = condition.get("operator", ">")
            threshold = condition.get("value", 0)
            if op == ">": return metric_val > threshold
            if op == "<": return metric_val < threshold
            if op == ">=": return metric_val >= threshold
            if op == "<=": return metric_val <= threshold
            if op == "==": return metric_val == threshold
        if ctype == "time":
            time_range = condition.get("time_range", "")
            if "-" in time_range:
                start_h, end_h = time_range.split("-")
                import datetime
                now_h = datetime.datetime.now().strftime("%H:%M")
                return start_h.strip() <= now_h <= end_h.strip()
        return True

    async def _execute_step(self, step: dict, ctx: dict) -> dict:
        """단계를 실행한다."""
        import asyncio
        action = step.get("action", "")

        if action == "shell":
            proc = await asyncio.create_subprocess_shell(
                step.get("command", "echo ok"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=step.get("timeout", 60))
            return {"ok": proc.returncode == 0, "output": stdout.decode()[:2000], "error": stderr.decode()[:500]}

        if action == "ssh":
            from ..connectors.ssh.client import SSHClient, SSHServer
            server_id = step.get("target", "")
            secrets = ctx.get("secrets")
            if secrets:
                profile = secrets.get(f"ssh:server:{server_id}") or {}
                server = SSHServer(server_id=server_id, host=profile.get("host", ""), port=profile.get("port", 22), username=profile.get("username", "deploy"), key_path=profile.get("key_path"))
                client = SSHClient(server)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: client.execute(step.get("command", "echo ok"), timeout=step.get("timeout", 30)))
                return result
            return {"ok": False, "error": "no secrets context"}

        if action == "notify":
            log.info("workflow notify: %s", step.get("command", ""))
            return {"ok": True, "output": f"notified: {step.get('command', '')}"}

        if action == "check":
            # 헬스체크 실행
            return {"ok": True, "output": "check placeholder"}

        return {"ok": True, "output": "no-op"}

    def list_executions(self, workflow_id: str = "", limit: int = 20) -> list[dict]:
        sql = "SELECT id, workflow_id, started_at, finished_at, status, error FROM workflow_executions"
        params: list = []
        if workflow_id:
            sql += " WHERE workflow_id = ?"
            params.append(workflow_id)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = self._db.execute(sql, params).fetchall()
        return [{"id": r[0], "workflow_id": r[1], "started_at": r[2], "finished_at": r[3], "status": r[4], "error": r[5]} for r in rows]
