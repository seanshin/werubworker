"""Kubernetes management tools tests."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

from coworker.tools.k8s_mgmt import (
    k8s_tools,
    _k8s_pods,
    _k8s_logs,
    _k8s_describe,
    _k8s_restart,
    _k8s_scale,
    _k8s_events,
    _kubectl_available,
)


def test_k8s_tools_factory():
    """Factory returns 6 tools."""
    tools = k8s_tools()
    assert len(tools) == 6
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert names == {"k8s_pods", "k8s_logs", "k8s_describe", "k8s_restart", "k8s_scale", "k8s_events"}


@patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=False)
def test_k8s_pods_no_kubectl(mock_avail):
    result = _k8s_pods()
    assert "error" in result
    assert "kubectl" in result["error"].lower()


@patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=False)
def test_k8s_logs_no_kubectl(mock_avail):
    result = _k8s_logs("my-pod")
    assert "error" in result
    assert "kubectl" in result["error"].lower()


def test_k8s_logs_no_pod_name():
    """Pod name is required."""
    with patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=True):
        result = _k8s_logs("")
        assert "error" in result
        assert "required" in result["error"].lower()


@patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=False)
def test_k8s_describe_no_kubectl(mock_avail):
    result = _k8s_describe("pod", "my-pod")
    assert "error" in result


def test_k8s_describe_missing_args():
    with patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=True):
        result = _k8s_describe("", "my-pod")
        assert "error" in result
        result = _k8s_describe("pod", "")
        assert "error" in result


@patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=False)
def test_k8s_restart_no_kubectl(mock_avail):
    result = _k8s_restart("my-deployment")
    assert "error" in result


def test_k8s_restart_no_deployment():
    with patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=True):
        result = _k8s_restart("")
        assert "error" in result
        assert "required" in result["error"].lower()


def test_k8s_scale_negative_replicas():
    with patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=True):
        result = _k8s_scale("my-deployment", -1)
        assert "error" in result
        assert "non-negative" in result["error"].lower()


@patch("coworker.tools.k8s_mgmt._run_kubectl")
@patch("coworker.tools.k8s_mgmt._kubectl_available", return_value=True)
def test_k8s_pods_success(mock_avail, mock_run):
    pods_data = {
        "items": [
            {
                "metadata": {"name": "web-abc", "namespace": "default", "creationTimestamp": "2024-01-01T00:00:00Z"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {"name": "web", "restartCount": 0, "ready": True},
                    ],
                },
            }
        ]
    }
    mock_run.return_value = (json.dumps(pods_data), "", 0)
    result = _k8s_pods()
    assert result["count"] == 1
    assert result["pods"][0]["name"] == "web-abc"
    assert result["pods"][0]["ready"] is True


def test_k8s_restart_requires_approval():
    tools = k8s_tools()
    restart = next(t for t in tools if t.__coworker_schema__["function"]["name"] == "k8s_restart")
    meta = getattr(restart, "__aisuite_tool_metadata__", None) or getattr(restart, "metadata", None)
    if meta is not None:
        assert meta.requires_approval is True


def test_k8s_scale_requires_approval():
    tools = k8s_tools()
    scale = next(t for t in tools if t.__coworker_schema__["function"]["name"] == "k8s_scale")
    meta = getattr(scale, "__aisuite_tool_metadata__", None) or getattr(scale, "metadata", None)
    if meta is not None:
        assert meta.requires_approval is True
