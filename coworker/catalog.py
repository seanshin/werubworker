"""Vetted tool catalog — the stable ``id → capability`` layer a persona references.

A *capability* bundles a group of tools (the existing ``tools/`` factories) behind a stable
id, plus what session context it needs (``requires``) and the risk classes it can produce
(``risk``, used by the Phase 2 install-consent screen). ``expand(ids, context)`` turns a
persona's ``tools:`` list into concrete callables, skipping capabilities whose context
prerequisites aren't met (e.g. no shell without an executor) — matching the per-agent
factories that used to assemble tools by hand.

The catalog is **platform-owned and closed**: third parties get breadth from us adding
vetted capabilities here and from MCP, never by adding entries. MCP tools are *not* in the
catalog (see ``PERMISSIONS-AND-INBOX.md``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import aisuite as ai

from .agents.base import AgentContext
from .risk import RiskClass
from .tools.ci_cd import ci_cd_tools
from .tools.code_review import code_review_tools
from .tools.files import file_tools
from .tools.git import git_tools
from .tools.search import search_tools
from .tools.cloud_infra import cloud_infra_tools
from .tools.db_mgmt import db_tools
from .tools.docker_mgmt import docker_tools
from .tools.k8s_mgmt import k8s_tools
from .tools.server_monitor import server_monitor_tools
from .tools.shell import shell_tools
from .tools.todo import todo_tools
from .wiki.tools import wiki_tools

# Context prerequisites a capability may require, mapped to a predicate over AgentContext.
_REQUIREMENTS: dict[str, Callable[[AgentContext], bool]] = {
    "workspace": lambda c: c.workspace is not None,
    "executor": lambda c: c.executor is not None,
    "todo": lambda c: c.todo is not None,
    "secrets": lambda c: c.secrets is not None,
}


@dataclass(frozen=True)
class Capability:
    id: str
    name: str  # human label (consent screen)
    description: str
    build: Callable[[AgentContext], list]
    requires: tuple[str, ...] = ()
    risk: tuple[RiskClass, ...] = (RiskClass.READ,)

    def available(self, context: AgentContext) -> bool:
        return all(_REQUIREMENTS[r](context) for r in self.requires)


# -- capability builders --------------------------------------------------------
# These reproduce, exactly, what the Code and Cowork agent factories assembled by hand.


def _code_files(context: AgentContext) -> list:
    """Repo-oriented files: single-root, line-numbered/windowed `read_file`. Our `grep` and
    windowed `read_file` replace aisuite's slower `search_files` / `read_file`/`read_file_lines`.
    """
    ws = str(context.workspace)
    replaced = {"search_files", "read_file", "read_file_lines"}
    files = [
        t
        for t in ai.toolkits.files(root=ws, allow_write=True)
        if getattr(t, "__name__", "") not in replaced
    ]
    return [*files, *file_tools(ws)]


def _files(context: AgentContext) -> list:
    """Knowledge-work files: multi-root aware (reads/writes across the session's roots), keeps
    aisuite's `read_file`/`read_file_lines`. Only our `grep` replaces the slow `search_files`.
    """
    ws = str(context.workspace)
    file_kwargs = (
        {"roots": context.roots} if context.roots else {"root": ws, "allow_write": True}
    )
    return [
        t
        for t in ai.toolkits.files(**file_kwargs)
        if getattr(t, "__name__", "") != "search_files"
    ]


def _git(context: AgentContext) -> list:
    ws = str(context.workspace)
    return [*ai.toolkits.git(root=ws), *git_tools(ws)]  # git_status, git_diff, git_log


def _search(context: AgentContext) -> list:
    return search_tools(str(context.workspace))  # grep (ripgrep, .gitignore-aware)


def _shell(context: AgentContext) -> list:
    return shell_tools(context.executor)  # run_shell + background task tools


def _todo(context: AgentContext) -> list:
    return todo_tools(context.todo)  # todo_write (drives the Progress panel)


def _server_monitor(context: AgentContext) -> list:
    return server_monitor_tools(context)  # server_status, service_status, check_ports, …


def _ci_cd(context: AgentContext) -> list:
    return ci_cd_tools(context)  # ci_status, ci_trigger, ci_logs, deploy_status, deploy_rollback


def _cloud_infra(context: AgentContext) -> list:
    return cloud_infra_tools(context)  # aws_ec2_list, cf_dns_list, wasabi_list, …


def _database(context: AgentContext) -> list:
    return db_tools(context)  # db_query, db_status, db_tables, db_backup


def _docker(context: AgentContext) -> list:
    return docker_tools(context)  # docker_ps, docker_logs, docker_restart, ...


def _k8s(context: AgentContext) -> list:
    return k8s_tools(context)  # k8s_pods, k8s_logs, k8s_describe, k8s_restart, k8s_scale, k8s_events


def _wiki(context: AgentContext) -> list:
    return wiki_tools(context)  # wiki_search, wiki_get, wiki_get_credential, wiki_update, wiki_check_alerts


def _code_review(context: AgentContext) -> list:
    return code_review_tools(context)  # review_pr, review_security, review_test_coverage


def _ssh(context: AgentContext) -> list:
    from .connectors.ssh import ssh_tools

    return ssh_tools(context.secrets)  # remote server access via system ssh


_CAPS: list[Capability] = [
    Capability(
        id="code_files",
        name="Code files",
        description="Read & edit files in a single repo workspace (line-numbered reads).",
        build=_code_files,
        requires=("workspace",),
        risk=(RiskClass.READ, RiskClass.WRITE_LOCAL),
    ),
    Capability(
        id="files",
        name="Files",
        description="Read & edit files across the session's workspace folders.",
        build=_files,
        requires=("workspace",),
        risk=(RiskClass.READ, RiskClass.WRITE_LOCAL),
    ),
    Capability(
        id="git",
        name="Git",
        description="Inspect git state and history (status, diff, log).",
        build=_git,
        requires=("workspace",),
        risk=(RiskClass.READ,),
    ),
    Capability(
        id="search",
        name="Search",
        description="Fast code/content search (grep).",
        build=_search,
        requires=("workspace",),
        risk=(RiskClass.READ,),
    ),
    Capability(
        id="shell",
        name="Shell",
        description="Run shell commands in a persistent session.",
        build=_shell,
        requires=("executor",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="todo",
        name="Task list",
        description="Maintain a visible task/progress list.",
        build=_todo,
        requires=("todo",),
        risk=(RiskClass.READ,),
    ),
    Capability(
        id="server_monitor",
        name="Server monitoring",
        description="Check server health, resource usage, service status, and logs.",
        build=_server_monitor,
        requires=(),
        risk=(RiskClass.READ,),
    ),
    Capability(
        id="ci_cd",
        name="CI/CD pipelines",
        description="GitHub Actions CI/CD: check status, trigger workflows, view logs, deploy, and rollback.",
        build=_ci_cd,
        requires=(),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="cloud_infra",
        name="Cloud infrastructure",
        description="AWS, Cloudflare, and Wasabi cloud infrastructure management.",
        build=_cloud_infra,
        requires=("secrets",),
        risk=(RiskClass.READ, RiskClass.EXTERNAL),
    ),
    Capability(
        id="database",
        name="Database management",
        description="Query, inspect, and back up configured databases (PostgreSQL, MySQL, SQLite).",
        build=_database,
        requires=("secrets",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="code_review",
        name="Code review",
        description="Analyze PRs, scan for security issues, and inspect test coverage.",
        build=_code_review,
        requires=(),
        risk=(RiskClass.READ,),
    ),
    Capability(
        id="docker",
        name="Docker management",
        description="Manage Docker containers, images, and compose services (local or remote).",
        build=_docker,
        requires=(),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="k8s",
        name="Kubernetes management",
        description="Manage Kubernetes clusters: pods, logs, deployments, scaling, and events via kubectl.",
        build=_k8s,
        requires=(),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="ssh",
        name="SSH remote access",
        description="Execute commands on registered remote servers via SSH.",
        build=_ssh,
        requires=("secrets",),
        risk=(RiskClass.EXEC,),
    ),
    Capability(
        id="wiki",
        name="Service Wiki",
        description="Search and manage service documentation and credentials.",
        build=_wiki,
        requires=("secrets",),
        risk=(RiskClass.READ,),
    ),
]

CATALOG: dict[str, Capability] = {c.id: c for c in _CAPS}


def capability(cap_id: str) -> Capability:
    cap = CATALOG.get(cap_id)
    if cap is None:
        raise KeyError(f"Unknown capability id: {cap_id!r}")
    return cap


def expand(ids: list[str], context: AgentContext) -> list:
    """Expand a persona's ``tools:`` id list into concrete tool callables for this context.
    Capabilities whose context prerequisites aren't met are skipped (no shell without an
    executor, no files without a workspace) — exactly like the old hand-written factories.
    """
    tools: list = []
    for cap_id in ids:
        cap = capability(cap_id)
        if cap.available(context):
            tools.extend(cap.build(context))
    return tools


def risk_summary(ids: list[str]) -> set[RiskClass]:
    """The union of risk classes a tool list can produce — for the install-consent screen."""
    out: set[RiskClass] = set()
    for cap_id in ids:
        out.update(capability(cap_id).risk)
    return out
