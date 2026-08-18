"""CodeReviewer — AI-powered code review for Gitea pull requests.

Analyzes PR diffs using LLM, posts review comments, auto-labels PRs,
and manages merge workflow automation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ReviewComment:
    """리뷰 코멘트."""
    path: str
    line: int = 0
    body: str = ""
    severity: str = "info"  # info, warning, critical


@dataclass
class ReviewResult:
    """리뷰 결과."""
    pr_number: int = 0
    summary: str = ""
    comments: list[ReviewComment] = field(default_factory=list)
    verdict: str = "COMMENT"  # COMMENT, APPROVED, REQUEST_CHANGES
    labels_suggested: list[str] = field(default_factory=list)
    score: int = 0  # 0~100


# ── 파일 패턴 → 라벨 매핑 ──
LABEL_PATTERNS = {
    "frontend": [r"surfaces/gui/", r"\.tsx?$", r"\.css$", r"\.html$"],
    "backend": [r"coworker/", r"\.py$"],
    "docs": [r"docs/", r"README", r"CHANGELOG", r"\.md$"],
    "tests": [r"tests/", r"test_"],
    "ci": [r"\.github/", r"\.gitea/", r"Dockerfile", r"docker-compose"],
    "monitoring": [r"monitoring/", r"alerting", r"healthcheck"],
    "security": [r"security", r"vault", r"auth"],
    "config": [r"\.json$", r"\.yaml$", r"\.toml$", r"\.env"],
}


class CodeReviewer:
    """AI 코드 리뷰어 + PR 워크플로우 자동화."""

    def __init__(self, gitea_client: Any, provider: Any = None) -> None:
        self._gc = gitea_client
        self._provider = provider

    async def review_pr(self, owner: str, repo: str, pr_number: int) -> ReviewResult:
        """PR을 분석하고 AI 리뷰를 생성한다."""
        result = ReviewResult(pr_number=pr_number)

        # 1. PR 정보 + diff 가져오기
        pr = await self._gc.pulls.get(owner, repo, pr_number)
        if isinstance(pr, dict) and pr.get("error"):
            result.summary = f"PR 조회 실패: {pr['error']}"
            return result

        diff = await self._gc.pulls.diff(owner, repo, pr_number)
        if not diff:
            result.summary = "diff를 가져올 수 없습니다."
            result.verdict = "COMMENT"
            return result

        # 2. 변경 파일 분석 → 라벨 제안
        changed_files = await self._gc.pulls.files(owner, repo, pr_number)
        if isinstance(changed_files, list):
            result.labels_suggested = self._suggest_labels(changed_files)

        # 3. LLM 리뷰
        if self._provider:
            result = await self._llm_review(pr, diff, result)
        else:
            result = self._static_review(pr, diff, result)

        return result

    async def review_and_post(self, owner: str, repo: str, pr_number: int) -> dict:
        """PR 리뷰 후 Gitea에 코멘트를 작성한다."""
        result = await self.review_pr(owner, repo, pr_number)

        # 리뷰 코멘트 작성
        body = self._format_review(result)
        review = await self._gc.pulls.create_review(
            owner, repo, pr_number,
            body=body,
            event=result.verdict,
        )

        # 라벨 자동 부착
        if result.labels_suggested:
            await self._ensure_and_apply_labels(owner, repo, pr_number, result.labels_suggested)

        return {
            "ok": True,
            "pr_number": pr_number,
            "verdict": result.verdict,
            "summary": result.summary,
            "comments_count": len(result.comments),
            "labels": result.labels_suggested,
            "score": result.score,
            "review_id": review.get("id") if isinstance(review, dict) else None,
        }

    async def auto_merge_check(self, owner: str, repo: str, pr_number: int) -> dict:
        """머지 전 체크리스트를 검증한다."""
        pr = await self._gc.pulls.get(owner, repo, pr_number)
        if not isinstance(pr, dict) or pr.get("error"):
            return {"ok": False, "error": "PR 조회 실패"}

        checks = {
            "mergeable": pr.get("mergeable", False),
            "no_conflicts": not pr.get("has_conflicts", True),
            "reviews_approved": False,
            "title_valid": bool(pr.get("title", "").strip()),
        }

        # 리뷰 승인 확인
        reviews = await self._gc.pulls.reviews(owner, repo, pr_number)
        if isinstance(reviews, list):
            approved = any(r.get("state") == "APPROVED" for r in reviews)
            checks["reviews_approved"] = approved

        all_pass = all(checks.values())
        return {
            "ok": True,
            "pr_number": pr_number,
            "can_merge": all_pass,
            "checks": checks,
        }

    async def auto_merge(self, owner: str, repo: str, pr_number: int, merge_type: str = "squash", delete_branch: bool = True) -> dict:
        """조건 충족 시 자동 머지."""
        check = await self.auto_merge_check(owner, repo, pr_number)
        if not check.get("can_merge"):
            return {"ok": False, "error": "머지 조건 미충족", "checks": check.get("checks", {})}

        result = await self._gc.pulls.merge(owner, repo, pr_number, merge_type=merge_type, delete_branch=delete_branch)
        return {"ok": True, "merged": True, "merge_type": merge_type, **result}

    def _suggest_labels(self, changed_files: list[dict]) -> list[str]:
        """변경 파일 패턴으로 라벨을 제안한다."""
        labels = set()
        for f in changed_files:
            filename = f.get("filename", "")
            for label, patterns in LABEL_PATTERNS.items():
                if any(re.search(p, filename) for p in patterns):
                    labels.add(label)
        return sorted(labels)

    async def _ensure_and_apply_labels(self, owner: str, repo: str, pr_number: int, label_names: list[str]) -> None:
        """라벨이 없으면 생성하고 PR에 부착."""
        existing = await self._gc.issues.repo_labels(owner, repo)
        existing_map = {l["name"]: l["id"] for l in (existing if isinstance(existing, list) else [])}

        label_ids = []
        colors = {"frontend": "#61dafb", "backend": "#3572A5", "docs": "#0075ca",
                  "tests": "#22c55e", "ci": "#f59e0b", "monitoring": "#8b5cf6",
                  "security": "#ef4444", "config": "#6b7280"}

        for name in label_names:
            if name in existing_map:
                label_ids.append(existing_map[name])
            else:
                color = colors.get(name, "#ededed")
                new_label = await self._gc.issues.create_label(owner, repo, name, color)
                if isinstance(new_label, dict) and new_label.get("id"):
                    label_ids.append(new_label["id"])

        if label_ids:
            await self._gc.pulls.add_labels(owner, repo, pr_number, label_ids)

    async def _llm_review(self, pr: dict, diff: str, result: ReviewResult) -> ReviewResult:
        """LLM으로 코드 리뷰."""
        title = pr.get("title", "")
        body = pr.get("body", "")
        diff_truncated = diff[:8000]

        prompt = f"""다음 Pull Request의 코드 변경 사항을 리뷰해주세요. 한국어로 작성합니다.

## PR 정보
- 제목: {title}
- 설명: {body[:500]}

## Diff
```
{diff_truncated}
```

다음 형식으로 리뷰해주세요:
1. **요약**: 전체 변경 사항 요약 (1~2문장)
2. **점수**: 0~100 (코드 품질)
3. **판정**: APPROVED (문제 없음) / COMMENT (사소한 지적) / REQUEST_CHANGES (수정 필요)
4. **지적 사항**: 각 항목을 다음 형식으로:
   - [severity: critical/warning/info] 내용

보안 취약점, 성능 이슈, 코드 품질, 에러 처리를 중점적으로 검토하세요."""

        try:
            resp = await self._provider.complete(
                messages=[{"role": "user", "content": prompt}],
                model=None,
            )
            content = resp.get("content", "")

            # 판정 파싱
            if "REQUEST_CHANGES" in content:
                result.verdict = "REQUEST_CHANGES"
            elif "APPROVED" in content:
                result.verdict = "APPROVED"
            else:
                result.verdict = "COMMENT"

            # 점수 파싱
            score_match = re.search(r'점수[:\s]*(\d+)', content)
            if score_match:
                result.score = min(100, max(0, int(score_match.group(1))))

            result.summary = content
        except Exception as e:
            log.warning("LLM review failed: %s", e)
            result = self._static_review(pr, diff, result)

        return result

    def _static_review(self, pr: dict, diff: str, result: ReviewResult) -> ReviewResult:
        """LLM 없이 정적 분석 기반 리뷰."""
        lines = diff.split("\n")
        additions = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
        files_changed = len([l for l in lines if l.startswith("diff --git")])

        warnings = []

        # 대규모 변경 감지
        if additions > 500:
            warnings.append(ReviewComment(path="", body=f"대규모 변경: +{additions}줄. PR을 분할하는 것을 고려하세요.", severity="warning"))

        # 보안 패턴 감지
        security_patterns = [
            (r"password\s*=\s*['\"]", "하드코딩된 비밀번호가 감지되었습니다."),
            (r"api[_-]?key\s*=\s*['\"]", "하드코딩된 API 키가 감지되었습니다."),
            (r"eval\(", "eval() 사용은 보안 위험이 있습니다."),
            (r"subprocess\.call\(.*shell\s*=\s*True", "shell=True는 명령 주입 위험이 있습니다."),
            (r"\.execute\([\"'].*%s", "SQL 인젝션 위험: 파라미터화된 쿼리를 사용하세요."),
        ]

        for line in lines:
            if line.startswith("+") and not line.startswith("+++"):
                for pattern, msg in security_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        warnings.append(ReviewComment(path="", body=f"보안: {msg}", severity="critical"))

        # TODO/FIXME 감지
        todo_count = sum(1 for l in lines if l.startswith("+") and re.search(r"TODO|FIXME|HACK|XXX", l, re.IGNORECASE))
        if todo_count > 0:
            warnings.append(ReviewComment(path="", body=f"TODO/FIXME 코멘트 {todo_count}개가 추가되었습니다.", severity="info"))

        # console.log / print 디버그 감지
        debug_count = sum(1 for l in lines if l.startswith("+") and re.search(r"console\.log|print\(|debugger", l))
        if debug_count > 0:
            warnings.append(ReviewComment(path="", body=f"디버그 코드 {debug_count}건이 남아있습니다. (console.log/print)", severity="warning"))

        result.comments = warnings
        result.summary = f"변경: {files_changed}개 파일, +{additions}/-{deletions}줄"

        critical = sum(1 for c in warnings if c.severity == "critical")
        if critical > 0:
            result.verdict = "REQUEST_CHANGES"
            result.score = max(0, 50 - critical * 20)
        elif len(warnings) > 3:
            result.verdict = "COMMENT"
            result.score = max(30, 70 - len(warnings) * 5)
        else:
            result.verdict = "APPROVED" if not warnings else "COMMENT"
            result.score = max(60, 90 - len(warnings) * 5)

        return result

    def _format_review(self, result: ReviewResult) -> str:
        """리뷰 결과를 마크다운으로 포맷."""
        emoji = {"APPROVED": "✅", "COMMENT": "💬", "REQUEST_CHANGES": "🔴"}.get(result.verdict, "📝")

        parts = [f"## {emoji} AI 코드 리뷰\n"]
        parts.append(f"**점수**: {result.score}/100 | **판정**: {result.verdict}\n")

        if isinstance(result.summary, str) and len(result.summary) > 200:
            # LLM 생성 리뷰는 그대로 사용
            parts.append(result.summary)
        else:
            parts.append(f"\n{result.summary}\n")
            if result.comments:
                parts.append("\n### 지적 사항\n")
                for c in result.comments:
                    icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(c.severity, "📝")
                    parts.append(f"- {icon} **[{c.severity}]** {c.body}")

        if result.labels_suggested:
            parts.append(f"\n\n**자동 라벨**: {', '.join(f'`{l}`' for l in result.labels_suggested)}")

        parts.append("\n\n---\n*WeruBWorker AI Code Reviewer*")
        return "\n".join(parts)
