"""CI/CD pipeline tools — GitHub Actions workflow status, triggering, logs,
deployment status, and rollback.

Uses the GitHub REST API via ``httpx``. GitHub token resolved from
``secrets.json`` (key ``github:default``, field ``token``) or the
``GITHUB_TOKEN`` environment variable.

Tools that mutate state (``ci_trigger``, ``deploy_rollback``) require approval;
the rest are read-only.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

import aisuite as ai

# ---------------------------------------------------------------------------
# httpx — best-effort import
# ---------------------------------------------------------------------------
try:
    import httpx

    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

_GH_API = "https://api.github.com"


def _get_token(context: Any = None) -> Optional[str]:
    """Resolve a GitHub token: secrets store first, then env."""
    if context is not None:
        secrets = getattr(context, "secrets", None)
        if secrets is not None:
            data = secrets.get("github:default")
            if data and isinstance(data, dict):
                token = data.get("token")
                if token:
                    return str(token)
    return os.environ.get("GITHUB_TOKEN")


def _headers(token: Optional[str]) -> dict[str, str]:
    hdrs: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


def _parse_owner_repo(repo: str) -> tuple[str, str]:
    """Parse 'owner/repo' from a string (handles full URLs too)."""
    repo = repo.strip().rstrip("/")
    if "github.com/" in repo:
        # https://github.com/owner/repo or git@github.com:owner/repo
        parts = repo.split("github.com/")[-1].split("github.com:")[-1]
        repo = parts.removesuffix(".git")
    if "/" not in repo:
        return "", repo
    segments = repo.split("/")
    return segments[0], segments[1]


def _api_get(
    path: str, token: Optional[str], params: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """GET request to GitHub API."""
    if not _HAS_HTTPX:
        return {"ok": False, "error": "httpx is not installed"}
    try:
        resp = httpx.get(
            f"{_GH_API}{path}",
            headers=_headers(token),
            params=params,
            timeout=30,
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"GitHub API {resp.status_code}: {resp.text[:500]}",
            }
        return {"ok": True, "data": resp.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"HTTP error: {exc}"}


def _api_post(
    path: str,
    token: Optional[str],
    json_body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """POST request to GitHub API."""
    if not _HAS_HTTPX:
        return {"ok": False, "error": "httpx is not installed"}
    try:
        resp = httpx.post(
            f"{_GH_API}{path}",
            headers=_headers(token),
            json=json_body or {},
            timeout=30,
        )
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error": f"GitHub API {resp.status_code}: {resp.text[:500]}",
            }
        # 204 No Content is success for dispatches
        if resp.status_code == 204:
            return {"ok": True, "data": None}
        return {"ok": True, "data": resp.json()}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"HTTP error: {exc}"}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _ci_status(token: Optional[str], repo: str = "", branch: str = "main") -> dict[str, Any]:
    """Check CI pipeline status (GitHub Actions workflow runs)."""
    if not repo:
        return {"ok": False, "error": "repo is required (e.g. 'owner/repo')"}
    owner, name = _parse_owner_repo(repo)
    if not owner:
        return {"ok": False, "error": "repo must be 'owner/repo'"}

    params: dict[str, Any] = {"branch": branch, "per_page": 10}
    result = _api_get(f"/repos/{owner}/{name}/actions/runs", token, params)
    if not result.get("ok"):
        return result

    runs = result["data"].get("workflow_runs", [])
    summary = []
    for run in runs:
        summary.append(
            {
                "id": run.get("id"),
                "name": run.get("name"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "branch": run.get("head_branch"),
                "event": run.get("event"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "url": run.get("html_url"),
            }
        )
    return {"ok": True, "repo": f"{owner}/{name}", "branch": branch, "runs": summary}


def _ci_trigger(
    token: Optional[str],
    repo: str,
    workflow: str = "",
    branch: str = "main",
) -> dict[str, Any]:
    """Trigger a CI workflow run."""
    if not repo:
        return {"ok": False, "error": "repo is required (e.g. 'owner/repo')"}
    owner, name = _parse_owner_repo(repo)
    if not owner:
        return {"ok": False, "error": "repo must be 'owner/repo'"}

    # If no workflow specified, list available workflows
    if not workflow:
        result = _api_get(f"/repos/{owner}/{name}/actions/workflows", token)
        if not result.get("ok"):
            return result
        workflows = result["data"].get("workflows", [])
        return {
            "ok": False,
            "error": "workflow is required",
            "available_workflows": [
                {"id": w["id"], "name": w["name"], "path": w["path"]} for w in workflows
            ],
        }

    # workflow can be an ID (numeric) or filename (e.g. "ci.yml")
    path = f"/repos/{owner}/{name}/actions/workflows/{workflow}/dispatches"
    result = _api_post(path, token, {"ref": branch})
    if result.get("ok"):
        return {
            "ok": True,
            "message": f"Workflow '{workflow}' triggered on {branch}",
            "repo": f"{owner}/{name}",
        }
    return result


def _ci_logs(token: Optional[str], repo: str, run_id: str = "") -> dict[str, Any]:
    """View CI build logs (latest or specific run)."""
    if not repo:
        return {"ok": False, "error": "repo is required (e.g. 'owner/repo')"}
    owner, name = _parse_owner_repo(repo)
    if not owner:
        return {"ok": False, "error": "repo must be 'owner/repo'"}

    # If no run_id, get the latest run
    if not run_id:
        result = _api_get(f"/repos/{owner}/{name}/actions/runs", token, {"per_page": 1})
        if not result.get("ok"):
            return result
        runs = result["data"].get("workflow_runs", [])
        if not runs:
            return {"ok": False, "error": "No workflow runs found"}
        run_id = str(runs[0]["id"])

    # Get the jobs for this run (logs URL requires download which returns a zip;
    # instead we fetch jobs and their step outputs which is more useful as text).
    result = _api_get(f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs", token)
    if not result.get("ok"):
        return result

    jobs = result["data"].get("jobs", [])
    job_summaries = []
    for job in jobs:
        steps = []
        for step in job.get("steps", []):
            steps.append(
                {
                    "name": step.get("name"),
                    "status": step.get("status"),
                    "conclusion": step.get("conclusion"),
                    "number": step.get("number"),
                }
            )
        job_summaries.append(
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "steps": steps,
            }
        )
    return {
        "ok": True,
        "repo": f"{owner}/{name}",
        "run_id": run_id,
        "jobs": job_summaries,
    }


def _deploy_status(token: Optional[str], repo: str = "", service: str = "") -> dict[str, Any]:
    """Check deployment status via GitHub Deployments API."""
    if not repo and not service:
        return {
            "ok": False,
            "error": "repo or service is required. Provide repo as 'owner/repo'.",
        }
    # Treat service as repo if repo not given (common shortcut)
    target = repo or service
    owner, name = _parse_owner_repo(target)
    if not owner:
        return {"ok": False, "error": "repo must be 'owner/repo'"}

    # Fetch recent deployments
    result = _api_get(f"/repos/{owner}/{name}/deployments", token, {"per_page": 10})
    if not result.get("ok"):
        return result

    deployments = result["data"] if isinstance(result["data"], list) else []
    summaries = []
    for dep in deployments[:10]:
        dep_id = dep.get("id")
        # Fetch latest status for each deployment
        status_result = _api_get(
            f"/repos/{owner}/{name}/deployments/{dep_id}/statuses",
            token,
            {"per_page": 1},
        )
        latest_status = {}
        if status_result.get("ok"):
            statuses = status_result["data"]
            if isinstance(statuses, list) and statuses:
                latest_status = {
                    "state": statuses[0].get("state"),
                    "description": statuses[0].get("description"),
                    "created_at": statuses[0].get("created_at"),
                    "environment_url": statuses[0].get("environment_url"),
                }
        summaries.append(
            {
                "id": dep_id,
                "environment": dep.get("environment"),
                "ref": dep.get("ref"),
                "sha": dep.get("sha", "")[:12],
                "creator": dep.get("creator", {}).get("login"),
                "created_at": dep.get("created_at"),
                "status": latest_status,
            }
        )
    return {
        "ok": True,
        "repo": f"{owner}/{name}",
        "deployments": summaries,
    }


def _deploy_rollback(
    token: Optional[str],
    repo: str = "",
    service: str = "",
    version: str = "",
) -> dict[str, Any]:
    """Rollback to a previous deployment version.

    Creates a new deployment using the specified ref/SHA, effectively rolling
    back. If *version* is empty, looks up the second-most-recent deployment's
    ref as the rollback target.
    """
    target = repo or service
    if not target:
        return {"ok": False, "error": "repo/service is required (e.g. 'owner/repo')"}
    owner, name = _parse_owner_repo(target)
    if not owner:
        return {"ok": False, "error": "repo must be 'owner/repo'"}

    # If no version, find previous deployment ref
    if not version:
        result = _api_get(f"/repos/{owner}/{name}/deployments", token, {"per_page": 5})
        if not result.get("ok"):
            return result
        deps = result["data"] if isinstance(result["data"], list) else []
        if len(deps) < 2:
            return {
                "ok": False,
                "error": "Not enough deployment history to determine rollback target. "
                "Specify 'version' explicitly.",
            }
        version = deps[1].get("ref", "")
        if not version:
            return {"ok": False, "error": "Could not determine previous version ref"}

    # Determine environment from latest deployment
    env_result = _api_get(f"/repos/{owner}/{name}/deployments", token, {"per_page": 1})
    environment = "production"
    if env_result.get("ok"):
        deps = env_result["data"] if isinstance(env_result["data"], list) else []
        if deps:
            environment = deps[0].get("environment", "production")

    # Create a new deployment at the rollback ref
    result = _api_post(
        f"/repos/{owner}/{name}/deployments",
        token,
        {
            "ref": version,
            "environment": environment,
            "description": f"Rollback to {version}",
            "auto_merge": False,
            "required_contexts": [],  # skip status checks for rollback
        },
    )
    if result.get("ok"):
        dep_data = result.get("data") or {}
        return {
            "ok": True,
            "message": f"Rollback deployment created for ref '{version}'",
            "repo": f"{owner}/{name}",
            "environment": environment,
            "deployment_id": dep_data.get("id"),
        }
    return result


# ---------------------------------------------------------------------------
# Schema definitions
# ---------------------------------------------------------------------------

_CI_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ci_status",
        "description": (
            "Check CI pipeline status for a GitHub repo. Returns recent "
            "GitHub Actions workflow runs with status and conclusion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in 'owner/repo' format.",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to check (default: 'main').",
                },
            },
            "required": ["repo"],
        },
    },
}

_CI_TRIGGER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ci_trigger",
        "description": (
            "Trigger a CI workflow run via GitHub Actions workflow_dispatch. "
            "If workflow is not specified, lists available workflows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in 'owner/repo' format.",
                },
                "workflow": {
                    "type": "string",
                    "description": (
                        "Workflow ID (numeric) or filename (e.g. 'ci.yml'). "
                        "Omit to list available workflows."
                    ),
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to run against (default: 'main').",
                },
            },
            "required": ["repo"],
        },
    },
}

_CI_LOGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "ci_logs",
        "description": (
            "View CI build logs: jobs and step results for a workflow run. "
            "Returns the latest run if run_id is not specified."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in 'owner/repo' format.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Workflow run ID. Omit for latest run.",
                },
            },
            "required": ["repo"],
        },
    },
}

_DEPLOY_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "deploy_status",
        "description": (
            "Check deployment status for a GitHub repo via the Deployments API. "
            "Returns recent deployments with their statuses."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": ("Repository in 'owner/repo' format (alias for repo)."),
                },
            },
        },
    },
}

_DEPLOY_ROLLBACK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "deploy_rollback",
        "description": (
            "Rollback to a previous deployment version by creating a new "
            "deployment at the specified ref. If version is omitted, rolls "
            "back to the second-most-recent deployment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Repository in 'owner/repo' format.",
                },
                "version": {
                    "type": "string",
                    "description": (
                        "Git ref or SHA to roll back to. Omit to use the previous deployment's ref."
                    ),
                },
            },
            "required": ["service"],
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory — called by catalog.py
# ---------------------------------------------------------------------------


def ci_cd_tools(context: Any = None) -> list:
    """Return CI/CD tools. GitHub token from secrets.json provider:openai or
    github:default."""
    token = _get_token(context)

    def ci_status(repo: str = "", branch: str = "main") -> dict:
        """Check CI pipeline status (GitHub Actions workflow runs)"""
        return _ci_status(token, repo, branch)

    def ci_trigger(repo: str, workflow: str = "", branch: str = "main") -> dict:
        """Trigger a CI workflow run (requires approval)"""
        return _ci_trigger(token, repo, workflow, branch)

    def ci_logs(repo: str, run_id: str = "") -> dict:
        """View CI build logs (latest or specific run)"""
        return _ci_logs(token, repo, run_id)

    def deploy_status(service: str = "") -> dict:
        """Check deployment status"""
        return _deploy_status(token, service=service)

    def deploy_rollback(service: str, version: str = "") -> dict:
        """Rollback to previous version (requires approval)"""
        return _deploy_rollback(token, service=service, version=version)

    # Build tool list with metadata
    _read_meta = ai.ToolMetadata(
        category="ci_cd",
        risk_level="low",
        capabilities=["ci_cd"],
        requires_approval=False,
    )
    _write_meta = ai.ToolMetadata(
        category="ci_cd",
        risk_level="medium",
        capabilities=["ci_cd"],
        requires_approval=True,
    )

    tools: list[Callable[..., Any]] = []
    for fn, schema, meta in [
        (ci_status, _CI_STATUS_SCHEMA, _read_meta),
        (ci_trigger, _CI_TRIGGER_SCHEMA, _write_meta),
        (ci_logs, _CI_LOGS_SCHEMA, _read_meta),
        (deploy_status, _DEPLOY_STATUS_SCHEMA, _read_meta),
        (deploy_rollback, _DEPLOY_ROLLBACK_SCHEMA, _write_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        wrapped.__aisuite_tool_metadata__ = meta
        tools.append(wrapped)

    return tools
