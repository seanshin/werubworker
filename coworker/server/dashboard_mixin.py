"""Dashboard API mixin — REST endpoints for infrastructure overview and monitoring.

Adds dashboard-specific routes to the FastAPI app: infrastructure overview,
server metrics time-series, alert feed, health check status, and Wiki API.
This mixin is mixed into SessionManager and its routes are registered in create_app().
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class DashboardMixin:
    """Adds monitoring dashboard data methods to SessionManager.

    Assumes self has:
    - self.data_dir: Path
    - self.secrets: SecretStore
    """

    def _get_ts_store(self):
        """Lazy-init TimeSeriesStore."""
        if not hasattr(self, "_ts_store_cache"):
            from ..monitoring.timeseries import TimeSeriesStore

            self._ts_store_cache = TimeSeriesStore(self.data_dir)
        return self._ts_store_cache

    def _get_collector(self):
        """Lazy-init MetricCollector with broadcast callback."""
        if not hasattr(self, "_collector_cache"):
            from ..monitoring.collector import MetricCollector
            self._collector_cache = MetricCollector(
                self._get_ts_store(),
                secrets=getattr(self, "secrets", None),
                on_collect=self.broadcast_metrics,
            )
        return self._collector_cache

    def _get_hc_manager(self):
        from ..monitoring.healthcheck import HealthCheckManager

        if not hasattr(self, "_hc_manager_cache"):
            self._hc_manager_cache = HealthCheckManager(self.data_dir)
        return self._hc_manager_cache

    def _get_alert_engine(self):
        from ..monitoring.alerting import AlertEngine

        if not hasattr(self, "_alert_engine_cache"):
            self._alert_engine_cache = AlertEngine(self.data_dir)
        return self._alert_engine_cache

    def _get_remediation_engine(self):
        if not hasattr(self, "_remediation_cache"):
            from ..monitoring.remediation import RemediationEngine
            self._remediation_cache = RemediationEngine(self.data_dir)
        return self._remediation_cache

    def _ensure_remediation_linked(self):
        """AlertEngine과 RemediationEngine을 연결."""
        if not hasattr(self, "_remediation_linked"):
            ae = self._get_alert_engine()
            re = self._get_remediation_engine()
            hc = self._get_hc_manager()
            ae.set_remediation_engine(re, hc)
            self._remediation_linked = True

    def _get_incident_manager(self):
        from ..monitoring.incidents import IncidentManager

        if not hasattr(self, "_incident_mgr_cache"):
            self._incident_mgr_cache = IncidentManager(self.data_dir)
        return self._incident_mgr_cache

    def _get_audit_store(self):
        from ..monitoring.audit_ops import OpsAuditStore

        if not hasattr(self, "_audit_store_cache"):
            self._audit_store_cache = OpsAuditStore(self.data_dir)
        return self._audit_store_cache

    def dashboard_overview(self) -> dict:
        """인프라 대시보드 전체 현황."""
        self._ensure_remediation_linked()
        ts = self._get_ts_store()
        hc = self._get_hc_manager()
        alert = self._get_alert_engine()
        inc = self._get_incident_manager()

        return {
            "ok": True,
            "servers": ts.query_latest(),
            "server_count": len(ts.server_list()),
            "active_alerts": alert.active_alerts(),
            "alert_count": len(alert.active_alerts()),
            "health_checks": hc.list_checks(),
            "active_incidents": inc.active_incidents(),
            "incident_count": len(inc.active_incidents()),
            "timestamp": time.time(),
        }

    def dashboard_server_metrics(self, server_id: str, range: str = "1h") -> dict:
        """특정 서버의 시계열 메트릭."""
        ts = self._get_ts_store()
        range_map = {
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
            "7d": 604800,
            "30d": 2592000,
        }
        range_secs = range_map.get(range, 3600)
        now = int(time.time())
        table = ts.auto_select_table(range_secs)
        data = ts.query(server_id, now - range_secs, now, table=table)
        return {"ok": True, "server_id": server_id, "table": table, "data": data}

    def dashboard_alert_feed(self, limit: int = 50) -> dict:
        """알림 피드 (활성 + 최근 해제)."""
        alert = self._get_alert_engine()
        active = alert.active_alerts()
        history = alert.alert_history(limit=limit)
        return {"ok": True, "active": active, "history": history}

    def dashboard_incidents(self, status: str = "", limit: int = 50, offset: int = 0) -> dict:
        """인시던트 목록 (페이지네이션).

        `total`을 함께 돌려주므로 호출자는 더 가져올 게 남았는지 알 수 있다 — 이전에는
        50건에서 조용히 잘려서 그 뒤가 있는지조차 알 수 없었다.
        """
        inc = self._get_incident_manager()
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        incidents = inc.list_incidents(status=status, limit=limit, offset=offset)
        total = inc.count_incidents(status=status)
        return {
            "ok": True,
            "incidents": incidents,
            "total": total,
            "offset": offset,
            "has_more": offset + len(incidents) < total,
        }

    def dashboard_audit_recent(self, limit: int = 50) -> dict:
        """최근 운영 감사 로그."""
        audit = self._get_audit_store()
        return {"ok": True, "entries": audit.recent(limit=limit)}

    # -- Escalation policy --

    def list_escalation_policies(self):
        return self._get_alert_engine().list_escalation_policies()

    def add_escalation_policy(self, name, levels, repeat_last=True):
        from ..monitoring.alerting import EscalationLevel
        lvls = [EscalationLevel(**l) for l in levels]
        return self._get_alert_engine().add_escalation_policy(name, lvls, repeat_last)

    def remove_escalation_policy(self, policy_id):
        self._get_alert_engine().remove_escalation_policy(policy_id)

    # -- Log viewer --

    def _get_log_aggregator(self):
        """Lazy-init LogAggregator."""
        if not hasattr(self, "_log_aggregator_cache"):
            from ..monitoring.log_aggregator import LogAggregator
            self._log_aggregator_cache = LogAggregator(self.data_dir)
        return self._log_aggregator_cache

    def query_logs(self, server_id=None, severity=None, pattern=None, limit=200, offset=0):
        """로그 엔트리 검색."""
        agg = self._get_log_aggregator()
        entries = agg.query(server_id=server_id, severity=severity, pattern=pattern, limit=limit, offset=offset)
        return [
            {
                "ts": e.timestamp,
                "server_id": e.server_id,
                "line": e.line,
                "severity": e.severity,
                "source_id": e.source_id,
                "matched_pattern": e.matched_pattern,
            }
            for e in entries
        ]

    def log_sources(self):
        """등록된 로그 소스 목록."""
        agg = self._get_log_aggregator()
        return agg.list_sources()

    def log_servers(self):
        """로그가 기록된 서버 목록."""
        agg = self._get_log_aggregator()
        return agg.list_servers() if hasattr(agg, 'list_servers') else []

    # -- Network topology --

    def network_topology(self):
        """서버와 서비스 간 연결 토폴로지를 생성."""
        nodes = []
        edges = []

        # SSH 서버 노드 수집
        secrets = getattr(self, "secrets", None)
        if secrets:
            for entry in secrets.status():
                key = entry.get("profile", "")
                if key.startswith("ssh:server:"):
                    server_id = key[len("ssh:server:"):]
                    profile = secrets.get(key) or {}
                    nodes.append({
                        "id": server_id,
                        "label": profile.get("label", server_id),
                        "type": "server",
                        "host": profile.get("host", ""),
                        "status": "unknown",
                    })

        # 로컬 서버 노드
        nodes.append({
            "id": "__local__",
            "label": "iMac (로컬)",
            "type": "local",
            "host": "127.0.0.1",
            "status": "healthy",
        })

        # 헬스체크 기반 서비스 노드와 엣지
        hc = self._get_hc_manager()
        for rule in hc.list_rules():
            target = rule.get("target", "")
            svc_id = f"svc-{rule.get('name', target)}"
            nodes.append({
                "id": svc_id,
                "label": rule.get("name", target),
                "type": "service",
                "target": target,
                "status": rule.get("last_status", "unknown"),
            })
            # 서비스 → 관련 서버 엣지
            server_id = rule.get("server_id", "__local__")
            edges.append({
                "source": server_id,
                "target": svc_id,
                "type": rule.get("type", "http"),
            })

        return {"nodes": nodes, "edges": edges}

    # -- Anomaly detection --

    def _get_anomaly_detector(self):
        if not hasattr(self, "_anomaly_cache"):
            from ..monitoring.anomaly import AnomalyDetector
            self._anomaly_cache = AnomalyDetector(self._get_ts_store())
        return self._anomaly_cache

    def detect_anomalies(self, server_id=None, window=60):
        detector = self._get_anomaly_detector()
        if server_id:
            return detector.detect(server_id, window)
        return detector.detect_all_servers()

    async def analyze_anomalies(self, server_id=None, window=60):
        detector = self._get_anomaly_detector()
        anomalies = detector.detect(server_id, window) if server_id else []
        if not server_id:
            all_results = detector.detect_all_servers()
            anomalies = [a for lst in all_results.values() for a in lst]
        provider = getattr(self, "provider", None)
        return await detector.analyze_with_llm(anomalies, provider)

    # -- Postmortem --

    def _get_postmortem_generator(self):
        if not hasattr(self, "_postmortem_cache"):
            from ..monitoring.postmortem import PostmortemGenerator
            self._postmortem_cache = PostmortemGenerator(
                self._get_incident_manager(),
                self._get_ts_store(),
                self._get_alert_engine(),
                wiki_store=getattr(self, "wiki_store", None),
            )
        return self._postmortem_cache

    async def generate_postmortem(self, incident_id, use_llm=False):
        gen = self._get_postmortem_generator()
        provider = getattr(self, "provider", None) if use_llm else None
        report = await gen.generate(incident_id, provider)
        return {
            "ok": True,
            "incident_id": report.incident_id,
            "title": report.title,
            "summary": report.summary,
            "markdown": report.full_markdown,
            "action_items": report.action_items,
        }

    async def save_postmortem_to_wiki(self, incident_id, use_llm=False):
        gen = self._get_postmortem_generator()
        provider = getattr(self, "provider", None) if use_llm else None
        report = await gen.generate(incident_id, provider)
        return await gen.save_to_wiki(report)

    # -- Workflow engine --

    def _get_workflow_engine(self):
        if not hasattr(self, "_workflow_cache"):
            from ..automation.workflow import WorkflowEngine
            self._workflow_cache = WorkflowEngine(self.data_dir)
        return self._workflow_cache

    # -- Batch SSH --

    def _get_batch_ssh(self):
        if not hasattr(self, "_batch_ssh_cache"):
            from ..connectors.ssh.batch import BatchSSH
            self._batch_ssh_cache = BatchSSH(secrets=getattr(self, "secrets", None))
        return self._batch_ssh_cache

    def _get_backup_manager(self):
        """Lazy-init BackupManager."""
        if not hasattr(self, "_backup_cache"):
            from ..monitoring.backup import BackupManager
            self._backup_cache = BackupManager(self.data_dir)
        return self._backup_cache

    def _get_slack_bot(self):
        """Lazy-init SlackBot."""
        if not hasattr(self, "_slack_bot_cache"):
            from ..connectors.slack_bot import SlackBot
            self._slack_bot_cache = SlackBot(secrets=getattr(self, "secrets", None), dashboard=self)
        return self._slack_bot_cache

    def _get_pipeline_manager(self):
        """Lazy-init PipelineManager."""
        if not hasattr(self, "_pipeline_cache"):
            from ..connectors.gitea.pipeline import PipelineManager
            self._pipeline_cache = PipelineManager(
                self.data_dir,
                repo_path=str(Path(self.data_dir).parent) if hasattr(self, 'data_dir') else "",
                gitea_client=self._get_gitea_client(),
            )
        return self._pipeline_cache

    def _get_agent_git_ops(self):
        if not hasattr(self, "_agent_ops_cache"):
            from ..connectors.gitea.agent_ops import AgentGitOps
            self._agent_ops_cache = AgentGitOps(self._get_gitea_client(), provider=getattr(self, "provider", None))
        return self._agent_ops_cache

    def _get_gitea_wiki_sync(self):
        if not hasattr(self, "_gitea_wiki_sync_cache"):
            from ..connectors.gitea.sync import GiteaWikiSync
            self._gitea_wiki_sync_cache = GiteaWikiSync(self._get_gitea_client(), wiki_store=getattr(self, "wiki_store", None))
        return self._gitea_wiki_sync_cache

    def _get_gitea_client(self):
        """Lazy-init GiteaClient for REST API access."""
        if not hasattr(self, "_gitea_client_cache"):
            from ..connectors.gitea.client import GiteaClient
            secrets = getattr(self, "secrets", None)
            token = ""
            if secrets:
                gitea_conf = secrets.get("gitea") or {}
                token = gitea_conf.get("token", "")
            self._gitea_client_cache = GiteaClient(base_url="http://localhost:3000", token=token)
        return self._gitea_client_cache

    def _get_teams_manager(self):
        if not hasattr(self, "_teams_cache"):
            from ..connectors.gitea.teams import TeamsManager
            self._teams_cache = TeamsManager(self._get_gitea_client())
        return self._teams_cache

    def _get_security_scanner(self):
        if not hasattr(self, "_sec_scanner_cache"):
            from ..connectors.gitea.teams import SecurityScanner
            self._sec_scanner_cache = SecurityScanner(self._get_gitea_client())
        return self._sec_scanner_cache

    def _get_gitea_webhook(self):
        """Lazy-init GiteaWebhookHandler."""
        if not hasattr(self, "_gitea_webhook_cache"):
            from ..connectors.gitea_webhook import GiteaWebhookHandler
            self._gitea_webhook_cache = GiteaWebhookHandler(self.data_dir, secrets=getattr(self, "secrets", None), dashboard=self)
        return self._gitea_webhook_cache

    def _get_onboarding(self):
        """Lazy-init ServerOnboarding."""
        if not hasattr(self, "_onboarding_cache"):
            from ..connectors.ssh.onboarding import ServerOnboarding
            self._onboarding_cache = ServerOnboarding(
                secrets=getattr(self, "secrets", None),
                wiki_store=getattr(self, "wiki_store", None),
                hc_manager=self._get_hc_manager(),
            )
        return self._onboarding_cache


def register_dashboard_routes(app, manager) -> None:
    """FastAPI 앱에 대시보드 라우트를 등록."""
    from fastapi import Request

    @app.get("/v1/dashboard/overview")
    async def api_dashboard_overview():
        return manager.dashboard_overview()

    @app.get("/v1/dashboard/servers/{server_id}/metrics")
    async def api_server_metrics(server_id: str, range: str = "1h"):
        return manager.dashboard_server_metrics(server_id, range)

    @app.get("/v1/dashboard/alerts")
    async def api_alert_feed(limit: int = 50):
        return manager.dashboard_alert_feed(limit)

    @app.get("/v1/dashboard/incidents")
    async def api_incidents(status: str = "", limit: int = 50, offset: int = 0):
        return manager.dashboard_incidents(status, limit=limit, offset=offset)

    @app.get("/v1/dashboard/audit")
    async def api_audit_recent(limit: int = 50):
        return manager.dashboard_audit_recent(limit)

    # Wiki API는 app.py에 이미 구현되어 있으므로 여기서 중복 등록하지 않음.
    # (GET /v1/wiki, /v1/wiki/{page_id}, /v1/wiki/categories 등 — app.py 라인 2759~2899)

    # -- Infrastructure API --

    @app.get("/v1/infrastructure/servers")
    async def api_infra_servers():
        ts = manager._get_ts_store()
        servers = ts.query_latest()
        return {"ok": True, "count": len(servers), "servers": servers}

    @app.get("/v1/infrastructure/topology")
    async def api_infra_topology():
        """서비스 의존관계 맵."""
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        from ..wiki.resolver import ServiceResolver

        resolver = ServiceResolver(
            manager.wiki_store,
            getattr(manager, "secrets", None),
        )
        services = resolver.list_services_with_wiki()
        return {"ok": True, "count": len(services), "services": services}

    # -- Webhook management --

    @app.get("/v1/dashboard/webhooks")
    async def api_webhooks_list():
        alert = manager._get_alert_engine()
        return {"ok": True, "webhooks": alert.list_webhooks()}

    @app.post("/v1/dashboard/webhooks")
    async def api_webhooks_add(body: dict):
        alert = manager._get_alert_engine()
        url = (body or {}).get("url", "")
        if not url:
            return {"ok": False, "error": "url required"}
        return alert.add_webhook(
            url=url,
            webhook_type=(body or {}).get("type", "slack"),
            name=(body or {}).get("name", ""),
        )

    @app.delete("/v1/dashboard/webhooks/{webhook_id}")
    async def api_webhooks_remove(webhook_id: int):
        alert = manager._get_alert_engine()
        return alert.remove_webhook(webhook_id)

    # -- Escalation policy management --

    @app.get("/v1/dashboard/escalation-policies")
    def list_escalation_policies():
        return {"ok": True, "policies": manager.list_escalation_policies()}

    @app.post("/v1/dashboard/escalation-policies")
    async def create_escalation_policy(request: Request):
        body = await request.json()
        policy_id = manager.add_escalation_policy(
            name=body.get("name", ""),
            levels=body.get("levels", []),
            repeat_last=body.get("repeat_last", True),
        )
        return {"ok": True, "id": policy_id}

    @app.delete("/v1/dashboard/escalation-policies/{policy_id}")
    def delete_escalation_policy(policy_id: str):
        manager.remove_escalation_policy(policy_id)
        return {"ok": True}

    # -- Log viewer --

    @app.get("/v1/dashboard/logs")
    def get_logs(server_id: str = "", severity: str = "", pattern: str = "", limit: int = 200, offset: int = 0):
        entries = manager.query_logs(
            server_id=server_id or None,
            severity=severity or None,
            pattern=pattern or None,
            limit=min(limit, 1000),
            offset=offset,
        )
        return {"ok": True, "entries": entries, "count": len(entries)}

    @app.get("/v1/dashboard/logs/sources")
    def get_log_sources():
        return {"ok": True, "sources": manager.log_sources()}

    @app.get("/v1/dashboard/logs/servers")
    def get_log_servers():
        return {"ok": True, "servers": manager.log_servers()}

    # -- Network topology --

    @app.get("/v1/dashboard/topology")
    def get_topology():
        data = manager.network_topology()
        return {"ok": True, **data}

    # -- Anomaly detection --

    @app.get("/v1/dashboard/anomalies")
    def get_anomalies(server_id: str = "", window: int = 60):
        result = manager.detect_anomalies(server_id or None, window)
        if isinstance(result, dict):
            flat = [{"server_id": k, "anomalies": [{"metric": a.metric, "value": a.value, "expected": a.expected, "z_score": a.z_score, "severity": a.severity, "description": a.description, "timestamp": a.timestamp} for a in v]} for k, v in result.items()]
            return {"ok": True, "servers": flat}
        return {"ok": True, "anomalies": [{"metric": a.metric, "value": a.value, "expected": a.expected, "z_score": a.z_score, "severity": a.severity, "description": a.description, "timestamp": a.timestamp} for a in result]}

    @app.post("/v1/dashboard/anomalies/analyze")
    async def analyze_anomalies(request: Request):
        body = await request.json()
        analysis = await manager.analyze_anomalies(body.get("server_id"), body.get("window", 60))
        return {"ok": True, "analysis": analysis}

    # -- Postmortem --

    @app.post("/v1/dashboard/incidents/{incident_id}/postmortem")
    async def generate_postmortem(incident_id: str, request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        use_llm = body.get("use_llm", False)
        result = await manager.generate_postmortem(incident_id, use_llm)
        return result

    @app.post("/v1/dashboard/incidents/{incident_id}/postmortem/save")
    async def save_postmortem(incident_id: str, request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        use_llm = body.get("use_llm", False)
        result = await manager.save_postmortem_to_wiki(incident_id, use_llm)
        return result

    # -- Remediation management --

    @app.get("/v1/dashboard/remediation/actions")
    def list_remediation_actions():
        engine = manager._get_remediation_engine()
        return {"ok": True, "actions": engine.list_actions(enabled_only=False)}

    @app.post("/v1/dashboard/remediation/actions")
    async def create_remediation_action(request: Request):
        from ..monitoring.remediation import RemediationAction, RemediationStep
        body = await request.json()
        steps = [RemediationStep(**s) for s in body.get("steps", [])]
        action = RemediationAction(
            id=body.get("id", ""),
            name=body.get("name", ""),
            trigger=body.get("trigger", ""),
            steps=steps,
            requires_approval=body.get("requires_approval", True),
            cooldown_seconds=body.get("cooldown_seconds", 600),
        )
        engine = manager._get_remediation_engine()
        result = engine.register(action)
        return result

    @app.post("/v1/dashboard/remediation/execute/{action_id}")
    async def execute_remediation(action_id: str, request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        manager._ensure_remediation_linked()
        engine = manager._get_remediation_engine()
        result = await engine.execute_and_verify(
            action_id=action_id,
            alert_id=body.get("alert_id", ""),
            server_id=body.get("server_id", ""),
            alert_engine=manager._get_alert_engine(),
            hc_manager=manager._get_hc_manager(),
        )
        return result

    @app.get("/v1/dashboard/remediation/executions")
    def list_remediation_executions(limit: int = 50):
        engine = manager._get_remediation_engine()
        return {"ok": True, "executions": engine.list_executions(limit=limit)}

    # -- Workflow management --

    @app.get("/v1/dashboard/workflows")
    def list_workflows():
        engine = manager._get_workflow_engine()
        return {"ok": True, "workflows": engine.list_workflows()}

    @app.post("/v1/dashboard/workflows")
    async def create_workflow(request: Request):
        body = await request.json()
        engine = manager._get_workflow_engine()
        result = engine.create(
            name=body.get("name", ""),
            description=body.get("description", ""),
            steps=body.get("steps", []),
            entry_step=body.get("entry_step", ""),
        )
        return result

    @app.get("/v1/dashboard/workflows/{workflow_id}")
    def get_workflow(workflow_id: str):
        engine = manager._get_workflow_engine()
        wf = engine.get(workflow_id)
        if not wf:
            return {"ok": False, "error": "not found"}
        return {"ok": True, **wf}

    @app.delete("/v1/dashboard/workflows/{workflow_id}")
    def delete_workflow(workflow_id: str):
        engine = manager._get_workflow_engine()
        return engine.delete(workflow_id)

    @app.post("/v1/dashboard/workflows/{workflow_id}/execute")
    async def execute_workflow(workflow_id: str):
        engine = manager._get_workflow_engine()
        secrets = getattr(manager, "secrets", None)
        result = await engine.execute(workflow_id, context={"secrets": secrets})
        return result

    @app.get("/v1/dashboard/workflows/{workflow_id}/executions")
    def list_workflow_executions(workflow_id: str, limit: int = 20):
        engine = manager._get_workflow_engine()
        return {"ok": True, "executions": engine.list_executions(workflow_id, limit)}

    # -- Batch SSH (multi-server) --

    @app.get("/v1/dashboard/servers/tags")
    def list_server_tags():
        batch = manager._get_batch_ssh()
        return {"ok": True, "tags": batch.list_tags()}

    @app.post("/v1/dashboard/batch/execute")
    async def batch_execute(request: Request):
        body = await request.json()
        batch = manager._get_batch_ssh()
        mode = body.get("mode", "parallel")  # parallel or rolling

        if mode == "rolling":
            result = await batch.execute_rolling(
                command=body.get("command", ""),
                server_ids=body.get("server_ids"),
                tag=body.get("tag", ""),
                timeout=body.get("timeout", 30),
                sudo=body.get("sudo", False),
                delay_seconds=body.get("delay_seconds", 5),
                stop_on_failure=body.get("stop_on_failure", True),
            )
        else:
            result = await batch.execute_parallel(
                command=body.get("command", ""),
                server_ids=body.get("server_ids"),
                tag=body.get("tag", ""),
                timeout=body.get("timeout", 30),
                max_concurrent=body.get("max_concurrent", 10),
                sudo=body.get("sudo", False),
            )

        return {
            "ok": True,
            "total": result.total,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "results": result.results,
            "duration_ms": result.duration_ms,
        }

    # -- Security scan (advanced) --

    @app.get("/v1/dashboard/security/score")
    def get_security_score(server_id: str = ""):
        from ..tools.security_scan import security_scan_tools
        tools = security_scan_tools(manager)
        # security_score is the last tool registered
        score_fn = [t for t in tools if getattr(t, "__name__", "") == "security_score"]
        if score_fn:
            return score_fn[0](server=server_id or "")
        return {"ok": False, "error": "security_score tool not found"}

    @app.post("/v1/dashboard/security/container-scan")
    async def scan_container(request: Request):
        body = await request.json()
        from ..tools.security_scan import security_scan_tools
        tools = security_scan_tools(manager)
        scan_fn = [t for t in tools if getattr(t, "__name__", "") == "container_scan"]
        if scan_fn:
            return scan_fn[0](image=body.get("image", ""), server=body.get("server_id", ""))
        return {"ok": False, "error": "container_scan tool not found"}

    @app.post("/v1/dashboard/security/dependency-audit")
    async def audit_dependencies(request: Request):
        body = await request.json()
        from ..tools.security_scan import security_scan_tools
        tools = security_scan_tools(manager)
        audit_fn = [t for t in tools if getattr(t, "__name__", "") == "dependency_audit"]
        if audit_fn:
            return audit_fn[0](project_path=body.get("path", "."), audit_type=body.get("type", "auto"))
        return {"ok": False, "error": "dependency_audit tool not found"}

    @app.get("/v1/dashboard/security/firewall")
    def check_firewall(server_id: str = ""):
        from ..tools.security_scan import security_scan_tools
        tools = security_scan_tools(manager)
        fw_fn = [t for t in tools if getattr(t, "__name__", "") == "firewall_check"]
        if fw_fn:
            return fw_fn[0](server=server_id or "")
        return {"ok": False, "error": "firewall_check tool not found"}

    # -- Backup / Restore --

    @app.get("/v1/dashboard/backups")
    def list_backups(limit: int = 20):
        bm = manager._get_backup_manager()
        return {"ok": True, "backups": bm.list_backups(limit)}

    @app.post("/v1/dashboard/backups")
    async def create_backup(request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        bm = manager._get_backup_manager()
        targets = body.get("targets")
        return bm.create_backup(targets)

    @app.post("/v1/dashboard/backups/{backup_id}/restore")
    async def restore_backup(backup_id: str, request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        bm = manager._get_backup_manager()
        return bm.restore(backup_id, body.get("targets"))

    @app.delete("/v1/dashboard/backups/{backup_id}")
    def delete_backup(backup_id: str):
        bm = manager._get_backup_manager()
        return bm.delete_backup(backup_id)

    @app.get("/v1/dashboard/backups/targets")
    def backup_targets():
        bm = manager._get_backup_manager()
        return {"ok": True, "targets": bm.available_targets()}

    @app.post("/v1/dashboard/backups/prune")
    def prune_backups():
        bm = manager._get_backup_manager()
        return bm.prune()

    # -- Audit stats (Phase 4) --

    @app.get("/v1/dashboard/audit/stats")
    def audit_stats(days: int = 7):
        store = manager._get_audit_store()
        return store.stats_by_period(days)

    @app.get("/v1/dashboard/audit/users")
    def audit_users(days: int = 7):
        store = manager._get_audit_store()
        return store.stats_by_user(days)

    @app.get("/v1/dashboard/audit/flagged")
    def audit_flagged(limit: int = 50):
        store = manager._get_audit_store()
        return {"ok": True, "flagged": store.flagged_actions(limit)}

    @app.get("/v1/dashboard/audit/export")
    def audit_export(days: int = 30):
        from starlette.responses import Response
        store = manager._get_audit_store()
        csv_data = store.export_csv_by_days(days)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_log_{days}d.csv"},
        )

    # -- Slack Bot integration --

    @app.post("/v1/slack/command")
    async def slack_command(request: Request):
        """Slack 슬래시 명령어 수신."""
        form = await request.form()
        bot = manager._get_slack_bot()
        result = await bot.handle_slash_command(
            command=form.get("command", ""),
            text=form.get("text", ""),
            channel_id=form.get("channel_id", ""),
            user_id=form.get("user_id", ""),
            user_name=form.get("user_name", ""),
        )
        return result

    @app.post("/v1/slack/interaction")
    async def slack_interaction(request: Request):
        """Slack 대화형 액션 (버튼 클릭 등) 수신."""
        form = await request.form()
        import json as _json
        payload = _json.loads(form.get("payload", "{}"))
        bot = manager._get_slack_bot()
        result = await bot.handle_interaction(payload)
        return result

    @app.get("/v1/slack/mappings")
    def slack_mappings():
        bot = manager._get_slack_bot()
        return {"ok": True, "mappings": bot.list_mappings()}

    @app.post("/v1/slack/mappings")
    async def slack_map_channel(request: Request):
        body = await request.json()
        bot = manager._get_slack_bot()
        return bot.map_channel(body.get("channel_id", ""), body.get("channel_name", ""), body.get("session_id", ""))

    # -- Gitea Webhook integration --

    @app.post("/v1/webhooks/gitea")
    async def gitea_webhook(request: Request):
        """Gitea Webhook 수신 엔드포인트."""
        handler = manager._get_gitea_webhook()
        body = await request.body()

        # 서명 검증
        signature = request.headers.get("X-Gitea-Signature", "")
        if not handler.verify_signature(body, signature):
            return {"ok": False, "error": "invalid signature"}

        event_type = request.headers.get("X-Gitea-Event", "unknown")
        import json as _json
        payload = _json.loads(body)

        event = handler.parse_event(event_type, payload)
        result = await handler.process_event(event)
        return result

    @app.get("/v1/webhooks/gitea/events")
    def gitea_events(limit: int = 50, repo: str = "", event_type: str = ""):
        handler = manager._get_gitea_webhook()
        return {"ok": True, "events": handler.recent_events(limit, repo, event_type)}

    @app.get("/v1/webhooks/gitea/stats")
    def gitea_stats(days: int = 7):
        handler = manager._get_gitea_webhook()
        return handler.event_stats(days)

    # -- Server Onboarding --

    @app.post("/v1/dashboard/servers/onboard")
    async def onboard_server(request: Request):
        body = await request.json()
        onboarding = manager._get_onboarding()
        result = await onboarding.onboard(
            server_id=body.get("server_id", ""),
            host=body.get("host", ""),
            port=body.get("port", 22),
            username=body.get("username", "deploy"),
            key_path=body.get("key_path", ""),
            label=body.get("label", ""),
            tags=body.get("tags", []),
        )
        return {
            "ok": len(result.steps_failed) == 0,
            "server_id": result.server_id,
            "steps_completed": result.steps_completed,
            "steps_failed": result.steps_failed,
            "system_info": result.system_info,
            "wiki_page_id": result.wiki_page_id,
            "health_checks": result.health_checks_created,
        }

    # ── Gitea 리포 관리 ──

    @app.get("/v1/gitea/repos")
    async def gitea_repos():
        gc = manager._get_gitea_client()
        repos = await gc.repos.list()
        if isinstance(repos, dict) and repos.get("error"):
            return {"ok": False, "error": repos["error"]}
        return {"ok": True, "repos": [{"id": r.get("id"), "full_name": r.get("full_name", ""), "description": r.get("description", ""), "html_url": r.get("html_url", ""), "stars": r.get("stars_count", 0), "forks": r.get("forks_count", 0), "open_issues": r.get("open_issues_count", 0), "language": r.get("language", ""), "updated_at": r.get("updated_at", "")} for r in (repos if isinstance(repos, list) else [])]}

    @app.post("/v1/gitea/repos")
    async def gitea_create_repo(request: Request):
        body = await request.json()
        gc = manager._get_gitea_client()
        return await gc.repos.create(name=body.get("name", ""), description=body.get("description", ""), private=body.get("private", False))

    @app.get("/v1/gitea/repos/{owner}/{repo}")
    async def gitea_repo_detail(owner: str, repo: str):
        gc = manager._get_gitea_client()
        return await gc.repos.get(owner, repo)

    @app.get("/v1/gitea/repos/{owner}/{repo}/languages")
    async def gitea_repo_languages(owner: str, repo: str):
        gc = manager._get_gitea_client()
        return {"ok": True, "languages": await gc.repos.languages(owner, repo)}

    # ── Gitea 브랜치 ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/branches")
    async def gitea_branches(owner: str, repo: str):
        gc = manager._get_gitea_client()
        branches = await gc.branches.list(owner, repo)
        return {"ok": True, "branches": [{"name": b.get("name", ""), "commit_sha": b.get("commit", {}).get("id", ""), "commit_message": b.get("commit", {}).get("message", "")[:100]} for b in (branches if isinstance(branches, list) else [])]}

    @app.post("/v1/gitea/repos/{owner}/{repo}/branches")
    async def gitea_create_branch(owner: str, repo: str, request: Request):
        body = await request.json()
        gc = manager._get_gitea_client()
        return await gc.branches.create(owner, repo, name=body.get("name", ""), old_branch=body.get("from", "main"))

    @app.delete("/v1/gitea/repos/{owner}/{repo}/branches/{branch}")
    async def gitea_delete_branch(owner: str, repo: str, branch: str):
        gc = manager._get_gitea_client()
        return await gc.branches.delete(owner, repo, branch)

    # ── Gitea PR ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/pulls")
    async def gitea_pulls(owner: str, repo: str, state: str = "open"):
        gc = manager._get_gitea_client()
        pulls = await gc.pulls.list(owner, repo, state=state)
        return {"ok": True, "pulls": [{"number": p.get("number"), "title": p.get("title", ""), "state": p.get("state", ""), "user": p.get("user", {}).get("login", ""), "created_at": p.get("created_at", ""), "head": p.get("head", {}).get("label", ""), "base": p.get("base", {}).get("label", "")} for p in (pulls if isinstance(pulls, list) else [])]}

    @app.post("/v1/gitea/repos/{owner}/{repo}/pulls")
    async def gitea_create_pull(owner: str, repo: str, request: Request):
        body = await request.json()
        gc = manager._get_gitea_client()
        return await gc.pulls.create(owner, repo, title=body.get("title", ""), head=body.get("head", ""), base=body.get("base", "main"), body=body.get("body", ""))

    @app.post("/v1/gitea/repos/{owner}/{repo}/pulls/{number}/merge")
    async def gitea_merge_pull(owner: str, repo: str, number: int, request: Request):
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        gc = manager._get_gitea_client()
        return await gc.pulls.merge(owner, repo, number, merge_type=body.get("merge_type", "squash"))

    # ── Gitea 이슈 ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/issues")
    async def gitea_issues(owner: str, repo: str, state: str = "open"):
        gc = manager._get_gitea_client()
        issues = await gc.issues.list(owner, repo, state=state)
        return {"ok": True, "issues": [{"number": i.get("number"), "title": i.get("title", ""), "state": i.get("state", ""), "user": i.get("user", {}).get("login", ""), "labels": [l.get("name", "") for l in i.get("labels", [])], "created_at": i.get("created_at", "")} for i in (issues if isinstance(issues, list) else [])]}

    @app.post("/v1/gitea/repos/{owner}/{repo}/issues")
    async def gitea_create_issue(owner: str, repo: str, request: Request):
        body = await request.json()
        gc = manager._get_gitea_client()
        return await gc.issues.create(owner, repo, title=body.get("title", ""), body=body.get("body", ""))

    # ── Gitea 릴리즈 ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/releases")
    async def gitea_releases(owner: str, repo: str):
        gc = manager._get_gitea_client()
        releases = await gc.releases.list(owner, repo)
        return {"ok": True, "releases": [{"id": r.get("id"), "tag_name": r.get("tag_name", ""), "name": r.get("name", ""), "body": r.get("body", "")[:200], "draft": r.get("draft", False), "prerelease": r.get("prerelease", False), "created_at": r.get("created_at", "")} for r in (releases if isinstance(releases, list) else [])]}

    @app.post("/v1/gitea/repos/{owner}/{repo}/releases")
    async def gitea_create_release(owner: str, repo: str, request: Request):
        body = await request.json()
        gc = manager._get_gitea_client()
        return await gc.releases.create(owner, repo, tag_name=body.get("tag_name", ""), name=body.get("name", ""), body=body.get("body", ""))

    # ── Gitea 파일 ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/contents/{filepath:path}")
    async def gitea_file_content(owner: str, repo: str, filepath: str, ref: str = ""):
        gc = manager._get_gitea_client()
        return await gc.contents.get(owner, repo, filepath, ref=ref)

    @app.get("/v1/gitea/repos/{owner}/{repo}/tree")
    async def gitea_file_tree(owner: str, repo: str, ref: str = "main"):
        gc = manager._get_gitea_client()
        tree = await gc.contents.tree(owner, repo, ref=ref)
        return {"ok": True, "tree": [{"path": t.get("path", ""), "type": t.get("type", ""), "size": t.get("size", 0)} for t in tree[:500]]}

    # ── Gitea 커밋 ──

    # ── Gitea AI 코드 리뷰 ──

    @app.post("/v1/gitea/repos/{owner}/{repo}/pulls/{number}/review")
    async def gitea_review_pr(owner: str, repo: str, number: int):
        """AI 코드 리뷰 실행."""
        gc = manager._get_gitea_client()
        from ..connectors.gitea.reviewer import CodeReviewer
        reviewer = CodeReviewer(gc, provider=getattr(manager, "provider", None))
        return await reviewer.review_and_post(owner, repo, number)

    @app.get("/v1/gitea/repos/{owner}/{repo}/pulls/{number}/merge-check")
    async def gitea_merge_check(owner: str, repo: str, number: int):
        """머지 전 체크리스트 검증."""
        gc = manager._get_gitea_client()
        from ..connectors.gitea.reviewer import CodeReviewer
        reviewer = CodeReviewer(gc)
        return await reviewer.auto_merge_check(owner, repo, number)

    @app.post("/v1/gitea/repos/{owner}/{repo}/pulls/{number}/auto-merge")
    async def gitea_auto_merge(owner: str, repo: str, number: int, request: Request):
        """조건 충족 시 자동 머지."""
        body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
        gc = manager._get_gitea_client()
        from ..connectors.gitea.reviewer import CodeReviewer
        reviewer = CodeReviewer(gc)
        return await reviewer.auto_merge(owner, repo, number, merge_type=body.get("merge_type", "squash"))

    # ── Gitea 커밋 ──

    @app.get("/v1/gitea/repos/{owner}/{repo}/commits")
    async def gitea_commits(owner: str, repo: str, sha: str = "", limit: int = 30):
        gc = manager._get_gitea_client()
        commits = await gc.commits.list(owner, repo, sha=sha, limit=limit)
        return {"ok": True, "commits": [{"sha": c.get("sha", "")[:8], "message": c.get("commit", {}).get("message", "").split("\n")[0], "author": c.get("commit", {}).get("author", {}).get("name", ""), "date": c.get("commit", {}).get("author", {}).get("date", "")} for c in (commits if isinstance(commits, list) else [])]}

    # ── CI/CD 파이프라인 ──

    # ── 에이전트 Git 작업 ──

    @app.post("/v1/gitea/agent/hotfix")
    async def agent_hotfix(request: Request):
        body = await request.json()
        ops = manager._get_agent_git_ops()
        return await ops.create_hotfix(
            owner=body.get("owner", ""), repo=body.get("repo", ""),
            filepath=body.get("filepath", ""), content=body.get("content", ""),
            message=body.get("message", ""), title=body.get("title", ""), body=body.get("body", ""),
        )

    @app.post("/v1/gitea/agent/update-docs")
    async def agent_update_docs(request: Request):
        body = await request.json()
        ops = manager._get_agent_git_ops()
        return await ops.auto_update_docs(
            owner=body.get("owner", ""), repo=body.get("repo", ""),
            updates=body.get("updates", []),
        )

    @app.post("/v1/gitea/agent/cleanup")
    async def agent_cleanup(request: Request):
        body = await request.json()
        ops = manager._get_agent_git_ops()
        return await ops.scheduled_cleanup(owner=body.get("owner", ""), repo=body.get("repo", ""))

    # ── Wiki ↔ Gitea 동기화 ──

    @app.post("/v1/gitea/wiki/sync-to-gitea")
    async def wiki_sync_to_gitea(request: Request):
        body = await request.json()
        sync = manager._get_gitea_wiki_sync()
        return await sync.sync_wiki_to_gitea(owner=body.get("owner", ""), repo=body.get("repo", ""), categories=body.get("categories"))

    @app.post("/v1/gitea/wiki/sync-from-gitea")
    async def wiki_sync_from_gitea(request: Request):
        body = await request.json()
        sync = manager._get_gitea_wiki_sync()
        return await sync.sync_gitea_to_wiki(owner=body.get("owner", ""), repo=body.get("repo", ""))

    @app.post("/v1/gitea/wiki/auto-docs")
    async def wiki_auto_docs(request: Request):
        body = await request.json()
        sync = manager._get_gitea_wiki_sync()
        return await sync.auto_generate_repo_docs(owner=body.get("owner", ""), repo=body.get("repo", ""))

    # ── 멀티 리포 통계 + 보안 스캔 ──

    @app.get("/v1/gitea/orgs")
    async def gitea_orgs():
        tm = manager._get_teams_manager()
        return await tm.org_overview()

    @app.get("/v1/gitea/repos/{owner}/{repo}/stats")
    async def gitea_repo_stats(owner: str, repo: str):
        tm = manager._get_teams_manager()
        return await tm.repo_stats_dashboard(owner, repo)

    @app.get("/v1/gitea/repos/{owner}/{repo}/contributors")
    async def gitea_contributors(owner: str, repo: str):
        tm = manager._get_teams_manager()
        return await tm.contribution_stats(owner, repo)

    @app.post("/v1/gitea/repos/{owner}/{repo}/codeowners")
    async def gitea_codeowners(owner: str, repo: str):
        tm = manager._get_teams_manager()
        return await tm.generate_codeowners(owner, repo)

    @app.get("/v1/gitea/repos/{owner}/{repo}/secret-scan")
    async def gitea_secret_scan(owner: str, repo: str):
        sc = manager._get_security_scanner()
        return await sc.secret_scan(owner, repo)

    @app.get("/v1/gitea/repos/{owner}/{repo}/license")
    async def gitea_license_check(owner: str, repo: str):
        sc = manager._get_security_scanner()
        return await sc.license_check(owner, repo)

    @app.get("/v1/gitea/pipelines")
    def list_pipelines():
        pm = manager._get_pipeline_manager()
        return {"ok": True, "pipelines": pm.list_pipelines()}

    @app.post("/v1/gitea/pipelines/{name}/run")
    async def run_pipeline(name: str):
        pm = manager._get_pipeline_manager()
        result = await pm.run(name)
        return result

    @app.get("/v1/gitea/pipelines/runs")
    def list_pipeline_runs(pipeline: str = "", limit: int = 20):
        pm = manager._get_pipeline_manager()
        return {"ok": True, "runs": pm.list_runs(pipeline, limit)}

    @app.get("/v1/gitea/pipelines/runs/{run_id}")
    def get_pipeline_run(run_id: str):
        pm = manager._get_pipeline_manager()
        run = pm.get_run(run_id)
        if not run:
            return {"ok": False, "error": "not found"}
        return {"ok": True, **run}
