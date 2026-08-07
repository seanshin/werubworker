"""CI/CD pipeline tools tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from coworker.tools.ci_cd import (
    ci_cd_tools,
    _ci_status,
    _ci_trigger,
    _parse_owner_repo,
    _get_token,
)
from coworker.secrets import SecretStore


def test_ci_cd_tools_factory():
    """Factory returns 5 tools."""
    tools = ci_cd_tools()
    assert len(tools) == 5
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert names == {"ci_status", "ci_trigger", "ci_logs", "deploy_status", "deploy_rollback"}


def test_ci_status_no_token(monkeypatch):
    """ci_status should still work (public repos) but return error for private ones."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # No repo means error
    result = _ci_status(None, repo="")
    assert result["ok"] is False
    assert "required" in result["error"].lower()


def test_ci_status_bad_repo():
    """A repo without owner/name format should error."""
    result = _ci_status(None, repo="just-a-name")
    assert result["ok"] is False
    assert "owner/repo" in result["error"]


def test_ci_trigger_requires_repo():
    result = _ci_trigger(None, repo="")
    assert result["ok"] is False
    assert "required" in result["error"].lower()


def test_ci_trigger_requires_owner_slash_repo():
    result = _ci_trigger(None, repo="noslash")
    assert result["ok"] is False


def test_parse_owner_repo():
    assert _parse_owner_repo("owner/repo") == ("owner", "repo")
    assert _parse_owner_repo("https://github.com/owner/repo") == ("owner", "repo")
    assert _parse_owner_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert _parse_owner_repo("just-repo") == ("", "just-repo")


def test_get_token_from_secrets(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("github:default", {"token": "ghp_test_token_123"})
    ctx = SimpleNamespace(secrets=secrets)
    token = _get_token(ctx)
    assert token == "ghp_test_token_123"


def test_get_token_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token_456")
    token = _get_token(None)
    assert token == "ghp_env_token_456"


def test_ci_trigger_requires_approval():
    """ci_trigger should require approval (write operation)."""
    tools = ci_cd_tools()
    trigger = next(t for t in tools if t.__coworker_schema__["function"]["name"] == "ci_trigger")
    assert trigger.__aisuite_tool_metadata__.requires_approval is True


def test_deploy_rollback_requires_approval():
    tools = ci_cd_tools()
    rollback = next(t for t in tools if t.__coworker_schema__["function"]["name"] == "deploy_rollback")
    assert rollback.__aisuite_tool_metadata__.requires_approval is True
