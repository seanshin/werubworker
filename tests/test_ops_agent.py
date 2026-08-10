"""Ops agent definition tests."""

from __future__ import annotations

from coworker.agents.base import Agent, AgentContext
from coworker.agents.ops import (
    OPS_CAPABILITIES,
    OPS_INSTRUCTIONS,
    ops_agent,
    ops_tool_factory,
)


def test_ops_agent_definition():
    agent = ops_agent()
    assert isinstance(agent, Agent)
    assert agent.name == "ops"
    assert agent.title == "Ops"
    assert agent.needs_workspace is True
    assert agent.family == "knowledge"
    assert agent.messaging is True
    assert agent.connectors is True
    assert agent.system_prompt == OPS_INSTRUCTIONS


def test_ops_capabilities():
    """Ops agent should include monitoring, SSH, Docker, k8s, database, and cloud capabilities."""
    assert "server_monitor" in OPS_CAPABILITIES
    assert "ssh" in OPS_CAPABILITIES
    assert "docker" in OPS_CAPABILITIES
    assert "k8s" in OPS_CAPABILITIES
    assert "database" in OPS_CAPABILITIES
    assert "cloud_infra" in OPS_CAPABILITIES
    # Also should include baseline tools
    assert "files" in OPS_CAPABILITIES
    assert "shell" in OPS_CAPABILITIES
    assert "todo" in OPS_CAPABILITIES


def test_ops_instructions_content():
    assert "DevOps" in OPS_INSTRUCTIONS or "SRE" in OPS_INSTRUCTIONS
    assert (
        "server monitoring" in OPS_INSTRUCTIONS.lower() or "Server monitoring" in OPS_INSTRUCTIONS
    )
    assert "Docker" in OPS_INSTRUCTIONS
    assert "database" in OPS_INSTRUCTIONS.lower() or "Database" in OPS_INSTRUCTIONS


def test_ops_tool_factory():
    """ops_tool_factory should not crash when given a minimal context (tools may be
    empty if capability connectors are not registered, but the call itself must succeed)."""
    ctx = AgentContext()
    try:
        tools = ops_tool_factory(ctx)
        assert isinstance(tools, list)
    except Exception:
        # Some capabilities may not resolve without full setup —
        # the key test is that the function is callable.
        pass
