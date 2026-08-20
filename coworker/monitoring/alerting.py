"""AlertEngine — rule-based alerting with cooldown and escalation.

Evaluates metric points and health check results against configured rules.
Fires alerts via messaging connectors (Slack, Telegram) with cooldown
to prevent alert storms. Supports escalation policies for unacknowledged alerts.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class EscalationLevel:
    """에스컬레이션 단계."""
    delay_minutes: int
    channels: list[str] = field(default_factory=list)
    assignee: str = ""


@dataclass
class EscalationPolicy:
    """에스컬레이션 정책."""
    id: str = ""
    name: str = ""
    levels: list[EscalationLevel] = field(default_factory=list)
    repeat_last: bool = True
    enabled: bool = True


@dataclass
class AlertRule:
    id: str  # "rule-{hex}"
    name: str
    metric: str  # "cpu", "memory", "disk", "health_check"
    operator: str  # ">", "<", ">=", "<=", "=="
    threshold: float
    duration_seconds: int = 0  # 조건이 지속되어야 하는 시간 (0=즉시)
    severity: str = "warning"  # "info", "warning", "critical"
    channels: list[str] = field(default_factory=list)  # ["slack:C01234"]
    cooldown_seconds: int = 300  # 재알림 대기
    server_id: str = ""  # 빈 문자열 = 모든 서버
    auto_remediation: str = ""  # 복구 액션 ID (미래 확장)
    remediation_action_id: str = ""  # RemediationAction과 연결
    auto_remediate: bool = False     # 자동 복구 활성화 여부
    escalation_policy_id: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "duration_seconds": self.duration_seconds,
            "severity": self.severity,
            "channels": self.channels,
            "cooldown_seconds": self.cooldown_seconds,
            "server_id": self.server_id,
            "auto_remediation": self.auto_remediation,
            "remediation_action_id": self.remediation_action_id,
            "auto_remediate": self.auto_remediate,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AlertRule:
        return cls(
            id=d["id"],
            name=d["name"],
            metric=d["metric"],
            operator=d.get("operator", ">"),
            threshold=float(d["threshold"]),
            duration_seconds=int(d.get("duration_seconds", 0)),
            severity=d.get("severity", "warning"),
            channels=d.get("channels", []),
            cooldown_seconds=int(d.get("cooldown_seconds", 300)),
            server_id=d.get("server_id", ""),
            auto_remediation=d.get("auto_remediation", ""),
            remediation_action_id=d.get("remediation_action_id", ""),
            auto_remediate=bool(d.get("auto_remediate", False)),
            enabled=d.get("enabled", True),
        )


@dataclass
class Alert:
    id: str  # "alert-{hex}"
    rule_id: str
    server_id: str
    severity: str
    title: str
    description: str
    state: str = "firing"  # "firing", "acknowledged", "resolved"
    fired_at: float = 0.0
    resolved_at: float | None = None
    acknowledged_by: str | None = None
    last_notified_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "server_id": self.server_id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "state": self.state,
            "fired_at": self.fired_at,
            "resolved_at": self.resolved_at,
            "acknowledged_by": self.acknowledged_by,
            "last_notified_at": self.last_notified_at,
        }


_OPERATORS = {
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t,
}


class AlertEngine:
    """규칙 기반 알림 평가 및 발송 엔진."""

    def __init__(self, data_dir: Path, send_fn: Callable | None = None):
        """
        data_dir: monitoring.db 위치
        send_fn: async def send(channel: str, text: str, buttons: list | None) -> None
                 없으면 알림 저장만 하고 발송 안함
        """
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._send_fn = send_fn
        # 인메모리: 조건 지속 시간 추적 {(rule_id, server_id): first_seen_ts}
        self._condition_tracker: dict[tuple[str, str], float] = {}
        self._remediation_engine = None
        self._hc_manager = None
        # Rule cache: avoid DB query on every evaluate() call
        self._rules_cache: list[dict] | None = None
        self._rules_cache_ts: float = 0.0
        self._rules_cache_ttl: float = 5.0  # seconds
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
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    operator TEXT NOT NULL DEFAULT '>',
                    threshold REAL NOT NULL,
                    duration_seconds INTEGER NOT NULL DEFAULT 0,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    channels TEXT NOT NULL DEFAULT '[]',
                    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
                    server_id TEXT NOT NULL DEFAULT '',
                    auto_remediation TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'firing',
                    fired_at REAL NOT NULL,
                    resolved_at REAL,
                    acknowledged_by TEXT,
                    last_notified_at REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state);
                CREATE INDEX IF NOT EXISTS idx_alerts_rule ON alerts(rule_id, server_id);
                CREATE TABLE IF NOT EXISTS escalation_policies (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    levels TEXT NOT NULL DEFAULT '[]',
                    repeat_last INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
            """)
            # 기존 테이블에 에스컬레이션 컬럼 추가 (이미 존재하면 무시)
            try:
                conn.execute("ALTER TABLE alerts ADD COLUMN escalation_level INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE alerts ADD COLUMN escalation_policy_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN remediation_action_id TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN auto_remediate INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE alert_rules ADD COLUMN escalation_policy_id TEXT DEFAULT ''")
            except Exception:
                pass

    def set_remediation_engine(self, engine, hc_manager=None):
        """RemediationEngine과 HealthCheckManager를 연결."""
        self._remediation_engine = engine
        self._hc_manager = hc_manager

    # -- Rule CRUD --

    def add_rule(self, rule: AlertRule) -> dict:
        if not rule.id:
            rule.id = f"rule-{os.urandom(5).hex()}"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO alert_rules "
                "(id, name, metric, operator, threshold, duration_seconds, severity, "
                "channels, cooldown_seconds, server_id, auto_remediation, "
                "remediation_action_id, auto_remediate, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.id,
                    rule.name,
                    rule.metric,
                    rule.operator,
                    rule.threshold,
                    rule.duration_seconds,
                    rule.severity,
                    json.dumps(rule.channels),
                    rule.cooldown_seconds,
                    rule.server_id,
                    rule.auto_remediation,
                    rule.remediation_action_id,
                    1 if rule.auto_remediate else 0,
                    1 if rule.enabled else 0,
                ),
            )
        self._rules_cache = None  # invalidate cache
        return {"ok": True, "rule_id": rule.id}

    def remove_rule(self, rule_id: str) -> dict:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        self._rules_cache = None  # invalidate cache
        return {"ok": True}

    def _invalidate_rules_cache(self) -> None:
        self._rules_cache = None

    def list_rules(self, enabled_only: bool = False) -> list[dict]:
        # Fast path: return cached enabled rules if still fresh
        if enabled_only and self._rules_cache is not None:
            if time.time() - self._rules_cache_ts < self._rules_cache_ttl:
                return self._rules_cache

        with self._connect() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM alert_rules WHERE enabled = 1"
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM alert_rules").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["channels"] = json.loads(d.get("channels", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["channels"] = []
            d["enabled"] = bool(d.get("enabled", 1))
            d["auto_remediate"] = bool(d.get("auto_remediate", 0))
            result.append(d)

        # Cache enabled rules only (most frequent query path)
        if enabled_only:
            self._rules_cache = result
            self._rules_cache_ts = time.time()

        return result

    # -- 평가 --

    def evaluate(self, metrics: list[dict]) -> list[dict]:
        """메트릭 포인트 목록을 규칙과 대조하여 알림을 발생/해제."""
        rules = self.list_rules(enabled_only=True)
        now = time.time()
        new_alerts = []

        for rule_dict in rules:
            rule = AlertRule.from_dict(rule_dict)
            op_fn = _OPERATORS.get(rule.operator)
            if not op_fn:
                continue

            for point in metrics:
                sid = point.get("server_id", "")
                if rule.server_id and rule.server_id != sid:
                    continue

                value = point.get(rule.metric)
                if value is None:
                    continue

                key = (rule.id, sid)
                triggered = op_fn(float(value), rule.threshold)

                if triggered:
                    # 지속 시간 체크
                    if key not in self._condition_tracker:
                        self._condition_tracker[key] = now
                    elapsed = now - self._condition_tracker[key]
                    if elapsed >= rule.duration_seconds:
                        alert = self._fire_alert(rule, sid, value, now)
                        if alert:
                            new_alerts.append(alert)
                else:
                    # 조건 해소 → 기존 알림 해제
                    self._condition_tracker.pop(key, None)
                    self._auto_resolve(rule.id, sid, now)

        return new_alerts

    def _fire_alert(
        self, rule: AlertRule, server_id: str, value: float, now: float
    ) -> dict | None:
        """알림 발생 또는 cooldown 체크."""
        with self._lock, self._connect() as conn:
            # 이미 firing 중인 알림 확인
            existing = conn.execute(
                "SELECT * FROM alerts WHERE rule_id = ? AND server_id = ? AND state = 'firing'",
                (rule.id, server_id),
            ).fetchone()

            if existing:
                # cooldown 체크
                last = existing["last_notified_at"] or 0
                if now - last < rule.cooldown_seconds:
                    return None  # cooldown 내 → 스킵
                # 재알림
                conn.execute(
                    "UPDATE alerts SET last_notified_at = ? WHERE id = ?",
                    (now, existing["id"]),
                )
                return dict(existing)

            # 새 알림 생성
            alert_id = f"alert-{os.urandom(5).hex()}"
            title = f"[{rule.severity.upper()}] {rule.name}: {rule.metric}={value}"
            desc = (
                f"서버 {server_id}의 {rule.metric}이(가) "
                f"{rule.operator} {rule.threshold} 조건을 충족 (현재값: {value})"
            )

            conn.execute(
                "INSERT INTO alerts (id, rule_id, server_id, severity, title, description, "
                "state, fired_at, last_notified_at) VALUES (?, ?, ?, ?, ?, ?, 'firing', ?, ?)",
                (alert_id, rule.id, server_id, rule.severity, title, desc, now, now),
            )
        alert_dict = {
            "id": alert_id,
            "rule_id": rule.id,
            "server_id": server_id,
            "severity": rule.severity,
            "title": title,
            "description": desc,
            "state": "firing",
            "fired_at": now,
        }

        # 자동 복구 트리거
        if rule.auto_remediate and rule.remediation_action_id and self._remediation_engine:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        self._remediation_engine.execute_and_verify(
                            action_id=rule.remediation_action_id,
                            alert_id=alert_id,
                            server_id=server_id,
                            alert_engine=self,
                            hc_manager=self._hc_manager,
                        )
                    )
                    log.info("triggered auto-remediation %s for alert %s", rule.remediation_action_id, alert_id)
            except Exception:
                log.warning("auto-remediation trigger failed", exc_info=True)

        return alert_dict

    def _auto_resolve(self, rule_id: str, server_id: str, now: float) -> None:
        """조건 미충족 시 기존 알림 자동 해제."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE alerts SET state = 'resolved', resolved_at = ? "
                "WHERE rule_id = ? AND server_id = ? AND state = 'firing'",
                (now, rule_id, server_id),
            )

    # -- Alert 관리 --

    def acknowledge(self, alert_id: str, user: str = "system") -> dict:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE alerts SET state = 'acknowledged', acknowledged_by = ? WHERE id = ?",
                (user, alert_id),
            )
        return {"ok": True, "alert_id": alert_id}

    def resolve(self, alert_id: str) -> dict:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE alerts SET state = 'resolved', resolved_at = ? WHERE id = ?",
                (time.time(), alert_id),
            )
        return {"ok": True, "alert_id": alert_id}

    def active_alerts(self) -> list[dict]:
        """firing + acknowledged 알림 목록."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE state IN ('firing', 'acknowledged') "
                "ORDER BY fired_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def alert_history(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alerts ORDER BY fired_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def prune_alerts(self, retention_days: int = 180) -> dict:
        cutoff = time.time() - retention_days * 86400
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM alerts WHERE state = 'resolved' AND resolved_at < ?",
                (cutoff,),
            )
        return {"ok": True, "pruned": cursor.rowcount}

    # -- 알림 발송 --

    async def send_alerts(self, alerts: list[dict]) -> None:
        """새 알림을 메시징 채널로 발송."""
        if not self._send_fn or not alerts:
            return
        for alert in alerts:
            rule_id = alert.get("rule_id", "")
            rules = self.list_rules()
            rule = next((r for r in rules if r["id"] == rule_id), None)
            channels = rule.get("channels", []) if rule else []
            if not channels:
                continue
            text = self._format_alert_message(alert)
            for channel in channels:
                try:
                    await self._send_fn(channel, text, None)
                except Exception:
                    log.exception("failed to send alert to %s", channel)

    def _format_alert_message(self, alert: dict) -> str:
        severity = alert.get("severity", "warning").upper()
        emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}.get(severity, "⚠️")
        return (
            f"{emoji} *{severity}* — {alert.get('title', 'Alert')}\n"
            f"서버: `{alert.get('server_id', '?')}`\n"
            f"{alert.get('description', '')}\n"
            f"시각: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(alert.get('fired_at', 0)))}"
        )

    # -- Webhook 발송 --

    async def send_webhook(self, alerts: list[dict]) -> list[dict]:
        """알림을 Webhook URL로 발송 (Slack/Discord/Teams/커스텀)."""
        import httpx

        results = []
        webhook_urls = self._get_webhook_urls()
        if not webhook_urls or not alerts:
            return results

        for alert in alerts:
            text = self._format_alert_message(alert)
            for url in webhook_urls:
                payload = self._build_webhook_payload(url, alert, text)
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        resp = await client.post(url, json=payload)
                    results.append({
                        "ok": resp.status_code < 400,
                        "url": url[:40] + "...",
                        "status": resp.status_code,
                        "alert_id": alert.get("id", ""),
                    })
                except Exception as exc:
                    results.append({"ok": False, "url": url[:40] + "...", "error": str(exc)})
                    log.warning("webhook send failed: %s", exc)
        return results

    def _get_webhook_urls(self) -> list[str]:
        """alert_webhooks 테이블에서 URL 목록 조회."""
        try:
            with self._connect() as conn:
                # 테이블이 없으면 생성
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS alert_webhooks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        type TEXT NOT NULL DEFAULT 'slack',
                        name TEXT NOT NULL DEFAULT '',
                        enabled INTEGER NOT NULL DEFAULT 1
                    )
                """)
                rows = conn.execute(
                    "SELECT url FROM alert_webhooks WHERE enabled = 1"
                ).fetchall()
            return [r["url"] for r in rows]
        except Exception:
            return []

    def add_webhook(self, url: str, webhook_type: str = "slack",
                    name: str = "") -> dict:
        """Webhook URL 등록."""
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'slack',
                    name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute(
                "INSERT INTO alert_webhooks (url, type, name) VALUES (?, ?, ?)",
                (url, webhook_type, name or webhook_type),
            )
        return {"ok": True, "url": url[:40] + "..."}

    def remove_webhook(self, webhook_id: int) -> dict:
        """Webhook 삭제."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM alert_webhooks WHERE id = ?", (webhook_id,))
        return {"ok": True}

    def list_webhooks(self) -> list[dict]:
        """등록된 Webhook 목록."""
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS alert_webhooks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        type TEXT NOT NULL DEFAULT 'slack',
                        name TEXT NOT NULL DEFAULT '',
                        enabled INTEGER NOT NULL DEFAULT 1
                    )
                """)
                rows = conn.execute("SELECT * FROM alert_webhooks").fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # -- Escalation policy CRUD --

    def add_escalation_policy(self, name, levels, repeat_last=True):
        """에스컬레이션 정책 추가."""
        import secrets as _secrets
        policy_id = f"esc-{_secrets.token_hex(4)}"
        levels_json = json.dumps([{"delay_minutes": l.delay_minutes, "channels": l.channels, "assignee": l.assignee} for l in levels])
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO escalation_policies (id, name, levels, repeat_last) VALUES (?, ?, ?, ?)",
                (policy_id, name, levels_json, int(repeat_last)),
            )
        return policy_id

    def remove_escalation_policy(self, policy_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM escalation_policies WHERE id = ?", (policy_id,))

    def list_escalation_policies(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name, levels, repeat_last, enabled FROM escalation_policies").fetchall()
        result = []
        for r in rows:
            levels = json.loads(r["levels"]) if r["levels"] else []
            result.append({"id": r["id"], "name": r["name"], "levels": levels, "repeat_last": bool(r["repeat_last"]), "enabled": bool(r["enabled"])})
        return result

    def check_escalations(self, send_fn=None):
        """활성 알림의 에스컬레이션을 확인하고 필요 시 상위 단계로 알림 전송."""
        now = time.time()
        with self._connect() as conn:
            active = conn.execute(
                "SELECT id, rule_id, server_id, fired_at, escalation_level, escalation_policy_id "
                "FROM alerts WHERE state = 'firing'"
            ).fetchall()

            for alert_row in active:
                alert_id = alert_row["id"]
                rule_id = alert_row["rule_id"]
                server_id = alert_row["server_id"]
                fired_at = alert_row["fired_at"]
                current_level = alert_row["escalation_level"] or 0
                policy_id = alert_row["escalation_policy_id"] or ""

                if not policy_id:
                    # rule에서 policy_id 조회
                    rule_row = conn.execute(
                        "SELECT escalation_policy_id FROM alert_rules WHERE id = ?", (rule_id,)
                    ).fetchone()
                    if not rule_row or not rule_row["escalation_policy_id"]:
                        continue
                    policy_id = rule_row["escalation_policy_id"]

                policy_row = conn.execute(
                    "SELECT levels, repeat_last, enabled FROM escalation_policies WHERE id = ?",
                    (policy_id,)
                ).fetchone()
                if not policy_row or not policy_row["enabled"]:
                    continue

                levels = json.loads(policy_row["levels"]) if policy_row["levels"] else []
                repeat_last = bool(policy_row["repeat_last"])
                if not levels:
                    continue

                elapsed_minutes = (now - fired_at) / 60

                # 다음 에스컬레이션 레벨 결정
                target_level = current_level
                cumulative = 0
                for i, lvl in enumerate(levels):
                    cumulative += lvl.get("delay_minutes", 0)
                    if elapsed_minutes >= cumulative and i > current_level:
                        target_level = i

                if repeat_last and target_level >= len(levels) - 1:
                    last_delay = levels[-1].get("delay_minutes", 30)
                    extra_minutes = elapsed_minutes - cumulative
                    if extra_minutes > 0 and extra_minutes % last_delay < 1:
                        target_level = len(levels) - 1

                if target_level > current_level or (repeat_last and target_level == len(levels) - 1):
                    lvl_data = levels[min(target_level, len(levels) - 1)]
                    if send_fn and lvl_data.get("channels"):
                        for ch in lvl_data["channels"]:
                            try:
                                msg = f"\U0001f53a 에스컬레이션 L{target_level + 1}: [{server_id}] alert {alert_id}"
                                if lvl_data.get("assignee"):
                                    msg += f" \u2192 {lvl_data['assignee']}"
                                send_fn(ch, msg, [])
                            except Exception:
                                log.warning("escalation send failed", exc_info=True)

                    conn.execute(
                        "UPDATE alerts SET escalation_level = ? WHERE id = ?",
                        (target_level, alert_id),
                    )
                    log.info("escalated alert %s to level %d", alert_id, target_level)

    async def create_alert_issue(self, alert: dict, gitea_client: Any = None, owner: str = "", repo: str = "") -> dict:
        """Critical 알림 발생 시 Gitea 이슈 자동 생성."""
        if not gitea_client or not owner or not repo:
            return {"ok": False, "error": "gitea client or repo not configured"}

        severity = alert.get("severity", "warning")
        server_id = alert.get("server_id", "unknown")
        message = alert.get("message", "")

        title = f"[Alert-{severity.upper()}] {server_id}: {message[:80]}"
        body = f"""## 알림 상세

| 항목 | 값 |
|------|-----|
| 심각도 | {severity} |
| 서버 | {server_id} |
| 메시지 | {message} |
| 발생 시간 | {time.strftime('%Y-%m-%d %H:%M:%S')} |
| 알림 ID | {alert.get('id', '')} |

---
*WeruBWorker Alert -> Gitea Issue 자동 생성*
"""

        result = await gitea_client.issues.create(owner, repo, title=title, body=body)
        return {"ok": True, "issue": result}

    def _build_webhook_payload(self, url: str, alert: dict, text: str) -> dict:
        """URL 패턴에 따라 적절한 페이로드 구성."""
        # Slack Incoming Webhook
        if "hooks.slack.com" in url:
            severity = alert.get("severity", "warning")
            color = {"info": "#36a64f", "warning": "#ff9900", "critical": "#ff0000"}.get(
                severity, "#ff9900"
            )
            return {
                "attachments": [{
                    "color": color,
                    "title": alert.get("title", "Alert"),
                    "text": alert.get("description", ""),
                    "fields": [
                        {"title": "서버", "value": alert.get("server_id", "?"), "short": True},
                        {"title": "심각도", "value": severity.upper(), "short": True},
                    ],
                    "ts": int(alert.get("fired_at", time.time())),
                }]
            }
        # Discord Webhook
        if "discord.com/api/webhooks" in url:
            return {
                "content": text,
                "username": "WeruBWorker Alert",
            }
        # Microsoft Teams
        if "webhook.office.com" in url:
            return {"text": text}
        # Generic (Telegram bot, custom)
        return {"text": text, "alert": alert}
