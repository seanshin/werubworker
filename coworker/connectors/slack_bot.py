"""SlackBot — bidirectional Slack integration for WeruBWorker.

Provides slash commands, interactive button approvals, thread-based incident
conversations, and channel-to-session mapping.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)


@dataclass
class SlashCommand:
    """슬래시 명령어 정의."""
    name: str              # "/werub"
    subcommand: str        # "status", "deploy", "alert" 등
    description: str
    handler: str           # 처리할 내부 함수명


@dataclass
class ChannelMapping:
    """Slack 채널 ↔ WeruBWorker 세션 매핑."""
    channel_id: str
    channel_name: str
    session_id: str
    created_at: float = 0.0


class SlackBot:
    """Slack Bot 양방향 연동 엔진."""

    SLASH_COMMANDS = {
        "status": "현재 서버 상태 요약",
        "alerts": "활성 알림 목록",
        "incidents": "진행 중인 인시던트",
        "health": "헬스체크 결과",
        "deploy": "배포 상태 확인",
        "backup": "백업 실행",
        "score": "보안 점수 조회",
        "help": "명령어 도움말",
    }

    def __init__(self, secrets: Any = None, dashboard: Any = None) -> None:
        self._secrets = secrets
        self._dashboard = dashboard
        self._channel_mappings: dict[str, ChannelMapping] = {}
        self._pending_approvals: dict[str, dict] = {}

    def get_bot_token(self) -> str | None:
        """Slack Bot 토큰 조회."""
        if not self._secrets:
            return None
        slack_config = self._secrets.get("slack") or {}
        return slack_config.get("bot_token") or slack_config.get("token")

    async def handle_slash_command(self, command: str, text: str, channel_id: str, user_id: str, user_name: str = "") -> dict:
        """슬래시 명령어 처리.

        Parameters
        ----------
        command : str
            "/werub" 등
        text : str
            서브커맨드 + 인자 (예: "status web-01")
        """
        parts = text.strip().split(None, 1)
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1] if len(parts) > 1 else ""

        if subcommand == "help":
            return self._help_response()

        if subcommand == "status":
            return await self._cmd_status(args)
        elif subcommand == "alerts":
            return await self._cmd_alerts()
        elif subcommand == "incidents":
            return await self._cmd_incidents()
        elif subcommand == "health":
            return await self._cmd_health()
        elif subcommand == "backup":
            return await self._cmd_backup()
        elif subcommand == "score":
            return await self._cmd_score()
        else:
            return {"response_type": "ephemeral", "text": f"알 수 없는 명령: `{subcommand}`\n`/werub help`로 도움말을 확인하세요."}

    async def handle_interaction(self, payload: dict) -> dict:
        """Slack 대화형 버튼/액션 처리."""
        action_type = payload.get("type", "")

        if action_type == "block_actions":
            actions = payload.get("actions", [])
            for action in actions:
                action_id = action.get("action_id", "")
                value = action.get("value", "")

                if action_id.startswith("approve_"):
                    return await self._handle_approval(value, approved=True, user=payload.get("user", {}).get("name", ""))
                elif action_id.startswith("deny_"):
                    return await self._handle_approval(value, approved=False, user=payload.get("user", {}).get("name", ""))

        return {"text": "처리 완료"}

    def create_approval_request(self, request_id: str, title: str, description: str, channel_id: str) -> dict:
        """승인 요청 메시지를 생성한다."""
        self._pending_approvals[request_id] = {
            "title": title, "description": description,
            "channel_id": channel_id, "created_at": time.time(),
        }

        return {
            "channel": channel_id,
            "text": f"🔔 승인 요청: {title}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"🔔 승인 요청: {title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": description}},
                {
                    "type": "actions",
                    "elements": [
                        {"type": "button", "text": {"type": "plain_text", "text": "✅ 승인"}, "style": "primary", "action_id": f"approve_{request_id}", "value": request_id},
                        {"type": "button", "text": {"type": "plain_text", "text": "❌ 거부"}, "style": "danger", "action_id": f"deny_{request_id}", "value": request_id},
                    ],
                },
            ],
        }

    def create_incident_thread(self, incident_id: str, title: str, severity: str, channel_id: str) -> dict:
        """인시던트 스레드 메시지를 생성한다."""
        sev_emoji = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🔵"}.get(severity, "⚪")
        return {
            "channel": channel_id,
            "text": f"{sev_emoji} 인시던트: {title}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"{sev_emoji} [{severity}] {title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"인시던트 ID: `{incident_id}`\n상태: *investigating*\n\n이 스레드에서 인시던트를 추적합니다."}},
                {"type": "divider"},
            ],
        }

    def map_channel(self, channel_id: str, channel_name: str, session_id: str) -> dict:
        """채널을 세션에 매핑."""
        self._channel_mappings[channel_id] = ChannelMapping(
            channel_id=channel_id, channel_name=channel_name,
            session_id=session_id, created_at=time.time(),
        )
        return {"ok": True, "channel_id": channel_id, "session_id": session_id}

    def get_session_for_channel(self, channel_id: str) -> str | None:
        mapping = self._channel_mappings.get(channel_id)
        return mapping.session_id if mapping else None

    def list_mappings(self) -> list[dict]:
        return [{"channel_id": m.channel_id, "channel_name": m.channel_name, "session_id": m.session_id, "created_at": m.created_at} for m in self._channel_mappings.values()]

    # ── Command handlers ──

    def _help_response(self) -> dict:
        lines = ["*WeruBWorker 명령어*\n"]
        for cmd, desc in self.SLASH_COMMANDS.items():
            lines.append(f"• `/werub {cmd}` — {desc}")
        return {"response_type": "ephemeral", "text": "\n".join(lines)}

    async def _cmd_status(self, server_id: str = "") -> dict:
        if not self._dashboard:
            return {"text": "대시보드 연결 안됨"}
        overview = self._dashboard.dashboard_overview()
        servers = overview.get("servers", [])
        if server_id:
            servers = [s for s in servers if s.get("server_id") == server_id]
        lines = [f"*서버 상태* ({len(servers)}대)\n"]
        for s in servers[:10]:
            status = "🟢" if s.get("status") == "healthy" else "🔴"
            lines.append(f"{status} *{s.get('name', s.get('server_id', '?'))}* — CPU {s.get('cpu_percent', 0):.0f}% | MEM {s.get('memory_percent', 0):.0f}% | DISK {s.get('disk_percent', 0):.0f}%")
        return {"response_type": "in_channel", "text": "\n".join(lines)}

    async def _cmd_alerts(self) -> dict:
        if not self._dashboard:
            return {"text": "대시보드 연결 안됨"}
        feed = self._dashboard.dashboard_alert_feed()
        active = feed.get("active", [])
        if not active:
            return {"text": "✅ 활성 알림이 없습니다."}
        lines = [f"*활성 알림* ({len(active)}건)\n"]
        for a in active[:10]:
            sev = {"critical": "🔴", "warning": "🟡"}.get(a.get("severity", ""), "⚪")
            lines.append(f"{sev} [{a.get('severity', '?')}] {a.get('message', '?')} — {a.get('server_id', '?')}")
        return {"response_type": "in_channel", "text": "\n".join(lines)}

    async def _cmd_incidents(self) -> dict:
        if not self._dashboard:
            return {"text": "대시보드 연결 안됨"}
        data = self._dashboard.dashboard_incidents()
        incidents = [i for i in data.get("incidents", []) if i.get("status") != "resolved"]
        if not incidents:
            return {"text": "✅ 진행 중인 인시던트가 없습니다."}
        lines = [f"*진행 중 인시던트* ({len(incidents)}건)\n"]
        for i in incidents[:10]:
            lines.append(f"• [{i.get('severity', '?')}] *{i.get('title', '?')}* — {i.get('status', '?')}")
        return {"response_type": "in_channel", "text": "\n".join(lines)}

    async def _cmd_health(self) -> dict:
        if not self._dashboard:
            return {"text": "대시보드 연결 안됨"}
        overview = self._dashboard.dashboard_overview()
        checks = overview.get("health_checks", [])
        if not checks:
            return {"text": "등록된 헬스체크가 없습니다."}
        lines = [f"*헬스체크* ({len(checks)}건)\n"]
        for c in checks[:15]:
            icon = "✅" if c.get("last_status") == "ok" else "❌"
            lines.append(f"{icon} *{c.get('name', '?')}* ({c.get('type', '?')}) — {c.get('last_latency_ms', 0):.0f}ms")
        return {"response_type": "in_channel", "text": "\n".join(lines)}

    async def _cmd_backup(self) -> dict:
        if not self._dashboard:
            return {"text": "대시보드 연결 안됨"}
        bm = self._dashboard._get_backup_manager()
        result = bm.create_backup()
        if result.get("ok"):
            return {"response_type": "in_channel", "text": f"✅ 백업 완료: {result.get('size_human', '?')} ({', '.join(result.get('targets', []))})"}
        return {"text": f"❌ 백업 실패: {result.get('errors', [])}"}

    async def _cmd_score(self) -> dict:
        from ..tools.security_scan import security_score
        result = security_score()
        if result.get("ok"):
            grade = result.get("grade", "?")
            score = result.get("overall_score", 0)
            emoji = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🔴"}.get(grade, "⚪")
            return {"response_type": "in_channel", "text": f"{emoji} 보안 등급: *{grade}* ({score}점)"}
        return {"text": "보안 점수 산출 실패"}

    async def _handle_approval(self, request_id: str, approved: bool, user: str) -> dict:
        pending = self._pending_approvals.pop(request_id, None)
        action = "승인" if approved else "거부"
        title = pending.get("title", request_id) if pending else request_id
        return {"text": f"{'✅' if approved else '❌'} *{title}* — {user}님이 {action}했습니다."}
