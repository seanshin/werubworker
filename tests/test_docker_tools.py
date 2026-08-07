"""Docker management tools — mock subprocess since docker may not be running."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from coworker.tools.docker_mgmt import (
    _docker_ps,
    _docker_logs,
    _docker_restart,
    _docker_stats,
    _docker_images,
    _run_cmd,
    docker_tools,
)


def _mock_run(stdout="", stderr="", returncode=0):
    mock_result = MagicMock()
    mock_result.stdout = stdout
    mock_result.stderr = stderr
    mock_result.returncode = returncode
    return mock_result


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_docker_ps_local(mock_run):
    mock_run.return_value = _mock_run(stdout="CONTAINER ID  NAMES  IMAGE  STATUS\nabc  web  nginx  Up 2h")
    result = _docker_ps(server="local")
    assert result["ok"] is True
    assert "web" in result["stdout"]
    assert result["server"] == "local"


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_docker_logs(mock_run):
    mock_run.return_value = _mock_run(stdout="2024-01-01 log line 1\n2024-01-01 log line 2")
    result = _docker_logs("my-container", lines=10)
    assert result["ok"] is True
    assert "log line" in result["stdout"]


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_docker_restart_approval(mock_run):
    """docker_restart should be a write tool that requires approval."""
    mock_run.return_value = _mock_run(stdout="my-container")
    result = _docker_restart("my-container")
    assert result["ok"] is True

    # Verify the factory marks restart as requiring approval
    tools = docker_tools()
    restart_tool = None
    for t in tools:
        if t.__coworker_schema__["function"]["name"] == "docker_restart":
            restart_tool = t
            break
    assert restart_tool is not None
    meta = getattr(restart_tool, "__aisuite_tool_metadata__", None) or getattr(restart_tool, "metadata", None)
    if meta is not None:
        assert meta.requires_approval is True


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_docker_stats(mock_run):
    mock_run.return_value = _mock_run(stdout="NAME  CPU  MEM  NET\nweb  0.5%  100MiB  1kB")
    result = _docker_stats()
    assert result["ok"] is True


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_docker_images(mock_run):
    mock_run.return_value = _mock_run(stdout="REPOSITORY  TAG  SIZE\nnginx  latest  100MB")
    result = _docker_images()
    assert result["ok"] is True


def test_run_cmd_docker_not_found():
    """When docker is not on PATH, should return an error dict."""
    with patch("coworker.tools.docker_mgmt.subprocess.run", side_effect=FileNotFoundError):
        result = _run_cmd(["docker", "ps"])
    assert result["ok"] is False
    assert "not found" in result["error"]


@patch("coworker.tools.docker_mgmt.subprocess.run")
def test_run_cmd_remote_wraps_ssh(mock_run):
    mock_run.return_value = _mock_run(stdout="ok")
    result = _run_cmd(["docker", "ps"], server="deploy@web-01")
    assert result["ok"] is True
    # The call should have been wrapped in SSH
    args = mock_run.call_args[0][0]
    assert args[0] == "ssh"
    assert "deploy@web-01" in args


def test_docker_tools_factory():
    """Factory returns 7 tools."""
    tools = docker_tools()
    assert len(tools) == 7
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert "docker_ps" in names
    assert "docker_logs" in names
    assert "docker_restart" in names
    assert "docker_compose_status" in names
    assert "docker_compose_up" in names
    assert "docker_stats" in names
    assert "docker_images" in names
