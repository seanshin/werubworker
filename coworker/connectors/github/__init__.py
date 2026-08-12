"""GitHub connector — REST API v3 wrapper for DevView dashboard.

Requires a GitHub Personal Access Token stored in secrets.json
under the key ``github:pat``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

PREFIX = "github:pat"


class GitHubConnector:
    """Lightweight async GitHub REST API client."""

    def __init__(self, token: str, owner: str = "", repo: str = ""):
        self.token = token
        self.owner = owner
        self.repo = repo
        self._base = "https://api.github.com"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        import aiohttp

        url = f"{self._base}{path}"
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 401:
                    return {"ok": False, "error": "Invalid or expired GitHub token"}
                if resp.status == 404:
                    return {"ok": False, "error": f"Not found: {path}"}
                if not resp.ok:
                    text = await resp.text()
                    return {"ok": False, "error": f"GitHub API {resp.status}: {text[:200]}"}
                return await resp.json()

    # ---------------------------------------------------------------
    # User / Auth
    # ---------------------------------------------------------------

    async def get_user(self) -> dict:
        """Validate token and return authenticated user info."""
        data = await self._get("/user")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        return {"ok": True, "login": data.get("login", ""), "name": data.get("name", "")}

    # ---------------------------------------------------------------
    # Repository
    # ---------------------------------------------------------------

    async def get_repo(self) -> dict:
        """Get repository info."""
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
            "stargazers_count": data.get("stargazers_count", 0),
        }

    # ---------------------------------------------------------------
    # Pull Requests
    # ---------------------------------------------------------------

    async def list_pulls(self, state: str = "open", per_page: int = 20, page: int = 1) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/pulls",
            params={"state": state, "per_page": per_page, "page": page, "sort": "updated", "direction": "desc"},
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
                "mergeable_state": pr.get("mergeable_state", ""),
            })
        return {"ok": True, "pulls": prs}

    # ---------------------------------------------------------------
    # Actions / Workflow Runs
    # ---------------------------------------------------------------

    async def list_runs(self, per_page: int = 10) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/actions/runs",
            params={"per_page": per_page},
        )
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        runs = []
        for run in (data.get("workflow_runs") if isinstance(data, dict) else []) or []:
            runs.append({
                "id": run.get("id"),
                "name": run.get("name", ""),
                "status": run.get("status", ""),
                "conclusion": run.get("conclusion", ""),
                "created_at": run.get("created_at", ""),
                "head_branch": run.get("head_branch", ""),
            })
        return {"ok": True, "runs": runs}

    # ---------------------------------------------------------------
    # Issues
    # ---------------------------------------------------------------

    async def get_pull(self, number: int) -> dict:
        """Get PR detail with diff stats and review status."""
        data = await self._get(f"/repos/{self.owner}/{self.repo}/pulls/{number}")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        reviews = await self._get(f"/repos/{self.owner}/{self.repo}/pulls/{number}/reviews")
        review_list = []
        if isinstance(reviews, list):
            for r in reviews:
                review_list.append({
                    "user": r.get("user", {}).get("login", ""),
                    "state": r.get("state", ""),
                    "body": (r.get("body") or "")[:500],
                })
        checks = await self._get(f"/repos/{self.owner}/{self.repo}/commits/{data.get('head', {}).get('sha', '')}/check-runs")
        check_list = []
        if isinstance(checks, dict):
            for c in checks.get("check_runs", []):
                check_list.append({
                    "name": c.get("name", ""),
                    "status": c.get("status", ""),
                    "conclusion": c.get("conclusion", ""),
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
            "checks": check_list,
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }

    async def get_run_logs(self, run_id: int) -> dict:
        """Get workflow run jobs and their steps."""
        data = await self._get(f"/repos/{self.owner}/{self.repo}/actions/runs/{run_id}/jobs")
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        jobs = []
        for job in (data.get("jobs") if isinstance(data, dict) else []) or []:
            steps = []
            for s in job.get("steps", []):
                steps.append({
                    "name": s.get("name", ""),
                    "status": s.get("status", ""),
                    "conclusion": s.get("conclusion", ""),
                })
            jobs.append({
                "name": job.get("name", ""),
                "status": job.get("status", ""),
                "conclusion": job.get("conclusion", ""),
                "steps": steps,
            })
        return {"ok": True, "jobs": jobs}

    # ---------------------------------------------------------------
    # Issues
    # ---------------------------------------------------------------

    async def create_issue(self, title: str, body: str = "", labels: list[str] | None = None) -> dict:
        import aiohttp
        url = f"{self._base}/repos/{self.owner}/{self.repo}/issues"
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if not resp.ok:
                    return {"ok": False, "error": data.get("message", str(resp.status))}
                return {"ok": True, "number": data.get("number"), "html_url": data.get("html_url", "")}

    async def list_review_requests(self) -> dict:
        """PRs where the authenticated user is requested as reviewer."""
        data = await self._get(f"/repos/{self.owner}/{self.repo}/pulls", params={"state": "open", "per_page": 50})
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        user_data = await self._get("/user")
        my_login = user_data.get("login", "") if isinstance(user_data, dict) else ""
        review_prs = []
        for pr in (data if isinstance(data, list) else []):
            reviewers = [r.get("login", "") for r in pr.get("requested_reviewers", [])]
            if my_login in reviewers:
                review_prs.append({
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "author": pr.get("user", {}).get("login", ""),
                    "updated_at": pr.get("updated_at", ""),
                })
        return {"ok": True, "reviews": review_prs}

    # ---------------------------------------------------------------
    # Releases
    # ---------------------------------------------------------------

    async def list_releases(self, per_page: int = 10) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(f"/repos/{self.owner}/{self.repo}/releases", params={"per_page": per_page})
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
                "published_at": r.get("published_at", ""),
                "author": r.get("author", {}).get("login", ""),
            })
        return {"ok": True, "releases": releases}

    async def create_release(self, tag: str, name: str, body: str = "", draft: bool = False) -> dict:
        import aiohttp
        url = f"{self._base}/repos/{self.owner}/{self.repo}/releases"
        payload = {"tag_name": tag, "name": name, "body": body, "draft": draft}
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if not resp.ok:
                    return {"ok": False, "error": data.get("message", str(resp.status))}
                return {"ok": True, "id": data.get("id"), "html_url": data.get("html_url", "")}

    # ---------------------------------------------------------------
    # Commits
    # ---------------------------------------------------------------

    async def list_commits(self, per_page: int = 20, sha: str = "") -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        params: dict = {"per_page": per_page}
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
    # PR Merge
    # ---------------------------------------------------------------

    async def merge_pull(self, number: int, method: str = "squash") -> dict:
        import aiohttp
        url = f"{self._base}/repos/{self.owner}/{self.repo}/pulls/{number}/merge"
        payload = {"merge_method": method}
        async with aiohttp.ClientSession(headers=self._headers) as session:
            async with session.put(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if not resp.ok:
                    return {"ok": False, "error": data.get("message", str(resp.status))}
                return {"ok": True, "sha": data.get("sha", ""), "merged": data.get("merged", False)}

    async def list_issues(self, state: str = "open", per_page: int = 20) -> dict:
        if not self.owner or not self.repo:
            return {"ok": False, "error": "owner/repo not configured"}
        data = await self._get(
            f"/repos/{self.owner}/{self.repo}/issues",
            params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"},
        )
        if isinstance(data, dict) and data.get("ok") is False:
            return data
        issues = []
        for issue in (data if isinstance(data, list) else []):
            if issue.get("pull_request"):
                continue  # skip PRs
            issues.append({
                "number": issue.get("number"),
                "title": issue.get("title", ""),
                "state": issue.get("state", ""),
                "author": issue.get("user", {}).get("login", ""),
                "labels": [l.get("name", "") for l in issue.get("labels", [])],
                "updated_at": issue.get("updated_at", ""),
            })
        return {"ok": True, "issues": issues}


def get_github_connector(secrets) -> Optional[GitHubConnector]:
    """Create a GitHubConnector from stored secrets, or return None."""
    data = secrets.get(PREFIX)
    if not data or not isinstance(data, dict):
        return None
    token = data.get("token", "")
    if not token:
        return None
    return GitHubConnector(
        token=token,
        owner=data.get("owner", ""),
        repo=data.get("repo", ""),
    )


def save_github_config(secrets, token: str, owner: str, repo: str) -> dict:
    """Store GitHub PAT and repo config."""
    if not token.strip():
        return {"ok": False, "error": "token is required"}
    secrets.put(PREFIX, {
        "token": token.strip(),
        "owner": owner.strip(),
        "repo": repo.strip(),
    })
    return {"ok": True}
