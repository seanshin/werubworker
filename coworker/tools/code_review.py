"""Code review tools — PR analysis, security scanning, test coverage inspection.

Read-only tools that help with code review workflows: fetching and summarising GitHub
pull requests, scanning for common security anti-patterns (hardcoded secrets, SQL
injection), and inspecting test coverage.

The ``review_pr`` tool uses the GitHub REST API (via httpx) with a token read from the
secret store (``github:default.token``).  The security and coverage tools work locally
via subprocess and pattern matching — no external services required.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

import aisuite as ai

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], timeout: int = 30, cwd: str | None = None) -> str:
    """Run a command and return its stdout (best-effort, never raises)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.stdout.strip()
    except Exception:
        return ""


def _github_token(context: Any = None) -> Optional[str]:
    """Resolve a GitHub token from the agent context's secret store."""
    if context is None:
        return os.environ.get("GITHUB_TOKEN")
    secrets = getattr(context, "secrets", None)
    if secrets is None:
        return os.environ.get("GITHUB_TOKEN")
    profile = secrets.get("github:default") or {}
    return profile.get("token") or os.environ.get("GITHUB_TOKEN")


def _github_api(token: str, method: str, url: str, *, params: dict | None = None) -> dict[str, Any]:
    """Call the GitHub REST API via httpx."""
    try:
        import httpx
    except ImportError:
        return {"error": "httpx is not installed"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.request(method, url, headers=headers, params=params)
            ctype = resp.headers.get("content-type", "")
            data: Any = resp.json() if "json" in ctype.lower() else resp.text
            if resp.status_code >= 400:
                return {"error": f"HTTP {resp.status_code}", "details": data}
            return {"ok": True, "data": data}
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_GITHUB_API = "https://api.github.com"


def _review_pr(token: str, repo: str, pr_number: int) -> dict[str, Any]:
    """Fetch PR metadata and changed files, produce a review summary."""
    # Validate inputs
    if "/" not in repo:
        return {"error": "repo must be in 'owner/repo' format"}

    # Fetch PR details
    pr_resp = _github_api(token, "GET", f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}")
    if "error" in pr_resp:
        return pr_resp

    pr = pr_resp["data"]

    # Fetch changed files
    files_resp = _github_api(
        token,
        "GET",
        f"{_GITHUB_API}/repos/{repo}/pulls/{pr_number}/files",
        params={"per_page": 100},
    )
    if "error" in files_resp:
        return {"pr": pr.get("title"), "error_files": files_resp["error"]}

    files_data = files_resp["data"]

    # Summarise
    changed_files = []
    total_additions = 0
    total_deletions = 0
    for f in files_data:
        changed_files.append(
            {
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch_preview": (f.get("patch") or "")[:500],
            }
        )
        total_additions += f.get("additions", 0)
        total_deletions += f.get("deletions", 0)

    # Build review suggestions
    suggestions = []
    large_files = [f for f in changed_files if (f["additions"] + f["deletions"]) > 300]
    if large_files:
        suggestions.append(
            f"{len(large_files)} file(s) have large diffs (>300 lines) — consider splitting."
        )
    if total_additions + total_deletions > 1000:
        suggestions.append(
            "PR is very large — consider breaking into smaller PRs for easier review."
        )
    test_files = [f for f in changed_files if "test" in f["filename"].lower()]
    src_files = [f for f in changed_files if "test" not in f["filename"].lower()]
    if src_files and not test_files:
        suggestions.append(
            "No test files modified — consider adding test coverage for the changes."
        )

    return {
        "title": pr.get("title"),
        "state": pr.get("state"),
        "author": (pr.get("user") or {}).get("login"),
        "base": (pr.get("base") or {}).get("ref"),
        "head": (pr.get("head") or {}).get("ref"),
        "body_preview": (pr.get("body") or "")[:500],
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "files_changed": len(changed_files),
        "changed_files": changed_files,
        "suggestions": suggestions,
    }


def _review_security(path: str = ".") -> dict[str, Any]:
    """Scan code for common security issues using pattern matching."""
    root = Path(path).resolve()
    if not root.is_dir():
        return {"error": f"path is not a directory: {root}"}

    findings: list[dict[str, Any]] = []

    # Patterns to scan for
    secret_patterns = [
        (
            r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
            "Possible hardcoded API key",
        ),
        (
            r"(?i)(secret|password|passwd|pwd)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
            "Possible hardcoded secret/password",
        ),
        (
            r"(?i)(aws_access_key_id|aws_secret_access_key)\s*[:=]\s*['\"][A-Za-z0-9/+=]{16,}['\"]",
            "Possible AWS credential",
        ),
        (r"AKIA[0-9A-Z]{16}", "Possible AWS Access Key ID"),
        (r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}", "Possible hardcoded Bearer token"),
        (r"ghp_[A-Za-z0-9]{36}", "Possible GitHub personal access token"),
        (r"sk-[A-Za-z0-9]{20,}", "Possible secret key (OpenAI/Stripe style)"),
    ]

    sql_patterns = [
        (
            r"""(?i)(?:execute|cursor\.execute|query)\s*\(\s*(?:f['\"]|['\"].*%s|['\"].*\+\s*\w)""",
            "Possible SQL injection (string interpolation in query)",
        ),
        (
            r"(?i)(?:SELECT|INSERT|UPDATE|DELETE).*\+\s*(?:request|params|input|args)",
            "Possible SQL injection (concatenation with user input)",
        ),
    ]

    # File extensions to scan
    code_exts = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".go",
        ".rb",
        ".php",
        ".rs",
        ".yml",
        ".yaml",
        ".json",
        ".env",
        ".cfg",
        ".ini",
        ".conf",
    }

    scanned = 0
    max_files = 2000

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip common non-source dirs
        dirnames[:] = [
            d
            for d in dirnames
            if d
            not in {
                "node_modules",
                ".git",
                "__pycache__",
                ".venv",
                "venv",
                "dist",
                "build",
                ".tox",
                ".mypy_cache",
            }
        ]
        for fname in filenames:
            if scanned >= max_files:
                break
            fpath = Path(dirpath) / fname
            if fpath.suffix not in code_exts:
                continue
            scanned += 1
            try:
                content = fpath.read_text(errors="replace")
            except Exception:
                continue

            rel = str(fpath.relative_to(root))

            for pattern, desc in secret_patterns:
                for m in re.finditer(pattern, content):
                    line_no = content[: m.start()].count("\n") + 1
                    findings.append(
                        {
                            "file": rel,
                            "line": line_no,
                            "type": "secret",
                            "description": desc,
                            "match_preview": m.group(0)[:60] + "..."
                            if len(m.group(0)) > 60
                            else m.group(0),
                        }
                    )

            for pattern, desc in sql_patterns:
                for m in re.finditer(pattern, content):
                    line_no = content[: m.start()].count("\n") + 1
                    findings.append(
                        {
                            "file": rel,
                            "line": line_no,
                            "type": "sql_injection",
                            "description": desc,
                        }
                    )

    # Check for dependency vulnerabilities
    dep_audit: dict[str, Any] = {}
    if (root / "package.json").exists():
        out = _run(["npm", "audit", "--json"], timeout=30, cwd=str(root))
        if out:
            try:
                audit = __import__("json").loads(out)
                vuln_count = audit.get("metadata", {}).get("vulnerabilities", {})
                dep_audit["npm"] = vuln_count if vuln_count else "clean"
            except Exception:
                dep_audit["npm"] = "audit output could not be parsed"

    if (root / "requirements.txt").exists() or (root / "pyproject.toml").exists():
        out = _run(["pip", "audit", "--format", "json"], timeout=30, cwd=str(root))
        if out:
            try:
                audit = __import__("json").loads(out)
                dep_audit["pip"] = {"vulnerabilities": len(audit)} if audit else "clean"
            except Exception:
                dep_audit["pip"] = out[:500] if out else "pip-audit not available"

    return {
        "path": str(root),
        "files_scanned": scanned,
        "findings_count": len(findings),
        "findings": findings[:100],  # Cap output
        "dependency_audit": dep_audit or "no package manifests found",
    }


def _review_test_coverage(path: str = ".") -> dict[str, Any]:
    """Analyse test coverage: find test files, parse coverage reports, identify untested files."""
    root = Path(path).resolve()
    if not root.is_dir():
        return {"error": f"path is not a directory: {root}"}

    # Find test files
    test_files: list[str] = []
    source_files: list[str] = []
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d
            not in {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".tox"}
        ]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix not in code_exts:
                continue
            rel = str(fpath.relative_to(root))
            name_lower = fname.lower()
            is_test = (
                name_lower.startswith("test_")
                or name_lower.endswith("_test" + fpath.suffix)
                or name_lower.endswith(".test" + fpath.suffix)
                or name_lower.endswith(".spec" + fpath.suffix)
                or "/tests/" in rel.replace("\\", "/")
                or "/__tests__/" in rel.replace("\\", "/")
            )
            if is_test:
                test_files.append(rel)
            else:
                source_files.append(rel)

    # Parse coverage reports if they exist
    coverage_data: dict[str, Any] = {}

    # Python coverage.py JSON report
    cov_json = root / "coverage.json"
    if cov_json.exists():
        try:
            import json as _json

            raw = _json.loads(cov_json.read_text())
            totals = raw.get("totals", {})
            coverage_data["python_coverage"] = {
                "total_percent": totals.get("percent_covered"),
                "covered_lines": totals.get("covered_lines"),
                "missing_lines": totals.get("missing_lines"),
            }
        except Exception:
            pass

    # Python .coverage (XML)
    cov_xml = root / "coverage.xml"
    if cov_xml.exists():
        try:
            import xml.etree.ElementTree as ET

            tree = ET.parse(str(cov_xml))
            cov_root = tree.getroot()
            line_rate = cov_root.get("line-rate")
            if line_rate:
                coverage_data["cobertura_xml"] = {
                    "line_rate": float(line_rate),
                    "percent": round(float(line_rate) * 100, 1),
                }
        except Exception:
            pass

    # lcov.info (JS/TS)
    lcov = root / "coverage" / "lcov.info"
    if lcov.exists():
        try:
            content = lcov.read_text()
            lf = sum(int(m.group(1)) for m in re.finditer(r"LF:(\d+)", content))
            lh = sum(int(m.group(1)) for m in re.finditer(r"LH:(\d+)", content))
            if lf > 0:
                coverage_data["lcov"] = {
                    "lines_found": lf,
                    "lines_hit": lh,
                    "percent": round(lh / lf * 100, 1),
                }
        except Exception:
            pass

    # Identify source files without corresponding tests
    test_basenames = set()
    for tf in test_files:
        base = Path(tf).stem.lower()
        for prefix in ("test_", "test"):
            if base.startswith(prefix):
                base = base[len(prefix) :]
                break
        for suffix in ("_test", "_spec", ".test", ".spec"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
                break
        test_basenames.add(base)

    untested = []
    for sf in source_files:
        base = Path(sf).stem.lower()
        if base not in test_basenames and base not in {"__init__", "setup", "conftest", "index"}:
            untested.append(sf)

    return {
        "path": str(root),
        "test_files": test_files,
        "test_file_count": len(test_files),
        "source_file_count": len(source_files),
        "coverage_reports": coverage_data or "no coverage reports found",
        "potentially_untested_files": untested[:100],
        "untested_count": len(untested),
    }


# ---------------------------------------------------------------------------
# Schema definitions (aisuite tool format)
# ---------------------------------------------------------------------------

_REVIEW_PR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "review_pr",
        "description": (
            "Analyze a GitHub pull request: fetch changed files, diff summary, and "
            "generate review suggestions. Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in 'owner/repo' format (e.g. 'octocat/Hello-World').",
                },
                "pr_number": {
                    "type": "integer",
                    "description": "Pull request number.",
                },
            },
            "required": ["repo", "pr_number"],
        },
    },
}

_REVIEW_SECURITY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "review_security",
        "description": (
            "Scan code for common security issues: hardcoded secrets (API keys, passwords), "
            "SQL injection patterns, and dependency vulnerabilities (npm audit / pip audit). "
            "Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to scan (default: current working directory '.').",
                },
            },
        },
    },
}

_REVIEW_TEST_COVERAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "review_test_coverage",
        "description": (
            "Analyze test coverage: find test files, parse coverage reports (coverage.py, "
            "lcov, cobertura XML), and identify source files without corresponding tests. "
            "Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to analyze (default: current working directory '.').",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory — called by catalog.py
# ---------------------------------------------------------------------------


def code_review_tools(context: Any = None) -> list:
    """Return the code review toolset: review_pr, review_security, review_test_coverage.
    All read-only, no approval required."""

    token_holder: dict[str, Optional[str]] = {"token": _github_token(context)}

    def review_pr(repo: str, pr_number: int) -> dict:
        """Analyze a GitHub PR: changed files, diff summary, review suggestions."""
        t = token_holder["token"]
        if not t:
            return {
                "error": "GitHub token not configured (set github:default.token in secrets or GITHUB_TOKEN env var)"
            }
        return _review_pr(t, repo, pr_number)

    def review_security(path: str = ".") -> dict:
        """Scan code for common security issues: hardcoded secrets, SQL injection, dependency vulnerabilities."""
        return _review_security(path)

    def review_test_coverage(path: str = ".") -> dict:
        """Analyze test coverage: find test files, check coverage reports, identify untested files."""
        return _review_test_coverage(path)

    _meta = ai.ToolMetadata(
        category="code_review",
        risk_level="low",
        capabilities=["review"],
        requires_approval=False,
    )

    tools = []
    for fn, schema in [
        (review_pr, _REVIEW_PR_SCHEMA),
        (review_security, _REVIEW_SECURITY_SCHEMA),
        (review_test_coverage, _REVIEW_TEST_COVERAGE_SCHEMA),
    ]:
        wrapped = ai.tool(fn, metadata=_meta)
        wrapped.__coworker_schema__ = schema
        tools.append(wrapped)

    return tools
