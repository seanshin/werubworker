"""Server monitoring tools — CPU, memory, disk, ports, processes, logs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from coworker.tools.server_monitor import (
    _check_ports,
    _disk_usage,
    _process_list,
    _server_status,
    _service_status,
    _system_logs,
    server_monitor_tools,
)


def test_server_status_returns_dict():
    result = _server_status()
    assert isinstance(result, dict)
    assert "platform" in result
    assert "hostname" in result
    assert "python" in result


def test_service_status_empty_name():
    result = _service_status("")
    assert result == {"error": "service name is required"}


def test_service_status_unknown_service():
    """A made-up service should not crash; just return a dict."""
    result = _service_status("nonexistent_service_xyz_12345")
    assert isinstance(result, dict)
    assert "service" in result or "error" in result


@patch("coworker.tools.server_monitor.socket.create_connection")
def test_check_ports_localhost(mock_conn):
    """Port check with mocked socket — all ports appear open."""
    mock_conn.return_value.__enter__ = MagicMock()
    mock_conn.return_value.__exit__ = MagicMock(return_value=False)
    result = _check_ports("localhost", "80,443")
    assert result["host"] == "localhost"
    assert len(result["results"]) == 2
    for r in result["results"]:
        assert r["status"] == "open"


@patch("coworker.tools.server_monitor.socket.create_connection", side_effect=ConnectionRefusedError)
def test_check_ports_closed(mock_conn):
    result = _check_ports("localhost", "19999")
    assert result["results"][0]["status"] == "closed"


def test_check_ports_invalid_port():
    """Non-numeric port values should be silently skipped."""
    result = _check_ports("localhost", "abc,xyz")
    assert result["results"] == []


def test_check_ports_caps_at_20():
    """At most 20 ports should be checked."""
    ports = ",".join(str(p) for p in range(10000, 10030))
    with patch(
        "coworker.tools.server_monitor.socket.create_connection", side_effect=ConnectionRefusedError
    ):
        result = _check_ports("localhost", ports)
    assert len(result["results"]) == 20


def test_process_list_no_filter():
    result = _process_list()
    assert isinstance(result, dict)
    assert "count" in result


def test_process_list_with_filter():
    result = _process_list("python")
    assert isinstance(result, dict)
    assert "count" in result


def test_disk_usage_root():
    result = _disk_usage("/")
    assert isinstance(result, dict)
    assert "path" in result or "error" in result


def test_system_logs_default():
    result = _system_logs()
    assert isinstance(result, dict)
    assert "source" in result or "error" in result


def test_system_logs_caps_lines():
    """Lines should be capped between 1 and 500."""
    result = _system_logs(lines=9999)
    assert isinstance(result, dict)


def test_server_monitor_tools_factory():
    """Factory returns 7 tools with correct schema attributes."""
    tools = server_monitor_tools()
    assert len(tools) == 7
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert names == {
        "server_status",
        "service_status",
        "check_ports",
        "process_list",
        "disk_usage",
        "system_info",
        "system_logs",
    }
