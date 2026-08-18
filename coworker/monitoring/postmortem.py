"""PostmortemGenerator — automated incident postmortem reports.

Collects incident timeline, related alerts, and metrics during the incident
window, then uses LLM to generate a structured root-cause analysis report.
Results are saved to the Wiki as a postmortem page.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class PostmortemContext:
    incident: dict = field(default_factory=dict)
    timeline: list[dict] = field(default_factory=list)
    related_alerts: list[dict] = field(default_factory=list)
    metrics_during_incident: dict[str, list[dict]] = field(default_factory=dict)
    remediation_executions: list[dict] = field(default_factory=list)


@dataclass
class PostmortemReport:
    incident_id: str = ""
    title: str = ""
    summary: str = ""
    impact: str = ""
    timeline_md: str = ""
    root_cause: str = ""
    actions_taken: str = ""
    action_items: list[str] = field(default_factory=list)
    full_markdown: str = ""


class PostmortemGenerator:
    """인시던트 사후분석 자동 생성기."""

    def __init__(
        self,
        incident_mgr: Any,
        ts_store: Any,
        alert_engine: Any,
        wiki_store: Any | None = None,
    ) -> None:
        self._incidents = incident_mgr
        self._ts = ts_store
        self._alerts = alert_engine
        self._wiki = wiki_store

    def collect_context(self, incident_id: str) -> PostmortemContext:
        ctx = PostmortemContext()
        incident = self._incidents.get(incident_id)
        if not incident:
            return ctx
        ctx.incident = incident
        ctx.timeline = incident.get("timeline", [])

        # 관련 알림 수집
        related_alert_ids = incident.get("related_alerts", [])
        if related_alert_ids and hasattr(self._alerts, "get_alert"):
            for aid in related_alert_ids:
                alert = self._alerts.get_alert(aid)
                if alert:
                    ctx.related_alerts.append(alert)

        # 인시던트 기간 메트릭 수집
        created = incident.get("created_at", 0)
        resolved = incident.get("resolved_at") or time.time()
        start = created - 300  # 5분 전부터
        end = resolved + 300   # 5분 후까지
        affected = incident.get("affected_services", [])
        for svc in affected:
            points = self._ts.query(svc, start=start, end=end)
            if points:
                ctx.metrics_during_incident[svc] = points

        return ctx

    async def generate(self, incident_id: str, provider: Any = None) -> PostmortemReport:
        ctx = self.collect_context(incident_id)
        if not ctx.incident:
            return PostmortemReport(incident_id=incident_id, title="인시던트를 찾을 수 없음")

        incident = ctx.incident
        title = f"사후분석: {incident.get('title', incident_id)}"

        if provider:
            return await self._generate_with_llm(incident_id, title, ctx, provider)
        return self._generate_template(incident_id, title, ctx)

    def _generate_template(self, incident_id: str, title: str, ctx: PostmortemContext) -> PostmortemReport:
        incident = ctx.incident
        created = incident.get("created_at", 0)
        resolved = incident.get("resolved_at", 0)
        duration = (resolved - created) / 60 if resolved and created else 0

        timeline_lines = []
        for entry in ctx.timeline:
            ts = entry.get("ts") or entry.get("timestamp", 0)
            text = entry.get("text") or entry.get("content", "")
            t_str = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "?"
            timeline_lines.append(f"- **{t_str}** \u2014 {text}")
        timeline_md = "\n".join(timeline_lines) or "타임라인 데이터 없음"

        alert_summary = ""
        if ctx.related_alerts:
            alert_lines = []
            for a in ctx.related_alerts:
                alert_lines.append(f"- [{a.get('severity', '?')}] {a.get('message', a.get('metric', '?'))}")
            alert_summary = "\n".join(alert_lines)

        summary = f"인시던트 '{incident.get('title', '')}' \u2014 심각도 {incident.get('severity', '?')}, 소요 시간 {duration:.0f}분"
        impact = f"영향 서비스: {', '.join(incident.get('affected_services', ['정보 없음']))}"
        root_cause = "근본 원인 분석이 필요합니다. AI 분석을 실행해주세요."
        actions_taken = alert_summary or "조치 기록 없음"
        action_items = ["근본 원인 심층 분석", "재발 방지 대책 수립", "모니터링 규칙 검토"]

        full_md = f"""# {title}

## 요약
{summary}

## 영향 범위
{impact}

## 타임라인
{timeline_md}

## 관련 알림
{actions_taken}

## 근본 원인
{root_cause}

## 후속 조치
{chr(10).join(f'- [ ] {item}' for item in action_items)}

---
*생성일: {time.strftime('%Y-%m-%d %H:%M:%S')}*
"""
        return PostmortemReport(
            incident_id=incident_id, title=title, summary=summary,
            impact=impact, timeline_md=timeline_md, root_cause=root_cause,
            actions_taken=actions_taken, action_items=action_items, full_markdown=full_md,
        )

    async def _generate_with_llm(self, incident_id: str, title: str, ctx: PostmortemContext, provider: Any) -> PostmortemReport:
        template = self._generate_template(incident_id, title, ctx)

        prompt = f"""다음 인시던트 데이터를 기반으로 사후분석 보고서를 한국어로 작성해주세요.

인시던트: {ctx.incident.get('title', '')}
심각도: {ctx.incident.get('severity', '')}
상태: {ctx.incident.get('status', '')}

타임라인:
{template.timeline_md}

관련 알림:
{template.actions_taken}

메트릭 데이터 서버 수: {len(ctx.metrics_during_incident)}

다음 섹션을 포함해주세요:
1. 요약 (1-2문장)
2. 영향 범위
3. 근본 원인 분석 (RCA)
4. 조치 사항
5. 재발 방지 대책 (action items, 체크리스트)

마크다운 형식으로 작성해주세요."""

        try:
            resp = await provider.complete(
                messages=[{"role": "user", "content": prompt}],
                model=None,
            )
            content = resp.get("content", template.full_markdown)
            return PostmortemReport(
                incident_id=incident_id, title=title, summary=template.summary,
                impact=template.impact, timeline_md=template.timeline_md,
                root_cause="LLM 분석 완료", actions_taken=template.actions_taken,
                action_items=template.action_items, full_markdown=content,
            )
        except Exception:
            log.warning("LLM postmortem generation failed", exc_info=True)
            return template

    async def save_to_wiki(self, report: PostmortemReport) -> dict:
        if not self._wiki:
            return {"ok": False, "error": "Wiki store not available"}
        try:
            page_id = self._wiki.create_page(
                title=report.title,
                content=report.full_markdown,
                category="postmortem",
                tags=["postmortem", "incident", report.incident_id],
            )
            return {"ok": True, "page_id": page_id}
        except Exception as e:
            log.warning("Failed to save postmortem to wiki: %s", e)
            return {"ok": False, "error": str(e)}
