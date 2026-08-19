"""TeamsManager — multi-repo organization, team, and contribution management.

Handles Gitea organizations, teams, access permissions, contribution
statistics, and CODEOWNERS auto-generation.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


class TeamsManager:
    """조직/팀/기여 통계 관리."""

    def __init__(self, gitea_client: Any) -> None:
        self._gc = gitea_client

    async def org_overview(self) -> dict:
        """전체 조직 현황."""
        orgs = await self._gc.orgs.list()
        if not isinstance(orgs, list):
            orgs = []
        result = []
        for org in orgs:
            name = org.get("username", org.get("name", ""))
            repos = await self._gc.orgs.repos(name)
            teams = await self._gc.orgs.teams(name)
            members = await self._gc.orgs.members(name)
            result.append({
                "name": name,
                "full_name": org.get("full_name", ""),
                "description": org.get("description", ""),
                "repo_count": len(repos) if isinstance(repos, list) else 0,
                "team_count": len(teams) if isinstance(teams, list) else 0,
                "member_count": len(members) if isinstance(members, list) else 0,
            })
        return {"ok": True, "orgs": result}

    async def contribution_stats(self, owner: str, repo: str) -> dict:
        """기여 통계 (커밋, PR, 리뷰 횟수)."""
        contributors = await self._gc.repos.contributors(owner, repo)
        if not isinstance(contributors, list):
            return {"ok": True, "contributors": []}

        stats = []
        for c in contributors:
            stats.append({
                "user": c.get("login", c.get("name", "")),
                "avatar": c.get("avatar_url", ""),
                "commits": c.get("contributions", 0),
            })

        # PR 통계 보강
        pulls_closed = await self._gc.pulls.list(owner, repo, state="closed", limit=50)
        pr_by_user: dict[str, int] = {}
        if isinstance(pulls_closed, list):
            for pr in pulls_closed:
                user = pr.get("user", {}).get("login", "")
                if user:
                    pr_by_user[user] = pr_by_user.get(user, 0) + 1

        for s in stats:
            s["prs"] = pr_by_user.get(s["user"], 0)

        stats.sort(key=lambda x: x.get("commits", 0), reverse=True)
        return {"ok": True, "contributors": stats}

    async def generate_codeowners(self, owner: str, repo: str) -> dict:
        """CODEOWNERS 파일 자동 생성 (기여 통계 기반)."""
        stats = await self.contribution_stats(owner, repo)
        contributors = stats.get("contributors", [])
        if not contributors:
            return {"ok": False, "error": "no contributors"}

        top_contributor = contributors[0]["user"] if contributors else ""

        # 파일 트리 기반 CODEOWNERS 생성
        tree = await self._gc.contents.tree(owner, repo, ref="main")
        dirs: set[str] = set()
        for t in tree:
            path = t.get("path", "")
            if "/" in path:
                dirs.add(path.split("/")[0])

        lines = ["# CODEOWNERS — 자동 생성 by WeruBWorker", "#", f"# 기본 소유자: @{top_contributor}", ""]
        lines.append(f"* @{top_contributor}")

        for d in sorted(dirs):
            lines.append(f"/{d}/ @{top_contributor}")

        content = "\n".join(lines) + "\n"
        return {"ok": True, "content": content, "top_contributor": top_contributor, "dirs": sorted(dirs)}

    async def repo_stats_dashboard(self, owner: str, repo: str) -> dict:
        """리포 통계 대시보드 데이터."""
        repo_info = await self._gc.repos.get(owner, repo)
        langs = await self._gc.repos.languages(owner, repo)
        branches = await self._gc.branches.list(owner, repo)
        tags = await self._gc.tags.list(owner, repo)
        open_pulls = await self._gc.pulls.list(owner, repo, state="open")
        open_issues = await self._gc.issues.list(owner, repo, state="open")
        releases = await self._gc.releases.list(owner, repo, limit=5)
        commits = await self._gc.commits.list(owner, repo, limit=10)

        return {
            "ok": True,
            "repo": {
                "full_name": repo_info.get("full_name", "") if isinstance(repo_info, dict) else "",
                "description": repo_info.get("description", "") if isinstance(repo_info, dict) else "",
                "stars": repo_info.get("stars_count", 0) if isinstance(repo_info, dict) else 0,
                "forks": repo_info.get("forks_count", 0) if isinstance(repo_info, dict) else 0,
                "size_kb": repo_info.get("size", 0) if isinstance(repo_info, dict) else 0,
                "default_branch": repo_info.get("default_branch", "main") if isinstance(repo_info, dict) else "main",
                "created_at": repo_info.get("created_at", "") if isinstance(repo_info, dict) else "",
            },
            "languages": langs if isinstance(langs, dict) else {},
            "branches": len(branches) if isinstance(branches, list) else 0,
            "tags": len(tags) if isinstance(tags, list) else 0,
            "open_pulls": len(open_pulls) if isinstance(open_pulls, list) else 0,
            "open_issues": len(open_issues) if isinstance(open_issues, list) else 0,
            "recent_releases": [{"tag": r.get("tag_name",""), "name": r.get("name","")} for r in (releases if isinstance(releases, list) else [])],
            "recent_commits": [{"sha": c.get("sha","")[:8], "message": c.get("commit",{}).get("message","").split("\n")[0], "author": c.get("commit",{}).get("author",{}).get("name","")} for c in (commits if isinstance(commits, list) else [])],
        }


class SecurityScanner:
    """Gitea 리포 보안 스캐너."""

    def __init__(self, gitea_client: Any) -> None:
        self._gc = gitea_client

    async def secret_scan(self, owner: str, repo: str, branch: str = "main") -> dict:
        """커밋 내 시크릿(API 키, 비밀번호) 스캔."""
        import re

        patterns = [
            (r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{20,})['\"]", "API Key"),
            (r"(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]{6,})['\"]", "Password"),
            (r"(?:secret|token)\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{16,})['\"]", "Secret/Token"),
            (r"(?:aws_access_key_id)\s*[:=]\s*['\"]?(AKIA[A-Z0-9]{16})", "AWS Access Key"),
            (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Private Key"),
            (r"ghp_[a-zA-Z0-9]{36}", "GitHub PAT"),
            (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
        ]

        commits = await self._gc.commits.list(owner, repo, limit=20)
        findings = []

        if isinstance(commits, list):
            for commit in commits[:10]:
                sha = commit.get("sha", "")
                msg = commit.get("commit", {}).get("message", "")
                for pattern, name in patterns:
                    if re.search(pattern, msg, re.IGNORECASE):
                        findings.append({
                            "type": name, "commit": sha[:8],
                            "location": "commit message",
                            "severity": "critical",
                        })

        # 주요 설정 파일 스캔
        config_files = [".env", ".env.local", "config.json", "secrets.json", "credentials.json"]
        tree = await self._gc.contents.tree(owner, repo, ref=branch)
        for t in tree:
            path = t.get("path", "")
            if path in config_files or path.endswith((".pem", ".key")):
                findings.append({
                    "type": "Sensitive File",
                    "location": path,
                    "severity": "warning",
                    "message": f"잠재적 민감 파일: {path}",
                })

        return {
            "ok": True,
            "total": len(findings),
            "critical": sum(1 for f in findings if f.get("severity") == "critical"),
            "findings": findings,
        }

    async def license_check(self, owner: str, repo: str) -> dict:
        """라이선스 준수 검사."""
        # LICENSE 파일 확인
        license_data = await self._gc.contents.get(owner, repo, "LICENSE", ref="main")
        has_license = isinstance(license_data, dict) and not license_data.get("error")

        license_type = "Unknown"
        if has_license and license_data.get("content"):
            import base64
            try:
                content = base64.b64decode(license_data["content"]).decode()
                if "MIT" in content:
                    license_type = "MIT"
                elif "Apache" in content:
                    license_type = "Apache-2.0"
                elif "GPL" in content:
                    license_type = "GPL"
                elif "BSD" in content:
                    license_type = "BSD"
            except Exception:
                pass

        # 의존성 라이선스 (package.json, pyproject.toml 확인)
        dep_licenses = []
        pkg = await self._gc.contents.get(owner, repo, "pyproject.toml", ref="main")
        if isinstance(pkg, dict) and not pkg.get("error"):
            dep_licenses.append({"file": "pyproject.toml", "status": "exists"})

        return {
            "ok": True,
            "has_license": has_license,
            "license_type": license_type,
            "dependency_files": dep_licenses,
        }
