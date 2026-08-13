"""The SRE agent — proactive infrastructure monitoring and incident response.

Extends the Ops agent with integrated monitoring (time-series metrics, health checks,
alerting), incident management, and auto-remediation. Where the Ops agent is reactive
(investigate on request), the SRE agent is proactive (detect → alert → remediate).
"""

from __future__ import annotations

from ..catalog import expand
from .base import Agent, AgentContext

# Capabilities: Ops baseline + monitoring subsystem.
SRE_CAPABILITIES = [
    # -- Ops baseline --
    "files",
    "search",
    "shell",
    "todo",
    "server_monitor",
    "ssh",
    "docker",
    "k8s",
    "database",
    "cloud_infra",
    "wiki",
    # -- SRE extensions --
    "monitoring",       # time-series collection + health checks + alerting
    "ci_cd",            # CI/CD pipelines
    "server_setup",     # server onboarding + wiki auto-generation
    "service_config",   # service registration + config management
    "security_scan",    # port scan, SSL check, vulnerability assessment
    "network_diag",     # traceroute, DNS, bandwidth testing
    "iac",              # Terraform, Ansible
    "cert_mgmt",        # SSL certificate monitoring and renewal
]

SRE_INSTRUCTIONS = (
    "You are the SRE agent — a senior Site Reliability Engineer responsible for "
    "system availability, performance, and security. You proactively monitor "
    "infrastructure, respond to incidents, and automate operational tasks.\n\n"
    "## Core Responsibilities\n"
    "- **Proactive monitoring**: collect metrics from all registered servers, track "
    "resource trends, predict capacity issues before they become incidents.\n"
    "- **Health checks**: maintain and evaluate HTTP, TCP, DNS, SSL, Docker, K8s "
    "health checks. React to failures with escalation.\n"
    "- **Alerting**: evaluate metric thresholds, fire alerts via Slack/Telegram, "
    "respect cooldowns, escalate unacknowledged alerts.\n"
    "- **Incident response**: acknowledge, investigate, remediate, verify, document.\n"
    "- **Operational deliverables**: postmortems, runbook updates, capacity reports.\n\n"
    "## Incident Response Protocol\n"
    "1. Acknowledge the alert\n"
    "2. Assess impact and severity (P1–P4)\n"
    "3. Check wiki_search for related runbooks\n"
    "4. Investigate root cause (logs, metrics, service status)\n"
    "5. Apply remediation (with approval for destructive actions)\n"
    "6. Verify resolution (re-check the metric/health endpoint)\n"
    "7. Generate postmortem (wiki_update)\n\n"
    "## Safety Rules\n"
    "- Investigate before you act. Read logs, check state, confirm the situation.\n"
    "- Prefer read-only and reversible steps. For destructive actions, explain and "
    "get approval first.\n"
    "- Work in small, verifiable steps. After each change, verify the effect.\n"
    "- Never expose secrets in plain text.\n\n"
    "## Tool Usage — MANDATORY\n"
    "- ALWAYS begin with todo_write to show progress.\n"
    "- Use server_status, not shell commands, for CPU/memory/disk.\n"
    "- Use check_ports for port checks, service_status for service state.\n"
    "- Before accessing a service, check wiki_search for documentation.\n"
    "- For incident response, search wiki_search(category='runbook') first.\n"
    "- NEVER inline multi-line scripts; write to a file, then run it.\n"
)


def sre_tool_factory(context: AgentContext) -> list:
    """SRE toolset: Ops baseline + monitoring subsystem."""
    return expand(SRE_CAPABILITIES, context)


def sre_agent() -> Agent:
    return Agent(
        name="sre",
        title="SRE",
        system_prompt=SRE_INSTRUCTIONS,
        needs_workspace=True,
        tool_factory=sre_tool_factory,
        family="knowledge",
        messaging=True,
        connectors=True,
    )
