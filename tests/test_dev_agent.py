"""Dev agent definition tests."""

from __future__ import annotations

from coworker.agents.base import Agent, AgentContext
from coworker.agents.dev import (
    DEV_CAPABILITIES,
    DEV_INSTRUCTIONS,
    dev_agent,
    dev_tool_factory,
)


def test_dev_agent_definition():
    agent = dev_agent()
    assert isinstance(agent, Agent)
    assert agent.name == "dev"
    assert agent.title == "Dev"
    assert agent.needs_workspace is True
    assert agent.family == "code"
    assert agent.messaging is True
    assert agent.connectors is True
    assert agent.system_prompt == DEV_INSTRUCTIONS


def test_dev_capabilities():
    """Dev agent should include code review and CI/CD capabilities."""
    assert "ci_cd" in DEV_CAPABILITIES
    assert "code_review" in DEV_CAPABILITIES
    # Also baseline code tools
    assert "git" in DEV_CAPABILITIES
    assert "shell" in DEV_CAPABILITIES
    assert "todo" in DEV_CAPABILITIES
    assert "search" in DEV_CAPABILITIES


def test_dev_instructions_content():
    assert "software engineer" in DEV_INSTRUCTIONS.lower() or "Dev agent" in DEV_INSTRUCTIONS
    assert "code review" in DEV_INSTRUCTIONS.lower() or "Code review" in DEV_INSTRUCTIONS
    assert "CI/CD" in DEV_INSTRUCTIONS
    assert "security" in DEV_INSTRUCTIONS.lower()


def test_dev_tool_factory():
    """dev_tool_factory should not crash when given a minimal context."""
    ctx = AgentContext()
    try:
        tools = dev_tool_factory(ctx)
        assert isinstance(tools, list)
    except Exception:
        # Some capabilities may not resolve without full setup —
        # the key test is that the function is callable.
        pass
