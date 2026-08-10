"""SSH tools for the agent — registered using the same aisuite ToolMetadata /
``__coworker_schema__`` pattern as the connector tools in ``connectors/tools/``.
"""

from __future__ import annotations

from typing import Any, Callable

import aisuite as ai

from ...secrets import SecretStore
from .accounts import get_server, list_servers
from .client import SSHClient

# ---------------------------------------------------------------------------
# Tool-schema helpers (mirrors connectors/tools/_helpers.py)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="connector",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["ssh"],
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
# Shared helpers
# ---------------------------------------------------------------------------

_SERVER_PROP: dict[str, Any] = {
    "type": "string",
    "description": "Server ID (e.g. 'web-01'). Use ssh_list_servers to see available servers.",
}


def _resolve(secrets: SecretStore, server_id: str) -> tuple:
    """(SSHClient | None, error_dict | None)."""
    srv = get_server(secrets, server_id)
    if srv is None:
        return None, {"ok": False, "error": f"SSH server '{server_id}' not found"}
    return SSHClient(srv), None


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def ssh_tools(secrets: SecretStore) -> list[Callable[..., Any]]:
    """Build the SSH tool functions, closing over *secrets*."""
    tools: list[Callable[..., Any]] = []

    # -- ssh_list_servers ---------------------------------------------------
    def ssh_list_servers() -> dict[str, Any]:
        servers = list_servers(secrets)
        return {"ok": True, "servers": servers, "count": len(servers)}

    tools.append(
        _attach(
            ssh_list_servers,
            _schema(
                "ssh_list_servers",
                "List all registered SSH servers.",
                {},
                [],
            ),
            caps=["ssh", "read"],
        )
    )

    # -- ssh_execute --------------------------------------------------------
    def ssh_execute(
        server: str, command: str, sudo: bool = False, timeout: int = 30
    ) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        return client.execute(command, sudo=sudo, timeout=min(timeout, 120))

    tools.append(
        _attach(
            ssh_execute,
            _schema(
                "ssh_execute",
                "Execute a command on a remote server via SSH.",
                {
                    "server": _SERVER_PROP,
                    "command": {"type": "string", "description": "Shell command to run."},
                    "sudo": {
                        "type": "boolean",
                        "description": "Run with sudo (default false).",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30, max 120).",
                    },
                },
                ["server", "command"],
            ),
            approval=True,
            caps=["ssh", "write"],
        )
    )

    # -- ssh_server_status --------------------------------------------------
    def ssh_server_status(server: str) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        cmd = (
            "echo '=== uptime ===' && uptime && "
            "echo '=== cpu ===' && top -bn1 2>/dev/null | head -5 || sysctl -n vm.loadavg 2>/dev/null && "
            "echo '=== memory ===' && free -h 2>/dev/null || vm_stat 2>/dev/null && "
            "echo '=== disk ===' && df -h / 2>/dev/null"
        )
        return client.execute(cmd, timeout=15)

    tools.append(
        _attach(
            ssh_server_status,
            _schema(
                "ssh_server_status",
                "Check server basic status (uptime, CPU, memory, disk).",
                {"server": _SERVER_PROP},
                ["server"],
            ),
            caps=["ssh", "read"],
        )
    )

    # -- ssh_service_status -------------------------------------------------
    def ssh_service_status(server: str, service: str) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        return client.execute(f"systemctl status {service} --no-pager -l", timeout=15)

    tools.append(
        _attach(
            ssh_service_status,
            _schema(
                "ssh_service_status",
                "Check a systemd service status on the remote server.",
                {
                    "server": _SERVER_PROP,
                    "service": {"type": "string", "description": "Service name (e.g. 'nginx')."},
                },
                ["server", "service"],
            ),
            caps=["ssh", "read"],
        )
    )

    # -- ssh_read_file ------------------------------------------------------
    def ssh_read_file(server: str, path: str, max_lines: int = 200) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        n = max(1, min(int(max_lines or 200), 1000))
        return client.execute(f"head -n {n} {path}", timeout=15)

    tools.append(
        _attach(
            ssh_read_file,
            _schema(
                "ssh_read_file",
                "Read a file from the remote server (first N lines).",
                {
                    "server": _SERVER_PROP,
                    "path": {"type": "string", "description": "Absolute file path on the server."},
                    "max_lines": {
                        "type": "integer",
                        "description": "Max lines to read (default 200, max 1000).",
                    },
                },
                ["server", "path"],
            ),
            caps=["ssh", "read"],
        )
    )

    # -- ssh_tail_log -------------------------------------------------------
    def ssh_tail_log(server: str, log_path: str, lines: int = 50) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        n = max(1, min(int(lines or 50), 500))
        return client.execute(f"tail -n {n} {log_path}", timeout=15)

    tools.append(
        _attach(
            ssh_tail_log,
            _schema(
                "ssh_tail_log",
                "Tail a log file on the remote server.",
                {
                    "server": _SERVER_PROP,
                    "log_path": {"type": "string", "description": "Log file path."},
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to tail (default 50, max 500).",
                    },
                },
                ["server", "log_path"],
            ),
            caps=["ssh", "read"],
        )
    )

    # -- ssh_check_port -----------------------------------------------------
    def ssh_check_port(server: str, port: int) -> dict[str, Any]:
        client, err = _resolve(secrets, server)
        if err:
            return err
        # Use bash built-in /dev/tcp or nc for portability.
        cmd = (
            f"(echo >/dev/tcp/localhost/{port}) 2>/dev/null && echo 'OPEN' || "
            f"(nc -z -w2 localhost {port} 2>/dev/null && echo 'OPEN' || echo 'CLOSED')"
        )
        result = client.execute(cmd, timeout=10)
        if result.get("ok"):
            result["port"] = port
            result["status"] = "open" if "OPEN" in result.get("stdout", "") else "closed"
        return result

    tools.append(
        _attach(
            ssh_check_port,
            _schema(
                "ssh_check_port",
                "Check if a port is accessible (listening) on the remote server.",
                {
                    "server": _SERVER_PROP,
                    "port": {"type": "integer", "description": "Port number to check."},
                },
                ["server", "port"],
            ),
            caps=["ssh", "read"],
        )
    )

    return tools
