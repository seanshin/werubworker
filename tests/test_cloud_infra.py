"""Cloud infrastructure tools tests — mock boto3/httpx."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from coworker.tools.cloud_infra import cloud_infra_tools, _parse_period
from coworker.secrets import SecretStore


def _make_context(secrets: SecretStore) -> SimpleNamespace:
    return SimpleNamespace(secrets=secrets)


def test_cloud_infra_tools_factory(tmp_path):
    """Factory returns the expected set of tools."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    assert len(tools) >= 7  # aws_ec2_list, aws_s3_list, aws_cloudwatch_metrics, aws_cost_explorer, cf_dns_list, cf_analytics, wasabi_list, ...
    names = {t.__name__ for t in tools}
    assert "aws_ec2_list" in names
    assert "aws_s3_list" in names
    assert "cf_dns_list" in names
    assert "wasabi_list" in names


def test_aws_ec2_list_no_credentials(tmp_path):
    """Without AWS credentials, should return an error."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    ec2_list = next(t for t in tools if t.__name__ == "aws_ec2_list")
    result = ec2_list()
    assert result["ok"] is False
    assert "not configured" in result["error"].lower() or "credentials" in result["error"].lower()


def test_cf_dns_list_no_token(tmp_path):
    """Without Cloudflare credentials, should return an error."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    cf_dns = next(t for t in tools if t.__name__ == "cf_dns_list")
    result = cf_dns()
    assert result["ok"] is False
    assert "not configured" in result["error"].lower() or "credentials" in result["error"].lower()


def test_wasabi_list_no_credentials(tmp_path):
    """Without Wasabi credentials, should return an error."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    wasabi = next(t for t in tools if t.__name__ == "wasabi_list")
    result = wasabi()
    assert result["ok"] is False
    assert "not configured" in result["error"].lower() or "credentials" in result["error"].lower()


def test_parse_period():
    from datetime import timedelta

    assert _parse_period("1h") == timedelta(hours=1)
    assert _parse_period("7d") == timedelta(days=7)
    assert _parse_period("30m") == timedelta(minutes=30)
    assert _parse_period("24") == timedelta(hours=24)
    assert _parse_period("bad") == timedelta(hours=1)  # fallback


def test_cf_dns_update_requires_approval(tmp_path):
    """The cf_dns_update tool should require approval."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    dns_update = next(t for t in tools if t.__name__ == "cf_dns_update")
    assert dns_update.__aisuite_tool_metadata__.requires_approval is True


def test_wasabi_upload_requires_approval(tmp_path):
    """The wasabi_upload tool should require approval."""
    secrets = SecretStore(tmp_path / "secrets.json")
    ctx = _make_context(secrets)
    tools = cloud_infra_tools(ctx)
    upload = next(t for t in tools if t.__name__ == "wasabi_upload")
    assert upload.__aisuite_tool_metadata__.requires_approval is True
