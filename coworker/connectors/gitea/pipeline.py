"""PipelineManager — CI/CD pipeline engine for WeruBWorker.

Manages build, test, deploy pipelines triggered by Gitea webhooks.
Replaces the need for external CI runners (act_runner) with a built-in
async pipeline executor.

Pipeline stages: checkout → test → build → deploy → notify
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class PipelineStage:
    """파이프라인 단계."""
    name: str
    command: str
    working_dir: str = ""
    timeout: int = 300
    continue_on_error: bool = False


@dataclass
class PipelineConfig:
    """파이프라인 설정."""
    name: str = ""
    trigger: str = "push"            # push, tag, manual
    branch_filter: str = "main"      # 트리거 대상 브랜치
    stages: list[PipelineStage] = field(default_factory=list)
    notify_channels: list[str] = field(default_factory=list)
    auto_deploy: bool = False
    deploy_command: str = ""


@dataclass
class PipelineRun:
    """파이프라인 실행 기록."""
    id: str = ""
    pipeline_name: str = ""
    trigger: str = ""
    trigger_ref: str = ""            # 브랜치/태그
    trigger_sha: str = ""
    trigger_message: str = ""
    trigger_user: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    status: str = "running"          # pending, running, success, failed, cancelled
    stages: list[dict] = field(default_factory=list)
    error: str = ""


# 기본 파이프라인 정의
DEFAULT_PIPELINES = {
    "test": PipelineConfig(
        name="test",
        trigger="push",
        branch_filter="*",
        stages=[
            PipelineStage(name="lint", command="cd {repo_path} && python -m py_compile coworker/mcp/itms_server.py", timeout=60),
            PipelineStage(name="test", command="cd {repo_path} && .venv/bin/pytest tests/ -x -q --tb=short 2>&1 | tail -20", timeout=300),
        ],
    ),
    "deploy": PipelineConfig(
        name="deploy",
        trigger="push",
        branch_filter="main",
        auto_deploy=True,
        stages=[
            PipelineStage(name="test", command="cd {repo_path} && .venv/bin/pytest tests/ -x -q --tb=short 2>&1 | tail -20", timeout=300),
            PipelineStage(name="deploy", command="cd {repo_path} && ./start.sh --restart", timeout=60),
        ],
    ),
    "release": PipelineConfig(
        name="release",
        trigger="tag",
        stages=[
            PipelineStage(name="changelog", command="cd {repo_path} && git log --oneline $(git describe --tags --abbrev=0 HEAD~1 2>/dev/null || echo HEAD~10)..HEAD", timeout=30),
        ],
    ),
}


class PipelineManager:
    """CI/CD 파이프라인 관리자."""

    def __init__(self, data_dir: str | Path, repo_path: str = "", gitea_client: Any = None) -> None:
        import sqlite3
        self._data_dir = Path(data_dir)
        self._repo_path = repo_path or str(Path(__file__).resolve().parents[3])
        self._gc = gitea_client
        self._db_path = self._data_dir / "pipelines.db"
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()
        self._pipelines: dict[str, PipelineConfig] = dict(DEFAULT_PIPELINES)
        self._running: set[str] = set()

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id TEXT PRIMARY KEY,
                pipeline_name TEXT NOT NULL,
                trigger TEXT DEFAULT '',
                trigger_ref TEXT DEFAULT '',
                trigger_sha TEXT DEFAULT '',
                trigger_message TEXT DEFAULT '',
                trigger_user TEXT DEFAULT '',
                started_at REAL,
                finished_at REAL,
                status TEXT DEFAULT 'pending',
                stages TEXT DEFAULT '[]',
                error TEXT DEFAULT ''
            );
        """)
        self._db.commit()

    async def on_push(self, repo: str, branch: str, sha: str, message: str, user: str) -> list[dict]:
        """push 이벤트 처리 → 매칭 파이프라인 실행."""
        results = []
        for name, config in self._pipelines.items():
            if config.trigger != "push":
                continue
            if config.branch_filter != "*" and config.branch_filter != branch:
                continue
            result = await self.run(name, trigger="push", ref=branch, sha=sha, message=message, user=user)
            results.append(result)
        return results

    async def on_tag(self, repo: str, tag: str, sha: str, user: str) -> list[dict]:
        """태그 이벤트 처리 → release 파이프라인 + 릴리즈 자동 생성."""
        results = []
        for name, config in self._pipelines.items():
            if config.trigger != "tag":
                continue
            result = await self.run(name, trigger="tag", ref=tag, sha=sha, user=user)
            results.append(result)

            # 릴리즈 자동 생성
            if self._gc and result.get("status") == "success":
                changelog = ""
                for stage in result.get("stages", []):
                    if stage.get("name") == "changelog":
                        changelog = stage.get("output", "")
                await self._create_release(repo, tag, changelog)

        return results

    async def run(self, pipeline_name: str, trigger: str = "manual", ref: str = "", sha: str = "", message: str = "", user: str = "") -> dict:
        """파이프라인 실행."""
        import secrets as _secrets

        config = self._pipelines.get(pipeline_name)
        if not config:
            return {"ok": False, "error": f"pipeline '{pipeline_name}' not found"}

        run_id = f"run-{_secrets.token_hex(5)}"

        # 중복 실행 방지
        if pipeline_name in self._running:
            return {"ok": False, "error": "pipeline already running"}
        self._running.add(pipeline_name)

        now = time.time()
        self._db.execute(
            "INSERT INTO pipeline_runs (id, pipeline_name, trigger, trigger_ref, trigger_sha, trigger_message, trigger_user, started_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running')",
            (run_id, pipeline_name, trigger, ref, sha, message[:200], user, now),
        )
        self._db.commit()

        stages_result = []
        final_status = "success"
        error = ""

        for stage in config.stages:
            stage_start = time.time()
            cmd = stage.command.replace("{repo_path}", self._repo_path)

            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=stage.working_dir or self._repo_path,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=stage.timeout
                )
                ok = proc.returncode == 0
                output = stdout.decode("utf-8", errors="replace")[:3000]
                err_output = stderr.decode("utf-8", errors="replace")[:1000]

                stages_result.append({
                    "name": stage.name,
                    "status": "success" if ok else "failed",
                    "exit_code": proc.returncode,
                    "output": output,
                    "error": err_output if not ok else "",
                    "duration_ms": round((time.time() - stage_start) * 1000),
                })

                if not ok and not stage.continue_on_error:
                    final_status = "failed"
                    error = f"stage '{stage.name}' failed (exit {proc.returncode})"
                    break

            except asyncio.TimeoutError:
                stages_result.append({
                    "name": stage.name, "status": "timeout",
                    "duration_ms": stage.timeout * 1000,
                    "error": f"timeout after {stage.timeout}s",
                })
                final_status = "failed"
                error = f"stage '{stage.name}' timed out"
                break

            except Exception as e:
                stages_result.append({
                    "name": stage.name, "status": "error", "error": str(e),
                    "duration_ms": round((time.time() - stage_start) * 1000),
                })
                final_status = "failed"
                error = str(e)
                break

        finished = time.time()
        self._db.execute(
            "UPDATE pipeline_runs SET finished_at = ?, status = ?, stages = ?, error = ? WHERE id = ?",
            (finished, final_status, json.dumps(stages_result), error, run_id),
        )
        self._db.commit()
        self._running.discard(pipeline_name)

        return {
            "ok": final_status == "success",
            "id": run_id,
            "pipeline": pipeline_name,
            "status": final_status,
            "duration_ms": round((finished - now) * 1000),
            "stages": stages_result,
            "error": error,
        }

    async def _create_release(self, repo: str, tag: str, changelog: str) -> None:
        """Gitea 릴리즈 자동 생성."""
        if not self._gc:
            return
        parts = repo.split("/")
        if len(parts) != 2:
            return
        owner, repo_name = parts
        body = f"## 변경 내역\n\n```\n{changelog}\n```\n\n---\n*자동 생성 by WeruBWorker CI/CD*"
        try:
            await self._gc.releases.create(owner, repo_name, tag_name=tag, name=tag, body=body)
            log.info("auto-created release %s for %s", tag, repo)
        except Exception as e:
            log.warning("release creation failed: %s", e)

    def list_pipelines(self) -> list[dict]:
        """파이프라인 목록."""
        return [{
            "name": c.name, "trigger": c.trigger,
            "branch_filter": c.branch_filter,
            "stages": [s.name for s in c.stages],
            "auto_deploy": c.auto_deploy,
        } for c in self._pipelines.values()]

    def list_runs(self, pipeline_name: str = "", limit: int = 20) -> list[dict]:
        """실행 이력."""
        sql = "SELECT id, pipeline_name, trigger, trigger_ref, trigger_sha, trigger_user, started_at, finished_at, status, error FROM pipeline_runs"
        params: list = []
        if pipeline_name:
            sql += " WHERE pipeline_name = ?"
            params.append(pipeline_name)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = self._db.execute(sql, params).fetchall()
        return [{
            "id": r[0], "pipeline": r[1], "trigger": r[2], "ref": r[3],
            "sha": r[4][:8] if r[4] else "", "user": r[5],
            "started_at": r[6], "finished_at": r[7],
            "status": r[8], "error": r[9],
            "duration_ms": round((r[7] - r[6]) * 1000) if r[7] and r[6] else 0,
        } for r in rows]

    def get_run(self, run_id: str) -> dict | None:
        """실행 상세."""
        row = self._db.execute(
            "SELECT id, pipeline_name, trigger, trigger_ref, trigger_sha, trigger_message, trigger_user, started_at, finished_at, status, stages, error FROM pipeline_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "pipeline": row[1], "trigger": row[2], "ref": row[3],
            "sha": row[4], "message": row[5], "user": row[6],
            "started_at": row[7], "finished_at": row[8], "status": row[9],
            "stages": json.loads(row[10]) if row[10] else [],
            "error": row[11],
        }
