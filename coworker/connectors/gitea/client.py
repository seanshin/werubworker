"""GiteaClient — async REST API client for Gitea.

Wraps the Gitea API v1 with typed methods for repos, branches, tags,
pull requests, issues, releases, file contents, and organizations.

Usage:
    client = GiteaClient(base_url="http://localhost:3000", token="...")
    repos = await client.repos.list()
    pr = await client.pulls.create("owner/repo", title="...", head="feat", base="main")
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30


class _RepoAPI:
    """리포지토리 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, limit: int = 50) -> list[dict]:
        """현재 사용자의 리포 목록."""
        return await self._c._get("/api/v1/user/repos", params={"limit": limit})

    async def get(self, owner: str, repo: str) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}")

    async def create(self, name: str, description: str = "", private: bool = False, auto_init: bool = True) -> dict:
        return await self._c._post("/api/v1/user/repos", json={
            "name": name, "description": description, "private": private, "auto_init": auto_init,
        })

    async def delete(self, owner: str, repo: str) -> dict:
        return await self._c._delete(f"/api/v1/repos/{owner}/{repo}")

    async def update(self, owner: str, repo: str, **kwargs) -> dict:
        return await self._c._patch(f"/api/v1/repos/{owner}/{repo}", json=kwargs)

    async def topics(self, owner: str, repo: str) -> list[str]:
        data = await self._c._get(f"/api/v1/repos/{owner}/{repo}/topics")
        return data.get("topics", []) if isinstance(data, dict) else []

    async def set_topics(self, owner: str, repo: str, topics: list[str]) -> dict:
        return await self._c._put(f"/api/v1/repos/{owner}/{repo}/topics", json={"topics": topics})

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        data = await self._c._get("/api/v1/repos/search", params={"q": query, "limit": limit})
        return data.get("data", []) if isinstance(data, dict) else []

    async def languages(self, owner: str, repo: str) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/languages")

    async def contributors(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/contributors") or []


class _BranchAPI:
    """브랜치 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/branches") or []

    async def get(self, owner: str, repo: str, branch: str) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/branches/{branch}")

    async def create(self, owner: str, repo: str, name: str, old_branch: str = "main") -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/branches", json={
            "new_branch_name": name, "old_branch_name": old_branch,
        })

    async def delete(self, owner: str, repo: str, branch: str) -> dict:
        return await self._c._delete(f"/api/v1/repos/{owner}/{repo}/branches/{branch}")

    async def protect(self, owner: str, repo: str, branch: str, required_approvals: int = 1) -> dict:
        """브랜치 보호 규칙 설정."""
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/branch_protections", json={
            "branch_name": branch,
            "enable_push": False,
            "enable_merge_whitelist": True,
            "required_approvals": required_approvals,
            "enable_status_check": True,
        })

    async def protections(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/branch_protections") or []


class _TagAPI:
    """태그 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/tags") or []

    async def create(self, owner: str, repo: str, tag_name: str, target: str = "main", message: str = "") -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/tags", json={
            "tag_name": tag_name, "target": target, "message": message,
        })

    async def delete(self, owner: str, repo: str, tag_name: str) -> dict:
        return await self._c._delete(f"/api/v1/repos/{owner}/{repo}/tags/{tag_name}")


class _PullAPI:
    """Pull Request 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str, state: str = "open", limit: int = 30) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/pulls", params={"state": state, "limit": limit}) or []

    async def get(self, owner: str, repo: str, number: int) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/pulls/{number}")

    async def create(self, owner: str, repo: str, title: str, head: str, base: str = "main", body: str = "") -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/pulls", json={
            "title": title, "head": head, "base": base, "body": body,
        })

    async def merge(self, owner: str, repo: str, number: int, merge_type: str = "squash", delete_branch: bool = True) -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/merge", json={
            "Do": merge_type, "delete_branch_after_merge": delete_branch,
        })

    async def diff(self, owner: str, repo: str, number: int) -> str:
        """PR diff를 텍스트로 반환."""
        resp = await self._c._http.get(
            f"{self._c._base_url}/api/v1/repos/{owner}/{repo}/pulls/{number}.diff",
            headers=self._c._headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        return resp.text if resp.status_code == 200 else ""

    async def reviews(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/reviews") or []

    async def create_review(self, owner: str, repo: str, number: int, body: str, event: str = "COMMENT") -> dict:
        """리뷰 작성. event: COMMENT, APPROVED, REQUEST_CHANGES."""
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/reviews", json={
            "body": body, "event": event,
        })

    async def labels(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/labels") or []

    async def add_labels(self, owner: str, repo: str, number: int, label_ids: list[int]) -> list[dict]:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/labels", json={"labels": label_ids}) or []

    async def files(self, owner: str, repo: str, number: int) -> list[dict]:
        """PR에서 변경된 파일 목록."""
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/pulls/{number}/files") or []


class _IssueAPI:
    """이슈 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str, state: str = "open", limit: int = 30) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/issues", params={"state": state, "limit": limit, "type": "issues"}) or []

    async def get(self, owner: str, repo: str, number: int) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/issues/{number}")

    async def create(self, owner: str, repo: str, title: str, body: str = "", labels: list[int] | None = None) -> dict:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/issues", json=payload)

    async def update(self, owner: str, repo: str, number: int, **kwargs) -> dict:
        return await self._c._patch(f"/api/v1/repos/{owner}/{repo}/issues/{number}", json=kwargs)

    async def close(self, owner: str, repo: str, number: int) -> dict:
        return await self.update(owner, repo, number, state="closed")

    async def comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/issues/{number}/comments") or []

    async def add_comment(self, owner: str, repo: str, number: int, body: str) -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})

    async def repo_labels(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/labels") or []

    async def create_label(self, owner: str, repo: str, name: str, color: str = "#0075ca") -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/labels", json={"name": name, "color": color})

    async def milestones(self, owner: str, repo: str) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/milestones") or []


class _ReleaseAPI:
    """릴리즈 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str, limit: int = 20) -> list[dict]:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/releases", params={"limit": limit}) or []

    async def get(self, owner: str, repo: str, release_id: int) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/releases/{release_id}")

    async def create(self, owner: str, repo: str, tag_name: str, name: str = "", body: str = "", draft: bool = False, prerelease: bool = False) -> dict:
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/releases", json={
            "tag_name": tag_name, "name": name or tag_name, "body": body,
            "draft": draft, "prerelease": prerelease,
        })

    async def delete(self, owner: str, repo: str, release_id: int) -> dict:
        return await self._c._delete(f"/api/v1/repos/{owner}/{repo}/releases/{release_id}")

    async def latest(self, owner: str, repo: str) -> dict:
        releases = await self.list(owner, repo, limit=1)
        return releases[0] if releases else {}


class _ContentsAPI:
    """파일 콘텐츠 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def get(self, owner: str, repo: str, filepath: str, ref: str = "") -> dict:
        params = {"ref": ref} if ref else {}
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/contents/{filepath}", params=params)

    async def list_dir(self, owner: str, repo: str, dirpath: str = "", ref: str = "") -> list[dict]:
        params = {"ref": ref} if ref else {}
        result = await self._c._get(f"/api/v1/repos/{owner}/{repo}/contents/{dirpath}", params=params)
        return result if isinstance(result, list) else []

    async def create(self, owner: str, repo: str, filepath: str, content: str, message: str = "", branch: str = "") -> dict:
        import base64
        payload: dict[str, Any] = {
            "content": base64.b64encode(content.encode()).decode(),
            "message": message or f"create {filepath}",
        }
        if branch:
            payload["branch"] = branch
        return await self._c._post(f"/api/v1/repos/{owner}/{repo}/contents/{filepath}", json=payload)

    async def update(self, owner: str, repo: str, filepath: str, content: str, sha: str, message: str = "", branch: str = "") -> dict:
        import base64
        payload: dict[str, Any] = {
            "content": base64.b64encode(content.encode()).decode(),
            "sha": sha,
            "message": message or f"update {filepath}",
        }
        if branch:
            payload["branch"] = branch
        return await self._c._put(f"/api/v1/repos/{owner}/{repo}/contents/{filepath}", json=payload)

    async def delete(self, owner: str, repo: str, filepath: str, sha: str, message: str = "") -> dict:
        return await self._c._delete(f"/api/v1/repos/{owner}/{repo}/contents/{filepath}", json={
            "sha": sha, "message": message or f"delete {filepath}",
        })

    async def tree(self, owner: str, repo: str, ref: str = "main", recursive: bool = True) -> list[dict]:
        """Git 트리 (파일 목록)."""
        params = {"recursive": "true"} if recursive else {}
        data = await self._c._get(f"/api/v1/repos/{owner}/{repo}/git/trees/{ref}", params=params)
        return data.get("tree", []) if isinstance(data, dict) else []


class _CommitAPI:
    """커밋 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self, owner: str, repo: str, sha: str = "", limit: int = 30) -> list[dict]:
        params: dict[str, Any] = {"limit": limit}
        if sha:
            params["sha"] = sha
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/commits", params=params) or []

    async def get(self, owner: str, repo: str, sha: str) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/git/commits/{sha}")

    async def compare(self, owner: str, repo: str, base: str, head: str) -> dict:
        return await self._c._get(f"/api/v1/repos/{owner}/{repo}/compare/{base}...{head}")


class _OrgAPI:
    """조직/팀 관리 API."""

    def __init__(self, client: GiteaClient) -> None:
        self._c = client

    async def list(self) -> list[dict]:
        return await self._c._get("/api/v1/user/orgs") or []

    async def get(self, org: str) -> dict:
        return await self._c._get(f"/api/v1/orgs/{org}")

    async def create(self, name: str, full_name: str = "", description: str = "") -> dict:
        return await self._c._post("/api/v1/orgs", json={
            "username": name, "full_name": full_name or name, "description": description,
        })

    async def repos(self, org: str, limit: int = 50) -> list[dict]:
        return await self._c._get(f"/api/v1/orgs/{org}/repos", params={"limit": limit}) or []

    async def teams(self, org: str) -> list[dict]:
        return await self._c._get(f"/api/v1/orgs/{org}/teams") or []

    async def members(self, org: str) -> list[dict]:
        return await self._c._get(f"/api/v1/orgs/{org}/members") or []


class GiteaClient:
    """Gitea REST API v1 비동기 클라이언트.

    모든 API를 서브 객체로 그룹화:
        client.repos.list()
        client.pulls.create(...)
        client.contents.get(...)
    """

    def __init__(self, base_url: str = "http://localhost:3000", token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

        # Sub-APIs
        self.repos = _RepoAPI(self)
        self.branches = _BranchAPI(self)
        self.tags = _TagAPI(self)
        self.pulls = _PullAPI(self)
        self.issues = _IssueAPI(self)
        self.releases = _ReleaseAPI(self)
        self.contents = _ContentsAPI(self)
        self.commits = _CommitAPI(self)
        self.orgs = _OrgAPI(self)

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"token {self._token}"
        return h

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            resp = await self._http.get(f"{self._base_url}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("Gitea GET %s failed: %s", path, e)
            return {"error": str(e)}

    async def _post(self, path: str, json: dict | None = None) -> Any:
        try:
            resp = await self._http.post(f"{self._base_url}{path}", headers=self._headers(), json=json)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except Exception as e:
            log.warning("Gitea POST %s failed: %s", path, e)
            return {"error": str(e)}

    async def _put(self, path: str, json: dict | None = None) -> Any:
        try:
            resp = await self._http.put(f"{self._base_url}{path}", headers=self._headers(), json=json)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except Exception as e:
            log.warning("Gitea PUT %s failed: %s", path, e)
            return {"error": str(e)}

    async def _patch(self, path: str, json: dict | None = None) -> Any:
        try:
            resp = await self._http.patch(f"{self._base_url}{path}", headers=self._headers(), json=json)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}
        except Exception as e:
            log.warning("Gitea PATCH %s failed: %s", path, e)
            return {"error": str(e)}

    async def _delete(self, path: str, json: dict | None = None) -> Any:
        try:
            resp = await self._http.request("DELETE", f"{self._base_url}{path}", headers=self._headers(), json=json)
            resp.raise_for_status()
            return {"ok": True}
        except Exception as e:
            log.warning("Gitea DELETE %s failed: %s", path, e)
            return {"error": str(e)}

    async def version(self) -> str:
        data = await self._get("/api/v1/version")
        return data.get("version", "") if isinstance(data, dict) else ""

    async def user(self) -> dict:
        return await self._get("/api/v1/user")

    async def close(self) -> None:
        await self._http.aclose()
