"""MCP Server for WeruBWorker ITMS (IT Management System) integration.

Exposes a unified IT service management interface as an MCP server:
security scanning, backup/restore, workflow automation, batch operations,
anomaly detection, and postmortem generation — the full v2.3 toolset.

This complements the monitoring_server (metrics/alerts/incidents) with
operational management capabilities for CIO-level IT governance.

Usage:
    python -m coworker.mcp.itms_server

    # Or add to .mcp.json / Claude Desktop config:
    {
      "mcpServers": {
        "werubworker-itms": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "coworker.mcp.itms_server"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------


def _data_dir() -> Path:
    from ..secrets import state_dir

    return state_dir()


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_backup = None
_anomaly = None
_postmortem = None
_workflow = None
_batch = None
_secrets_store = None
_gitea = None


def _get_secrets():
    global _secrets_store
    if _secrets_store is None:
        from ..secrets import SecretStore

        _secrets_store = SecretStore()
    return _secrets_store


def _get_backup():
    global _backup
    if _backup is None:
        from ..monitoring.backup import BackupManager

        _backup = BackupManager(_data_dir())
    return _backup


def _get_anomaly():
    global _anomaly
    if _anomaly is None:
        from ..monitoring.anomaly import AnomalyDetector
        from ..monitoring.timeseries import TimeSeriesStore

        ts = TimeSeriesStore(_data_dir())
        _anomaly = AnomalyDetector(ts)
    return _anomaly


def _get_postmortem():
    global _postmortem
    if _postmortem is None:
        from ..monitoring.postmortem import PostmortemGenerator
        from ..monitoring.incidents import IncidentManager
        from ..monitoring.timeseries import TimeSeriesStore
        from ..monitoring.alerting import AlertEngine

        _postmortem = PostmortemGenerator(
            IncidentManager(_data_dir()),
            TimeSeriesStore(_data_dir()),
            AlertEngine(_data_dir()),
        )
    return _postmortem


def _get_workflow():
    global _workflow
    if _workflow is None:
        from ..automation.workflow import WorkflowEngine

        _workflow = WorkflowEngine(_data_dir())
    return _workflow


def _get_batch():
    global _batch
    if _batch is None:
        from ..connectors.ssh.batch import BatchSSH

        _batch = BatchSSH(secrets=_get_secrets())
    return _batch


def _get_gitea():
    global _gitea
    if _gitea is None:
        from ..connectors.gitea.client import GiteaClient
        secrets = _get_secrets()
        token = ""
        gitea_conf = secrets.get("gitea") if secrets else None
        if isinstance(gitea_conf, dict):
            token = gitea_conf.get("token", "")
        _gitea = GiteaClient(base_url="http://localhost:3000", token=token)
    return _gitea


# ---------------------------------------------------------------------------
# Tool definitions — 32 ITMS tools
# ---------------------------------------------------------------------------

TOOLS = [
    # ── Security ──
    Tool(
        name="security_score",
        description="종합 보안 점수 산출 (SSL, 포트, 방화벽, 인증 로그 기반 A~D 등급).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 로컬)"},
            },
        },
    ),
    Tool(
        name="container_scan",
        description="컨테이너 이미지 취약점 스캔 (Trivy CLI 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Docker 이미지명 (예: nginx:latest)"},
            },
            "required": ["image"],
        },
    ),
    Tool(
        name="dependency_audit",
        description="프로젝트 의존성 취약점 검사 (npm audit / pip-audit 자동 감지).",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "프로젝트 경로 (기본: .)"},
                "type": {"type": "string", "description": "감지 유형: auto, npm, pip"},
            },
        },
    ),
    Tool(
        name="firewall_check",
        description="방화벽 규칙 검증 (iptables/ufw/nftables).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 로컬)"},
            },
        },
    ),
    # ── Backup ──
    Tool(
        name="backup_create",
        description="WeruBWorker 데이터 백업 생성 (Wiki, 메트릭, 알림, 인시던트 등 8개 DB).",
        inputSchema={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "백업 대상 (wiki, metrics, alerts, incidents 등). 비어있으면 전체.",
                },
            },
        },
    ),
    Tool(
        name="backup_list",
        description="백업 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 건수 (기본 20)"},
            },
        },
    ),
    Tool(
        name="backup_restore",
        description="백업에서 데이터 복원.",
        inputSchema={
            "type": "object",
            "properties": {
                "backup_id": {"type": "string", "description": "백업 ID"},
            },
            "required": ["backup_id"],
        },
    ),
    # ── Anomaly Detection ──
    Tool(
        name="anomaly_detect",
        description="서버 메트릭 이상 탐지 (Z-score 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 전체)"},
                "window": {"type": "integer", "description": "분석 윈도우 (분, 기본 60)"},
            },
        },
    ),
    # ── Postmortem ──
    Tool(
        name="postmortem_generate",
        description="인시던트 사후분석 보고서 생성 (타임라인 + 관련 알림 + 메트릭 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "인시던트 ID"},
            },
            "required": ["incident_id"],
        },
    ),
    # ── Workflow ──
    Tool(
        name="workflow_list",
        description="등록된 조건부 워크플로우 목록 조회.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="workflow_execute",
        description="워크플로우 실행 (조건부 if/then/else 분기 포함).",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "워크플로우 ID"},
            },
            "required": ["workflow_id"],
        },
    ),
    # ── Batch SSH ──
    Tool(
        name="batch_execute",
        description="멀티 서버 일괄 SSH 명령 실행 (병렬 또는 롤링).",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "실행할 명령어"},
                "tag": {"type": "string", "description": "서버 태그 필터 (비어있으면 전체)"},
                "mode": {"type": "string", "description": "parallel 또는 rolling (기본 parallel)"},
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="batch_servers",
        description="등록된 SSH 서버 목록 및 태그 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "태그 필터 (비어있으면 전체)"},
            },
        },
    ),
    # ── Gitea ──
    Tool(
        name="gitea_repos",
        description="로컬 Gitea 리포지토리 목록 조회.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="gitea_webhook_events",
        description="최근 Gitea Webhook 이벤트 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 건수 (기본 30)"},
                "repo": {"type": "string", "description": "리포 필터 (비어있으면 전체)"},
            },
        },
    ),
    Tool(
        name="gitea_repo_detail",
        description="Gitea 리포 상세 정보 (언어, 기여자, 토픽).",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "소유자"},
                "repo": {"type": "string", "description": "리포 이름"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_branches",
        description="Gitea 리포 브랜치 목록/생성/삭제.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "action": {"type": "string", "description": "list, create, delete (기본 list)"},
                "name": {"type": "string", "description": "브랜치명 (create/delete 시)"},
                "from": {"type": "string", "description": "기반 브랜치 (create 시, 기본 main)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_pulls",
        description="Gitea PR 목록 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "state": {"type": "string", "description": "open, closed, all (기본 open)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_create_pr",
        description="Gitea PR 생성.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "title": {"type": "string"}, "head": {"type": "string"},
                "base": {"type": "string", "description": "기본 main"},
                "body": {"type": "string"},
            },
            "required": ["owner", "repo", "title", "head"],
        },
    ),
    Tool(
        name="gitea_issues",
        description="Gitea 이슈 목록/생성.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "action": {"type": "string", "description": "list 또는 create (기본 list)"},
                "title": {"type": "string", "description": "이슈 제목 (create 시)"},
                "body": {"type": "string", "description": "이슈 내용 (create 시)"},
                "state": {"type": "string", "description": "open, closed (list 시)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_releases",
        description="Gitea 릴리즈 목록/생성.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "action": {"type": "string", "description": "list 또는 create (기본 list)"},
                "tag_name": {"type": "string", "description": "태그명 (create 시)"},
                "name": {"type": "string", "description": "릴리즈명 (create 시)"},
                "body": {"type": "string", "description": "릴리즈 노트 (create 시)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_file_read",
        description="Gitea 리포 파일 내용 읽기.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "filepath": {"type": "string", "description": "파일 경로"},
                "ref": {"type": "string", "description": "브랜치/태그 (기본 main)"},
            },
            "required": ["owner", "repo", "filepath"],
        },
    ),
    Tool(
        name="gitea_file_write",
        description="Gitea 리포 파일 생성/수정 + 자동 커밋.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "filepath": {"type": "string"}, "content": {"type": "string"},
                "message": {"type": "string", "description": "커밋 메시지"},
                "sha": {"type": "string", "description": "기존 파일 SHA (수정 시, 비어있으면 신규 생성)"},
            },
            "required": ["owner", "repo", "filepath", "content"],
        },
    ),
    Tool(
        name="gitea_commits",
        description="Gitea 커밋 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "limit": {"type": "integer", "description": "최대 건수 (기본 20)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_file_tree",
        description="Gitea 리포 파일 트리 (전체 파일 목록).",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "ref": {"type": "string", "description": "브랜치 (기본 main)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_pr_review",
        description="Gitea PR AI 코드 리뷰 실행 (diff 분석, 보안/품질 검사, 자동 라벨링).",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "pr_number": {"type": "integer", "description": "PR 번호"},
            },
            "required": ["owner", "repo", "pr_number"],
        },
    ),
    Tool(
        name="gitea_merge_check",
        description="Gitea PR 머지 전 체크리스트 검증 (충돌, 리뷰 승인, 머지 가능 여부).",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "pr_number": {"type": "integer"},
            },
            "required": ["owner", "repo", "pr_number"],
        },
    ),
    # ── CI/CD Pipeline ──
    Tool(
        name="gitea_pipeline_run",
        description="CI/CD 파이프라인 수동 실행 (test, deploy, release).",
        inputSchema={
            "type": "object",
            "properties": {
                "pipeline": {"type": "string", "description": "파이프라인명: test, deploy, release"},
            },
            "required": ["pipeline"],
        },
    ),
    Tool(
        name="gitea_pipeline_status",
        description="CI/CD 파이프라인 실행 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "pipeline": {"type": "string", "description": "파이프라인명 필터 (비어있으면 전체)"},
                "limit": {"type": "integer", "description": "최대 건수 (기본 10)"},
            },
        },
    ),
    # ── Agent Git Ops ──
    Tool(
        name="gitea_hotfix",
        description="에이전트가 자동으로 핫픽스 브랜치 생성 -> 파일 수정 -> PR 생성.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "filepath": {"type": "string", "description": "수정할 파일 경로"},
                "content": {"type": "string", "description": "새 파일 내용"},
                "message": {"type": "string", "description": "커밋 메시지"},
            },
            "required": ["owner", "repo", "filepath", "content", "message"],
        },
    ),
    Tool(
        name="gitea_wiki_sync",
        description="WeruBWorker Wiki <-> Gitea 리포 docs/ 양방향 동기화.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
                "direction": {"type": "string", "description": "to_gitea 또는 from_gitea (기본 to_gitea)"},
            },
            "required": ["owner", "repo"],
        },
    ),
    Tool(
        name="gitea_cleanup",
        description="에이전트 자동 정리: 머지된 브랜치 삭제, 오래된 PR 닫기.",
        inputSchema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"}, "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call and return the JSON result."""
    try:
        # ── Security ──
        if name == "security_score":
            from ..tools.security_scan import security_score

            result = security_score(
                server_id=arguments.get("server_id", ""),
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        elif name == "container_scan":
            from ..tools.security_scan import container_scan

            result = container_scan(
                image=arguments["image"],
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        elif name == "dependency_audit":
            from ..tools.security_scan import dependency_audit

            result = dependency_audit(
                project_path=arguments.get("path", "."),
                audit_type=arguments.get("type", "auto"),
            )
            return json.dumps(result)

        elif name == "firewall_check":
            from ..tools.security_scan import firewall_check

            result = firewall_check(
                server_id=arguments.get("server_id", ""),
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        # ── Backup ──
        elif name == "backup_create":
            bm = _get_backup()
            targets = arguments.get("targets") or None
            result = bm.create_backup(targets)
            return json.dumps(result)

        elif name == "backup_list":
            bm = _get_backup()
            limit = int(arguments.get("limit", 20))
            backups = bm.list_backups(limit)
            return json.dumps({"ok": True, "count": len(backups), "backups": backups})

        elif name == "backup_restore":
            bm = _get_backup()
            result = bm.restore(arguments["backup_id"])
            return json.dumps(result)

        # ── Anomaly Detection ──
        elif name == "anomaly_detect":
            detector = _get_anomaly()
            sid = arguments.get("server_id", "")
            window = int(arguments.get("window", 60))
            if sid:
                anomalies = detector.detect(sid, window)
                data = [{"metric": a.metric, "value": a.value, "expected": a.expected,
                         "z_score": a.z_score, "severity": a.severity, "description": a.description}
                        for a in anomalies]
                return json.dumps({"ok": True, "server_id": sid, "count": len(data), "anomalies": data})
            else:
                all_results = detector.detect_all_servers()
                flat = []
                for s, anomalies in all_results.items():
                    for a in anomalies:
                        flat.append({"server_id": s, "metric": a.metric, "value": a.value,
                                     "expected": a.expected, "z_score": a.z_score, "severity": a.severity})
                return json.dumps({"ok": True, "count": len(flat), "anomalies": flat})

        # ── Postmortem ──
        elif name == "postmortem_generate":
            gen = _get_postmortem()
            report = await gen.generate(arguments["incident_id"])
            return json.dumps({
                "ok": True,
                "incident_id": report.incident_id,
                "title": report.title,
                "summary": report.summary,
                "markdown": report.full_markdown,
                "action_items": report.action_items,
            })

        # ── Workflow ──
        elif name == "workflow_list":
            wf = _get_workflow()
            workflows = wf.list_workflows()
            return json.dumps({"ok": True, "count": len(workflows), "workflows": workflows})

        elif name == "workflow_execute":
            wf = _get_workflow()
            result = await wf.execute(arguments["workflow_id"], context={"secrets": _get_secrets()})
            return json.dumps(result)

        # ── Batch SSH ──
        elif name == "batch_execute":
            batch = _get_batch()
            mode = arguments.get("mode", "parallel")
            tag = arguments.get("tag", "")
            cmd = arguments["command"]
            if mode == "rolling":
                result = await batch.execute_rolling(cmd, tag=tag)
            else:
                result = await batch.execute_parallel(cmd, tag=tag)
            return json.dumps({
                "ok": True, "total": result.total,
                "succeeded": result.succeeded, "failed": result.failed,
                "duration_ms": result.duration_ms,
                "results": result.results,
            })

        elif name == "batch_servers":
            batch = _get_batch()
            tag = arguments.get("tag", "")
            servers = batch.list_servers(tag=tag)
            tags = batch.list_tags()
            return json.dumps({"ok": True, "count": len(servers),
                               "servers": [{"server_id": s["server_id"], "host": s.get("host", ""),
                                            "label": s.get("label", ""), "tags": s.get("tags", [])}
                                           for s in servers],
                               "available_tags": tags})

        # ── Gitea ──
        elif name == "gitea_repos":
            gc = _get_gitea()
            repos = await gc.repos.list()
            if isinstance(repos, list):
                return json.dumps({"ok": True, "count": len(repos),
                    "repos": [{"full_name": r.get("full_name",""), "description": r.get("description",""),
                               "html_url": r.get("html_url",""), "language": r.get("language",""),
                               "stars": r.get("stars_count",0), "updated": r.get("updated_at","")} for r in repos[:30]]})
            return json.dumps({"ok": False, "error": str(repos)})

        elif name == "gitea_repo_detail":
            gc = _get_gitea()
            detail = await gc.repos.get(arguments["owner"], arguments["repo"])
            langs = await gc.repos.languages(arguments["owner"], arguments["repo"])
            return json.dumps({"ok": True, "repo": detail, "languages": langs})

        elif name == "gitea_branches":
            gc = _get_gitea()
            action = arguments.get("action", "list")
            o, r = arguments["owner"], arguments["repo"]
            if action == "create":
                result = await gc.branches.create(o, r, arguments.get("name",""), arguments.get("from","main"))
                return json.dumps(result)
            elif action == "delete":
                result = await gc.branches.delete(o, r, arguments.get("name",""))
                return json.dumps(result)
            branches = await gc.branches.list(o, r)
            return json.dumps({"ok": True, "branches": [{"name": b.get("name","")} for b in (branches if isinstance(branches, list) else [])]})

        elif name == "gitea_pulls":
            gc = _get_gitea()
            pulls = await gc.pulls.list(arguments["owner"], arguments["repo"], state=arguments.get("state","open"))
            return json.dumps({"ok": True, "pulls": [{"number": p.get("number"), "title": p.get("title",""), "state": p.get("state",""), "user": p.get("user",{}).get("login","")} for p in (pulls if isinstance(pulls, list) else [])]})

        elif name == "gitea_create_pr":
            gc = _get_gitea()
            result = await gc.pulls.create(arguments["owner"], arguments["repo"], title=arguments["title"], head=arguments["head"], base=arguments.get("base","main"), body=arguments.get("body",""))
            return json.dumps(result)

        elif name == "gitea_issues":
            gc = _get_gitea()
            action = arguments.get("action", "list")
            o, r = arguments["owner"], arguments["repo"]
            if action == "create":
                result = await gc.issues.create(o, r, title=arguments.get("title",""), body=arguments.get("body",""))
                return json.dumps(result)
            issues = await gc.issues.list(o, r, state=arguments.get("state","open"))
            return json.dumps({"ok": True, "issues": [{"number": i.get("number"), "title": i.get("title",""), "state": i.get("state","")} for i in (issues if isinstance(issues, list) else [])]})

        elif name == "gitea_releases":
            gc = _get_gitea()
            action = arguments.get("action", "list")
            o, r = arguments["owner"], arguments["repo"]
            if action == "create":
                result = await gc.releases.create(o, r, tag_name=arguments.get("tag_name",""), name=arguments.get("name",""), body=arguments.get("body",""))
                return json.dumps(result)
            releases = await gc.releases.list(o, r)
            return json.dumps({"ok": True, "releases": [{"tag_name": x.get("tag_name",""), "name": x.get("name","")} for x in (releases if isinstance(releases, list) else [])]})

        elif name == "gitea_file_read":
            gc = _get_gitea()
            import base64 as _b64
            data = await gc.contents.get(arguments["owner"], arguments["repo"], arguments["filepath"], ref=arguments.get("ref",""))
            if isinstance(data, dict) and data.get("content"):
                try:
                    decoded = _b64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return json.dumps({"ok": True, "path": data.get("path",""), "size": data.get("size",0), "sha": data.get("sha",""), "content": decoded[:5000]})
                except Exception:
                    pass
            return json.dumps({"ok": True, "data": data})

        elif name == "gitea_file_write":
            gc = _get_gitea()
            sha = arguments.get("sha", "")
            if sha:
                result = await gc.contents.update(arguments["owner"], arguments["repo"], arguments["filepath"], arguments["content"], sha=sha, message=arguments.get("message",""))
            else:
                result = await gc.contents.create(arguments["owner"], arguments["repo"], arguments["filepath"], arguments["content"], message=arguments.get("message",""))
            return json.dumps(result)

        elif name == "gitea_commits":
            gc = _get_gitea()
            commits = await gc.commits.list(arguments["owner"], arguments["repo"], limit=int(arguments.get("limit", 20)))
            return json.dumps({"ok": True, "commits": [{"sha": c.get("sha","")[:8], "message": c.get("commit",{}).get("message","").split("\n")[0], "author": c.get("commit",{}).get("author",{}).get("name","")} for c in (commits if isinstance(commits, list) else [])]})

        elif name == "gitea_file_tree":
            gc = _get_gitea()
            tree = await gc.contents.tree(arguments["owner"], arguments["repo"], ref=arguments.get("ref","main"))
            return json.dumps({"ok": True, "count": len(tree), "tree": [{"path": t.get("path",""), "type": t.get("type",""), "size": t.get("size",0)} for t in tree[:300]]})

        elif name == "gitea_pr_review":
            gc = _get_gitea()
            from ..connectors.gitea.reviewer import CodeReviewer
            reviewer = CodeReviewer(gc)
            result = await reviewer.review_and_post(arguments["owner"], arguments["repo"], arguments["pr_number"])
            return json.dumps(result)

        elif name == "gitea_merge_check":
            gc = _get_gitea()
            from ..connectors.gitea.reviewer import CodeReviewer
            reviewer = CodeReviewer(gc)
            result = await reviewer.auto_merge_check(arguments["owner"], arguments["repo"], arguments["pr_number"])
            return json.dumps(result)

        elif name == "gitea_pipeline_run":
            from ..connectors.gitea.pipeline import PipelineManager
            pm = PipelineManager(_data_dir(), gitea_client=_get_gitea())
            result = await pm.run(arguments["pipeline"])
            return json.dumps(result)

        elif name == "gitea_pipeline_status":
            from ..connectors.gitea.pipeline import PipelineManager
            pm = PipelineManager(_data_dir())
            runs = pm.list_runs(arguments.get("pipeline", ""), int(arguments.get("limit", 10)))
            return json.dumps({"ok": True, "runs": runs})

        elif name == "gitea_webhook_events":
            from ..connectors.gitea_webhook import GiteaWebhookHandler

            handler = GiteaWebhookHandler(_data_dir())
            events = handler.recent_events(
                limit=int(arguments.get("limit", 30)),
                repo=arguments.get("repo", ""),
            )
            return json.dumps({"ok": True, "count": len(events), "events": events})

        elif name == "gitea_hotfix":
            from ..connectors.gitea.agent_ops import AgentGitOps
            ops = AgentGitOps(_get_gitea())
            result = await ops.create_hotfix(arguments["owner"], arguments["repo"],
                arguments["filepath"], arguments["content"], arguments["message"])
            return json.dumps(result)

        elif name == "gitea_wiki_sync":
            from ..connectors.gitea.sync import GiteaWikiSync
            sync = GiteaWikiSync(_get_gitea())
            direction = arguments.get("direction", "to_gitea")
            if direction == "from_gitea":
                result = await sync.sync_gitea_to_wiki(arguments["owner"], arguments["repo"])
            else:
                result = await sync.sync_wiki_to_gitea(arguments["owner"], arguments["repo"])
            return json.dumps(result)

        elif name == "gitea_cleanup":
            from ..connectors.gitea.agent_ops import AgentGitOps
            ops = AgentGitOps(_get_gitea())
            result = await ops.scheduled_cleanup(arguments["owner"], arguments["repo"])
            return json.dumps(result)

        else:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})

    except Exception as exc:
        log.exception("ITMS tool error: %s", name)
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def create_server() -> Server:
    """Create and configure the MCP ITMS server."""
    server = Server("werubworker-itms")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await _handle_tool(name, arguments)
        return [TextContent(type="text", text=result)]

    return server


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main():
    """Run the MCP ITMS server via stdio transport."""
    from mcp.server.stdio import stdio_server

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
