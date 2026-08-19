"""GiteaWikiSync — bidirectional Wiki synchronization.

Syncs WeruBWorker Wiki pages to/from Gitea Wiki (git-based),
auto-generates repo documentation from Wiki, and mirrors
operational runbooks.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class GiteaWikiSync:
    """Wiki <-> Gitea 동기화."""

    def __init__(self, gitea_client: Any, wiki_store: Any = None) -> None:
        self._gc = gitea_client
        self._wiki = wiki_store

    async def sync_wiki_to_gitea(self, owner: str, repo: str, categories: list[str] | None = None) -> dict:
        """WeruBWorker Wiki -> Gitea 리포 docs/ 디렉토리에 동기화."""
        if not self._wiki:
            return {"ok": False, "error": "wiki store not available"}

        pages = self._wiki.list_pages(category="")
        if categories:
            pages = [p for p in pages if p.get("category") in categories]

        synced = []
        errors = []

        for page in pages:
            page_id = page.get("id") or page.get("page_id", "")
            title = page.get("title", "untitled")
            content = ""

            # 페이지 내용 가져오기
            full = self._wiki.get_page(page_id) if hasattr(self._wiki, "get_page") else None
            if full:
                content = full.get("content", "") if isinstance(full, dict) else ""

            if not content:
                continue

            # docs/{category}/{title}.md 로 저장
            category = page.get("category", "general")
            safe_title = title.replace("/", "_").replace(" ", "_")
            filepath = f"docs/wiki/{category}/{safe_title}.md"

            try:
                existing = await self._gc.contents.get(owner, repo, filepath, ref="main")
                sha = existing.get("sha", "") if isinstance(existing, dict) and not existing.get("error") else ""

                if sha:
                    await self._gc.contents.update(owner, repo, filepath, content, sha=sha, message=f"wiki sync: {title}")
                else:
                    await self._gc.contents.create(owner, repo, filepath, content, message=f"wiki sync: {title}")
                synced.append(filepath)
            except Exception as e:
                errors.append(f"{filepath}: {e}")

        return {"ok": True, "synced": len(synced), "files": synced, "errors": errors}

    async def sync_gitea_to_wiki(self, owner: str, repo: str, path_prefix: str = "docs/wiki") -> dict:
        """Gitea 리포 docs/ -> WeruBWorker Wiki로 동기화."""
        if not self._wiki:
            return {"ok": False, "error": "wiki store not available"}

        tree = await self._gc.contents.tree(owner, repo, ref="main")
        md_files = [t for t in tree if t.get("path", "").startswith(path_prefix) and t.get("path", "").endswith(".md")]

        imported = []
        for f in md_files:
            filepath = f.get("path", "")
            try:
                import base64
                data = await self._gc.contents.get(owner, repo, filepath, ref="main")
                if isinstance(data, dict) and data.get("content"):
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")

                    # 카테고리와 제목 추출
                    parts = filepath.replace(path_prefix + "/", "").rsplit("/", 1)
                    category = parts[0] if len(parts) > 1 else "general"
                    title = parts[-1].replace(".md", "").replace("_", " ")

                    # Wiki에 저장
                    if hasattr(self._wiki, "create_page"):
                        self._wiki.create_page(title=title, content=content, category=category, tags=["gitea-sync"])
                        imported.append(filepath)
            except Exception as e:
                log.warning("import failed for %s: %s", filepath, e)

        return {"ok": True, "imported": len(imported), "files": imported}

    async def auto_generate_repo_docs(self, owner: str, repo: str) -> dict:
        """리포 분석 -> 자동 문서 생성 (README 기반 Wiki)."""
        # README 읽기
        readme = await self._gc.contents.get(owner, repo, "README.md", ref="main")
        readme_content = ""
        if isinstance(readme, dict) and readme.get("content"):
            import base64
            readme_content = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")

        # 언어 통계
        langs = await self._gc.repos.languages(owner, repo)
        lang_info = ", ".join(f"{k}: {v}" for k, v in (langs.items() if isinstance(langs, dict) else []))

        # 리포 정보
        repo_info = await self._gc.repos.get(owner, repo)

        if self._wiki and readme_content:
            title = f"리포: {owner}/{repo}"
            content = f"""# {title}

## 기본 정보
- **설명**: {repo_info.get('description', '') if isinstance(repo_info, dict) else ''}
- **언어**: {lang_info}
- **URL**: http://localhost:3000/{owner}/{repo}

## README
{readme_content[:3000]}

---
*자동 생성: {time.strftime('%Y-%m-%d %H:%M:%S')}*
"""
            try:
                self._wiki.create_page(title=title, content=content, category="repository", tags=["repo", owner, repo])
            except Exception:
                pass

        return {"ok": True, "repo": f"{owner}/{repo}", "languages": lang_info}
