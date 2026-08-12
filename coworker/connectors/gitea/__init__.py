"""Gitea/Forgejo connector — REST API v1 wrapper for DevView dashboard.

Compatible with Gitea, Forgejo, and other Gitea-API-compatible services.
Stores configuration in secrets.json under the key ``gitea:config``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

PREFIX = "gitea:config"


class GiteaConnector:
    """Async Gitea/Forgejo REST API v1 client."""

    def __init__(self, base_url: str, token: str, owner: str = "", repo: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.owner = owner
        self.repo = repo
        self._headers = {
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        import aiohttp

        url = f"{self.base_url}/api/v1{path}"
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
                if resp.status == 401:
                    return {"ok": False, "error": "Invalid or expired Gitea token"}
                if resp.status == 404:
                    return {"ok": False, "error": f"Not found: {path}"}
                if not resp.ok:
                    text = await resp.text()
                    return {"ok": False, "error": f"Gitea API {resp.status}: {text[:200]}"}
                return await resp.json()

    async def _post(self, path: str, payload: dict) -> Any:
        import aiohttp

        url = f"{self.base_url}/api/v1{path}"
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as resp:
                data = await resp.json()
                if not resp.ok:
                    return {"ok": False, "error": data.get("message", str(resp.status))}
                return data

    # ---------------------------------------------------------------
    # User / Auth
    # ---------------------------------------------------------------

    async def get_user(self) -> dict:
        data = await self._get("/user")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "login": data.get("login", ""), "name": data.get("full_name", "")}

    async def get_version(self) -> dict:
        data = await self._get("/version")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "version": data.get("version", "unknown")}

    # ---------------------------------------------------------------
    # Repository
    # ---------------------------------------------------------------

    async def get_repo(self) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(f"/repos/{self.owner}/{self.repo}")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {
            "ok": True,
            "name": data.get("full_name", ""),
            "default_branch": data.get("default_branch", "main"),
            "description": data.get("description", ""),
            "private": data.get("private", False),
            "open_issues_count": data.get("open_issues_count", 0),
            "stars_count": data.get("stars_count", 0),
        }

    # ---------------------------------------------------------------
    # Pull Requests
    # ---------------------------------------------------------------

    async def list_pulls(self, state: str = "open", per_page: int = 20, page: int = 1) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={"state": state, "limit": per_page, "page": page, "sort": "newest"},
        )
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        prs = []
        for pr in (data if isinstance(data, list) else []):
            prs.append({
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "state": pr.get("state", ""),
                "author": pr.get("user", {}).get("login", ""),
                "updated_at": pr.get("updated_at", ""),
                "draft": pr.get("draft", False),
                "mergeable": pr.get("mergeable"),
            })
        return {"ok": True, "pulls": prs}

    async def get_pull(self, number: int) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(f"/repos/{self.owner}/{self.repo}/pulls/{number}")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        reviews_data = await self._get(f"/repos/{self.owner}/{self.repo}/pulls/{number}/reviews")
        review_list = []
        if isinstance(reviews_data, list):
            for r in reviews_data:
                review_list.append({
                    "user": r.get("user", {}).get("login", ""),
                    "state": r.get("state", ""),
                    "body": (r.get("body") or "")[:500],
                })
        return {
            "ok": True,
            "number": data.get("number"),
            "title": data.get("title", ""),
            "body": (data.get("body") or "")[:2000],
            "state": data.get("state", ""),
            "author": data.get("user", {}).get("login", ""),
            "draft": data.get("draft", False),
            "mergeable": data.get("mergeable"),
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "changed_files": data.get("changed_files", 0),
            "reviews": review_list,
            "checks": [],
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }

    async def merge_pull(self, number: int, method: str = "squash") -> dict:
        # Gitea merge methods: merge, rebase, rebase-merge, squash
        payload = {"Do": method}
        data = await self._post(f"/repos/{self.owner}/{self.repo}/pulls/{number}/merge", payload)
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "merged": True}

    # ---------------------------------------------------------------
    # Issues
    # ---------------------------------------------------------------

    async def list_issues(self, state: str = "open", per_page: int = 20) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/issues",
            params={"state": state, "limit": per_page, "sort": "updated", "type": "issues"},
        )
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        issues = []
        for issue in (data if isinstance(data, list) else []):
            if issue.get("pull_request"):
                continue
            issues.append({
                "number": issue.get("number"),
                "title": issue.get("title", ""),
                "state": issue.get("state", ""),
                "author": issue.get("user", {}).get("login", ""),
                "labels": [l.get("name", "") for l in issue.get("labels", [])],
                "updated_at": issue.get("updated_at", ""),
            })
        return {"ok": True, "issues": issues}

    async def create_issue(self, title: str, body: str = "", labels: list[str] | None = None) -> dict:
        payload: dict = {"title": title, "body": body}
        if labels:
            # Gitea requires label IDs, not names. For simplicity, skip labels for now.
            pass
        data = await self._post(f"/repos/{self.owner}/{self.repo}/issues", payload)
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "number": data.get("number"), "html_url": data.get("html_url", "")}

    # ---------------------------------------------------------------
    # Commits
    # ---------------------------------------------------------------

    async def list_commits(self, per_page: int = 20, sha: str = "") -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        params: dict = {"limit": per_page}
        if sha:
            params["sha"] = sha
        data = await self._get(f"/repos/{self.owner}/{self.repo}/commits", params=params)
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        commits = []
        for c in (data if isinstance(data, list) else []):
            commits.append({
                "sha": c.get("sha", "")[:7],
                "message": (c.get("commit", {}).get("message", "") or "").split("\n")[0][:100],
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
            })
        return {"ok": True, "commits": commits}

    # ---------------------------------------------------------------
    # Releases
    # ---------------------------------------------------------------

    async def list_releases(self, per_page: int = 10) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(f"/repos/{self.owner}/{self.repo}/releases", params={"limit": per_page})
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        releases = []
        for r in (data if isinstance(data, list) else []):
            releases.append({
                "id": r.get("id"),
                "tag_name": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "body": (r.get("body") or "")[:500],
                "draft": r.get("draft", False),
                "prerelease": r.get("prerelease", False),
                "published_at": r.get("published_at", r.get("created_at", "")),
                "author": r.get("author", {}).get("login", ""),
            })
        return {"ok": True, "releases": releases}

    async def create_release(self, tag: str, name: str, body: str = "", draft: bool = False) -> dict:
        payload = {"tag_name": tag, "name": name, "body": body, "draft": draft}
        data = await self._post(f"/repos/{self.owner}/{self.repo}/releases", payload)
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "id": data.get("id"), "html_url": data.get("html_url", "")}

    # ---------------------------------------------------------------
    # Actions (Gitea Actions — Gitea 1.19+)
    # ---------------------------------------------------------------

    async def list_runs(self, per_page: int = 10) -> dict:
        """List workflow runs (Gitea Actions). Requires Gitea 1.19+."""
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        # Gitea Actions API may not be available on all instances
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/actions/runs",
            params={"limit": per_page},
        )
        if isinstance(data, dict) and data.get("ok") is False:
            # Fallback: Actions not available
            return {"ok": True, "runs": []}
        runs = []
        wf_runs = data.get("workflow_runs", data) if isinstance(data, dict) else data
        for run in (wf_runs if isinstance(wf_runs, list) else []):
            runs.append({
                "id": run.get("id"),
                "name": run.get("name", run.get("workflow_id", "")),
                "status": run.get("status", ""),
                "conclusion": run.get("conclusion", ""),
                "created_at": run.get("created_at", ""),
                "head_branch": run.get("head_branch", ""),
            })
        return {"ok": True, "runs": runs}


def get_gitea_connector(secrets) -> Optional[GiteaConnector]:
    """Create a GiteaConnector from stored secrets, or return None."""
    data = secrets.get(PREFIX)
    if not data or not isinstance(data, dict):
        return None
    token = data.get("token", "")
    base_url = data.get("base_url", "")
    if not token or not base_url:
        return None
    return GiteaConnector(
        base_url=base_url,
        token=token,
        owner=data.get("owner", ""),
        repo=data.get("repo", ""),
    )


def save_gitea_config(secrets, base_url: str, token: str, owner: str, repo: str) -> dict:
    """Store Gitea config."""
    if not token.strip() or not base_url.strip():
        return {"ok": False, "error": "base_url and token are required"}
    secrets.put(PREFIX, {
        "base_url": base_url.strip().rstrip("/"),
        "token": token.strip(),
        "owner": owner.strip(),
        "repo": repo.strip(),
    })
    return {"ok": True}
