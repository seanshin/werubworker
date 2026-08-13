"""Development environment setup tools — project scanning, Git integration."""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable

import aisuite as ai


# ---------------------------------------------------------------------------
# Schema helpers (mirrors cloud_infra.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="dev_setup",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["development"],
        requires_approval=approval,
    )


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _attach(
    fn: Callable[..., Any],
    schema: dict[str, Any],
    *,
    approval: bool = False,
    caps: list[str] | None = None,
) -> Callable[..., Any]:
    name = schema["function"]["name"]
    fn.__coworker_schema__ = schema
    fn.__aisuite_tool_metadata__ = _meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = schema["function"]["description"]
    fn.__name__ = name
    return fn


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def dev_setup_tools(context: Any = None) -> list:
    secrets = getattr(context, "secrets", None)
    wiki_store = getattr(context, "wiki_store", None)
    if not secrets or not wiki_store:
        return []

    tools: list[Callable[..., Any]] = []

    # 1. scan_project: 프로젝트 디렉토리 스캔
    def scan_project(path: str) -> dict:
        """Scan a project directory to detect language, framework, CI, and tools."""
        if not os.path.isdir(path):
            return {"ok": False, "error": f"directory not found: {path}"}

        files = set(os.listdir(path))
        result = {
            "path": path,
            "language": _detect_language(files, path),
            "framework": _detect_framework(files, path),
            "package_manager": _detect_package_manager(files),
            "build_tool": _detect_build_tool(files),
            "ci_config": _detect_ci(files),
            "has_docker": "Dockerfile" in files or "docker-compose.yml" in files,
            "has_tests": any(f.startswith("test") or f == "tests" for f in files),
            "env_files": [f for f in files if f.startswith(".env")],
        }
        return {"ok": True, "project": result}

    _attach(
        scan_project,
        _schema(
            "scan_project",
            "Scan a project directory to detect language, framework, CI, and tools.",
            {
                "path": {"type": "string", "description": "Project directory path to scan"},
            },
            ["path"],
        ),
        approval=False,
        caps=["development"],
    )
    tools.append(scan_project)

    # 2. create_dev_wiki: 프로젝트 Wiki 문서 생성
    def create_dev_wiki(
        project_name: str,
        repo_url: str = "",
        description: str = "",
        scan_path: str = "",
    ) -> dict:
        """Create a development environment Wiki page, optionally from a project scan."""
        scan = {}
        if scan_path:
            scan_result = scan_project(scan_path)
            if scan_result.get("ok"):
                scan = scan_result.get("project", {})

        content = f"# 프로젝트: {project_name}\n\n"
        if description:
            content += f"## 개요\n{description}\n\n"
        if repo_url:
            content += f"## 저장소\n- **URL**: {repo_url}\n\n"
        if scan:
            content += "## 기술 스택\n"
            content += f"- **언어**: {scan.get('language', '?')}\n"
            content += f"- **프레임워크**: {scan.get('framework', '?')}\n"
            content += f"- **패키지 매니저**: {scan.get('package_manager', '?')}\n"
            content += f"- **CI**: {scan.get('ci_config', '?')}\n\n"
        content += "## 개발 환경 설정\n\n## 배포\n\n## 메모\n"

        page_id = f"dev-{project_name.lower().replace(' ', '-')[:30]}"
        return wiki_store.create_page(
            page_id=page_id,
            name=f"개발 환경: {project_name}",
            category="development",
            content=content,
            tags=["development", scan.get("language", "")],
            updated_by="agent",
            structured_data={
                "repo_url": repo_url,
                "language": scan.get("language", ""),
                "framework": scan.get("framework", ""),
                "ci": scan.get("ci_config", ""),
            },
        )

    _attach(
        create_dev_wiki,
        _schema(
            "create_dev_wiki",
            "Create a development environment Wiki page, optionally from a project scan.",
            {
                "project_name": {"type": "string", "description": "Project name"},
                "repo_url": {"type": "string", "description": "Git repository URL"},
                "description": {"type": "string", "description": "Project description"},
                "scan_path": {
                    "type": "string",
                    "description": "Path to scan for auto-detection",
                },
            },
            ["project_name"],
        ),
        approval=True,
        caps=["development", "wiki"],
    )
    tools.append(create_dev_wiki)

    # 3. setup_git_integration: Git 연동 설정
    def setup_git_integration(
        project_name: str,
        platform: str,
        repo: str,
        token_key: str = "",
    ) -> dict:
        """Configure Git platform integration (GitHub/Gitea/GitLab)."""
        if platform not in ("github", "gitea", "gitlab"):
            return {"ok": False, "error": f"unsupported platform: {platform}"}
        profile = {"platform": platform, "repo": repo}
        if token_key:
            profile["token_ref"] = token_key
        secrets.put(f"git:{platform}:{project_name}", profile)

        page_id = f"dev-{project_name.lower().replace(' ', '-')[:30]}"
        wiki_store.update_page(
            page_id,
            change_note=f"{platform} 저장소 연동: {repo}",
            updated_by="agent",
        )
        return {"ok": True, "platform": platform, "repo": repo}

    _attach(
        setup_git_integration,
        _schema(
            "setup_git_integration",
            "Configure Git platform integration (GitHub/Gitea/GitLab).",
            {
                "project_name": {"type": "string", "description": "Project name"},
                "platform": {
                    "type": "string",
                    "enum": ["github", "gitea", "gitlab"],
                    "description": "Git platform",
                },
                "repo": {
                    "type": "string",
                    "description": "Repository identifier (e.g. owner/repo)",
                },
                "token_key": {
                    "type": "string",
                    "description": "Secret key for access token",
                },
            },
            ["project_name", "platform", "repo"],
        ),
        approval=True,
        caps=["development", "git"],
    )
    tools.append(setup_git_integration)

    return tools


# ---------------------------------------------------------------------------
# Helpers (project scanning)
# ---------------------------------------------------------------------------


def _detect_language(files: set, path: str) -> str:
    if "pyproject.toml" in files or "setup.py" in files or "requirements.txt" in files:
        return "Python"
    if "package.json" in files:
        return "JavaScript/TypeScript" if "tsconfig.json" in files else "JavaScript"
    if "go.mod" in files:
        return "Go"
    if "Cargo.toml" in files:
        return "Rust"
    if "pom.xml" in files or "build.gradle" in files:
        return "Java"
    return "unknown"


def _detect_framework(files: set, path: str) -> str:
    # Python
    if "pyproject.toml" in files:
        try:
            content = open(os.path.join(path, "pyproject.toml")).read(2000)
            if "fastapi" in content.lower():
                return "FastAPI"
            if "django" in content.lower():
                return "Django"
            if "flask" in content.lower():
                return "Flask"
        except Exception:
            pass
    # JS
    if "package.json" in files:
        try:
            content = open(os.path.join(path, "package.json")).read(2000)
            if "next" in content:
                return "Next.js"
            if "react" in content:
                return "React"
            if "vue" in content:
                return "Vue"
            if "express" in content:
                return "Express"
        except Exception:
            pass
    return "unknown"


def _detect_package_manager(files: set) -> str:
    if "poetry.lock" in files:
        return "poetry"
    if "Pipfile.lock" in files:
        return "pipenv"
    if "uv.lock" in files:
        return "uv"
    if "requirements.txt" in files:
        return "pip"
    if "yarn.lock" in files:
        return "yarn"
    if "pnpm-lock.yaml" in files:
        return "pnpm"
    if "package-lock.json" in files:
        return "npm"
    if "go.sum" in files:
        return "go modules"
    return "unknown"


def _detect_build_tool(files: set) -> str:
    if "Makefile" in files:
        return "make"
    if "build.gradle" in files:
        return "gradle"
    if "CMakeLists.txt" in files:
        return "cmake"
    return ""


def _detect_ci(files: set) -> str:
    if ".github" in files:
        return "GitHub Actions"
    if ".gitlab-ci.yml" in files:
        return "GitLab CI"
    if "Jenkinsfile" in files:
        return "Jenkins"
    if ".circleci" in files:
        return "CircleCI"
    return ""
