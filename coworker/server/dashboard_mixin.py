"""Dashboard API mixin — REST endpoints for infrastructure overview and monitoring.

Adds dashboard-specific routes to the FastAPI app: infrastructure overview,
server metrics time-series, alert feed, health check status, and Wiki API.
This mixin is mixed into SessionManager and its routes are registered in create_app().
"""
from __future__ import annotations

import time
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

    def dashboard_incidents(self, status: str = "") -> dict:
        """인시던트 목록."""
        inc = self._get_incident_manager()
        if status:
            return {"ok": True, "incidents": inc.list_incidents(status=status)}
        return {"ok": True, "incidents": inc.list_incidents()}

    def dashboard_audit_recent(self, limit: int = 50) -> dict:
        """최근 운영 감사 로그."""
        audit = self._get_audit_store()
        return {"ok": True, "entries": audit.recent(limit=limit)}


def register_dashboard_routes(app, manager) -> None:
    """FastAPI 앱에 대시보드 라우트를 등록."""

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
    async def api_incidents(status: str = ""):
        return manager.dashboard_incidents(status)

    @app.get("/v1/dashboard/audit")
    async def api_audit_recent(limit: int = 50):
        return manager.dashboard_audit_recent(limit)

    # -- Wiki API --

    @app.get("/v1/wiki/pages")
    async def api_wiki_pages(category: str = "", query: str = ""):
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        pages = manager.wiki_store.list_pages(category=category, query=query)
        return {"ok": True, "count": len(pages), "pages": pages}

    @app.get("/v1/wiki/pages/{page_id}")
    async def api_wiki_page(page_id: str):
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        page = manager.wiki_store.get_page(page_id)
        if page is None:
            return {"ok": False, "error": f"page '{page_id}' not found"}
        return {"ok": True, "page": page}

    @app.get("/v1/wiki/categories")
    async def api_wiki_categories():
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        return {"ok": True, "categories": manager.wiki_store.categories()}

    @app.get("/v1/wiki/recent")
    async def api_wiki_recent(limit: int = 20):
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        return {"ok": True, "pages": manager.wiki_store.recent(limit)}

    @app.get("/v1/wiki/search")
    async def api_wiki_search(q: str = ""):
        if not hasattr(manager, "wiki_store") or not manager.wiki_store:
            return {"ok": False, "error": "wiki not configured"}
        results = manager.wiki_store.search_fts(q)
        return {"ok": True, "count": len(results), "results": results}

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
