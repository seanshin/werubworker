"""AgentGitOps — AI agent-driven Git operations via Gitea API.

Enables the AI agent to autonomously create branches, modify files,
and submit pull requests for automated fixes and maintenance.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class AgentGitOps:
    """에이전트 주도 Git 작업."""

    def __init__(self, gitea_client: Any, provider: Any = None) -> None:
        self._gc = gitea_client
        self._provider = provider

    async def create_hotfix(
        self,
        owner: str,
        repo: str,
        filepath: str,
        content: str,
        message: str,
        title: str = "",
        body: str = "",
    ) -> dict:
        """핫픽스: 브랜치 생성 -> 파일 수정 -> PR 생성.

        자동으로 hotfix 브랜치를 만들고 파일을 수정한 뒤 PR을 생성한다.
        """
        import secrets as _secrets
        branch_name = f"hotfix/{_secrets.token_hex(4)}"

        # 1. 브랜치 생성
        br = await self._gc.branches.create(owner, repo, branch_name, "main")
        if isinstance(br, dict) and br.get("error"):
            return {"ok": False, "error": f"branch creation failed: {br['error']}"}

        # 2. 기존 파일 SHA 확인
        existing = await self._gc.contents.get(owner, repo, filepath, ref=branch_name)
        sha = existing.get("sha", "") if isinstance(existing, dict) else ""

        # 3. 파일 수정
        if sha:
            result = await self._gc.contents.update(owner, repo, filepath, content, sha=sha, message=message, branch=branch_name)
        else:
            result = await self._gc.contents.create(owner, repo, filepath, content, message=message, branch=branch_name)

        if isinstance(result, dict) and result.get("error"):
            return {"ok": False, "error": f"file write failed: {result['error']}"}

        # 4. PR 생성
        pr_title = title or f"[hotfix] {message}"
        pr_body = body or f"자동 핫픽스 by WeruBWorker Agent\n\n변경 파일: `{filepath}`\n\n{message}"
        pr = await self._gc.pulls.create(owner, repo, title=pr_title, head=branch_name, base="main", body=pr_body)

        return {
            "ok": True,
            "branch": branch_name,
            "filepath": filepath,
            "pr_number": pr.get("number") if isinstance(pr, dict) else None,
            "pr_url": pr.get("html_url", "") if isinstance(pr, dict) else "",
        }

    async def auto_update_docs(self, owner: str, repo: str, updates: list[dict]) -> dict:
        """문서 자동 갱신: 여러 파일을 한 브랜치에서 수정 + PR.

        updates: [{"filepath": "docs/api.md", "content": "...", "message": "..."}]
        """
        import secrets as _secrets
        branch_name = f"docs/{_secrets.token_hex(4)}"

        br = await self._gc.branches.create(owner, repo, branch_name, "main")
        if isinstance(br, dict) and br.get("error"):
            return {"ok": False, "error": f"branch creation failed: {br['error']}"}

        updated_files = []
        for u in updates:
            fp = u.get("filepath", "")
            content = u.get("content", "")
            msg = u.get("message", f"update {fp}")

            existing = await self._gc.contents.get(owner, repo, fp, ref=branch_name)
            sha = existing.get("sha", "") if isinstance(existing, dict) else ""

            if sha:
                await self._gc.contents.update(owner, repo, fp, content, sha=sha, message=msg, branch=branch_name)
            else:
                await self._gc.contents.create(owner, repo, fp, content, message=msg, branch=branch_name)
            updated_files.append(fp)

        pr = await self._gc.pulls.create(
            owner, repo,
            title=f"[docs] 문서 자동 갱신 ({len(updated_files)}개 파일)",
            head=branch_name, base="main",
            body=f"WeruBWorker 에이전트 자동 문서 갱신\n\n변경 파일:\n" + "\n".join(f"- `{f}`" for f in updated_files),
        )

        return {
            "ok": True,
            "branch": branch_name,
            "files_updated": updated_files,
            "pr_number": pr.get("number") if isinstance(pr, dict) else None,
        }

    async def scheduled_cleanup(self, owner: str, repo: str) -> dict:
        """스케줄 기반 코드 정리: 머지된 브랜치 삭제, 오래된 PR 닫기."""
        results = {"branches_deleted": [], "prs_closed": []}

        # 머지된 브랜치 정리
        branches = await self._gc.branches.list(owner, repo)
        if isinstance(branches, list):
            protected = {"main", "master", "develop", "dev"}
            for b in branches:
                name = b.get("name", "")
                if name in protected:
                    continue
                # hotfix/, docs/, feature/ 패턴의 오래된 브랜치 삭제
                if name.startswith(("hotfix/", "docs/", "feature/")):
                    await self._gc.branches.delete(owner, repo, name)
                    results["branches_deleted"].append(name)

        # 30일 이상 오래된 open PR 닫기
        pulls = await self._gc.pulls.list(owner, repo, state="open")
        if isinstance(pulls, list):
            cutoff = time.time() - 30 * 86400
            for pr in pulls:
                created = pr.get("created_at", "")
                if created:
                    from datetime import datetime
                    try:
                        created_ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                        if created_ts < cutoff:
                            await self._gc.issues.close(owner, repo, pr.get("number", 0))
                            results["prs_closed"].append(pr.get("number"))
                    except Exception:
                        pass

        return {"ok": True, **results}
