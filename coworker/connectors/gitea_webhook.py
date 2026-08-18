"""GiteaWebhook — receives and processes Gitea webhook events.

Handles push, pull_request, issues, and release events from Gitea.
Can trigger automated code reviews, deployment pipelines, and notifications.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class WebhookEvent:
    """파싱된 Webhook 이벤트."""
    event_type: str        # push, pull_request, issues, release, etc.
    action: str = ""       # opened, closed, merged, created, etc.
    repo: str = ""
    sender: str = ""
    timestamp: float = 0.0
    data: dict = field(default_factory=dict)


class GiteaWebhookHandler:
    """Gitea Webhook 이벤트 처리기."""

    def __init__(self, data_dir: str | Path, secrets: Any = None, dashboard: Any = None) -> None:
        import sqlite3
        self._data_dir = Path(data_dir)
        self._secrets = secrets
        self._dashboard = dashboard
        self._db_path = self._data_dir / "gitea_webhooks.db"
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_db()
        self._webhook_secret = self._get_secret()

    def _init_db(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                action TEXT DEFAULT '',
                repo TEXT DEFAULT '',
                sender TEXT DEFAULT '',
                timestamp REAL,
                summary TEXT DEFAULT '',
                processed INTEGER DEFAULT 0
            );
        """)
        self._db.commit()

    def _get_secret(self) -> str:
        if self._secrets:
            config = self._secrets.get("gitea") or {}
            return config.get("webhook_secret", "")
        return ""

    def verify_signature(self, payload_body: bytes, signature: str) -> bool:
        """HMAC-SHA256 서명 검증."""
        if not self._webhook_secret:
            return True  # 시크릿 미설정 시 검증 스킵
        expected = hmac.new(self._webhook_secret.encode(), payload_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    def parse_event(self, event_type: str, payload: dict) -> WebhookEvent:
        """Webhook 페이로드를 파싱한다."""
        repo_info = payload.get("repository", {})
        sender_info = payload.get("sender", {})

        event = WebhookEvent(
            event_type=event_type,
            action=payload.get("action", ""),
            repo=repo_info.get("full_name", ""),
            sender=sender_info.get("login", sender_info.get("username", "")),
            timestamp=time.time(),
            data=payload,
        )
        return event

    async def process_event(self, event: WebhookEvent) -> dict:
        """이벤트를 처리하고 적절한 액션을 트리거한다."""
        summary = ""
        actions_taken = []

        if event.event_type == "push":
            result = await self._handle_push(event)
            summary = result.get("summary", "")
            actions_taken = result.get("actions", [])

        elif event.event_type == "pull_request":
            result = await self._handle_pull_request(event)
            summary = result.get("summary", "")
            actions_taken = result.get("actions", [])

        elif event.event_type == "issues":
            result = await self._handle_issues(event)
            summary = result.get("summary", "")
            actions_taken = result.get("actions", [])

        elif event.event_type == "release":
            result = await self._handle_release(event)
            summary = result.get("summary", "")
            actions_taken = result.get("actions", [])

        elif event.event_type == "create":
            ref = event.data.get("ref", "")
            ref_type = event.data.get("ref_type", "")
            summary = f"[{event.repo}] {ref_type} 생성: {ref}"

        elif event.event_type == "delete":
            ref = event.data.get("ref", "")
            ref_type = event.data.get("ref_type", "")
            summary = f"[{event.repo}] {ref_type} 삭제: {ref}"

        else:
            summary = f"[{event.repo}] {event.event_type} 이벤트 수신"

        # 자동 리뷰 트리거 실행
        for action in actions_taken:
            if action.get("type") == "auto_review" and self._dashboard:
                try:
                    gc = self._dashboard._get_gitea_client()
                    from .gitea.reviewer import CodeReviewer
                    reviewer = CodeReviewer(gc, provider=getattr(self._dashboard, "provider", None))
                    repo_parts = action["repo"].split("/")
                    if len(repo_parts) == 2:
                        review_result = await reviewer.review_and_post(repo_parts[0], repo_parts[1], action["pr_number"])
                        action["review_result"] = review_result
                except Exception as e:
                    log.warning("auto review failed: %s", e)

        # DB에 기록
        self._db.execute(
            "INSERT INTO webhook_events (event_type, action, repo, sender, timestamp, summary, processed) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (event.event_type, event.action, event.repo, event.sender, event.timestamp, summary),
        )
        self._db.commit()

        return {"ok": True, "summary": summary, "actions": actions_taken}

    async def _handle_push(self, event: WebhookEvent) -> dict:
        commits = event.data.get("commits", [])
        branch = event.data.get("ref", "").replace("refs/heads/", "")
        commit_msgs = [c.get("message", "").split("\n")[0] for c in commits[:5]]
        summary = f"[{event.repo}] {event.sender}님이 {branch}에 {len(commits)}개 커밋 push"

        actions = []
        # main/master 브랜치 push → 배포 알림
        if branch in ("main", "master"):
            actions.append({"type": "notify", "message": f"🚀 {event.repo} main 브랜치 업데이트 — {len(commits)}개 커밋"})

        return {"summary": summary, "actions": actions, "commits": commit_msgs}

    async def _handle_pull_request(self, event: WebhookEvent) -> dict:
        pr = event.data.get("pull_request", {})
        pr_number = pr.get("number", "?")
        pr_title = pr.get("title", "")
        action = event.action

        summary = f"[{event.repo}] PR #{pr_number} {action}: {pr_title}"
        actions = []

        if action == "opened":
            actions.append({"type": "notify", "message": f"📋 새 PR: {event.repo}#{pr_number} — {pr_title}"})
            actions.append({"type": "auto_review", "repo": event.repo, "pr_number": pr_number})

        elif action == "closed" and pr.get("merged"):
            actions.append({"type": "notify", "message": f"✅ PR 머지됨: {event.repo}#{pr_number} — {pr_title}"})

        return {"summary": summary, "actions": actions}

    async def _handle_issues(self, event: WebhookEvent) -> dict:
        issue = event.data.get("issue", {})
        issue_number = issue.get("number", "?")
        issue_title = issue.get("title", "")
        action = event.action

        summary = f"[{event.repo}] 이슈 #{issue_number} {action}: {issue_title}"
        actions = []

        if action == "opened":
            actions.append({"type": "notify", "message": f"🐛 새 이슈: {event.repo}#{issue_number} — {issue_title}"})

        return {"summary": summary, "actions": actions}

    async def _handle_release(self, event: WebhookEvent) -> dict:
        release = event.data.get("release", {})
        tag = release.get("tag_name", "")
        name = release.get("name", tag)
        action = event.action

        summary = f"[{event.repo}] 릴리스 {action}: {name} ({tag})"
        actions = []

        if action in ("published", "created"):
            actions.append({"type": "notify", "message": f"🎉 새 릴리스: {event.repo} {name}"})

        return {"summary": summary, "actions": actions}

    def recent_events(self, limit: int = 50, repo: str = "", event_type: str = "") -> list[dict]:
        """최근 이벤트 조회."""
        sql = "SELECT id, event_type, action, repo, sender, timestamp, summary FROM webhook_events WHERE 1=1"
        params: list = []
        if repo:
            sql += " AND repo = ?"
            params.append(repo)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self._db.execute(sql, params).fetchall()
        return [{"id": r[0], "event_type": r[1], "action": r[2], "repo": r[3], "sender": r[4], "timestamp": r[5], "summary": r[6]} for r in rows]

    def event_stats(self, days: int = 7) -> dict:
        """이벤트 통계."""
        cutoff = time.time() - days * 86400
        rows = self._db.execute(
            "SELECT event_type, COUNT(*) FROM webhook_events WHERE timestamp >= ? GROUP BY event_type",
            (cutoff,),
        ).fetchall()
        return {"ok": True, "stats": {r[0]: r[1] for r in rows}, "total": sum(r[1] for r in rows)}
