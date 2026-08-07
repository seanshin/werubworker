"""Server monitoring tools — CPU, memory, disk, ports, processes, logs.

Portable across macOS and Linux: tries ``psutil`` first for richer data, falls back to
shell commands (``ps``, ``df``, ``uptime``, etc.) via ``subprocess``. Never installs
packages — the agent already has ``shell`` for anything these tools don't cover.

All tools are read-only and don't require approval. They report local-machine state;
remote-server monitoring is handled via the shell tool + SSH.
"""

from __future__ import annotations

import platform
import socket
import subprocess
import sys
from typing import Any, Optional

import aisuite as ai

# AgentContext not imported here to avoid circular import with catalog.py

# ---------------------------------------------------------------------------
# psutil — best-effort import
# ---------------------------------------------------------------------------
try:
    import psutil  # type: ignore[import-untyped]

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_IS_DARWIN = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 10) -> str:
    """Run a command and return its stdout (best-effort, never raises)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _server_status() -> dict[str, Any]:
    """Check local server status: CPU, memory, disk usage, uptime, platform info."""
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "hostname": platform.node(),
        "python": platform.python_version(),
    }

    if _HAS_PSUTIL:
        import psutil as _ps

        info["cpu_percent"] = _ps.cpu_percent(interval=0.5)
        info["cpu_count"] = _ps.cpu_count()
        mem = _ps.virtual_memory()
        info["memory"] = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "percent": mem.percent,
        }
        disk = _ps.disk_usage("/")
        info["disk_root"] = {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "percent": disk.percent,
        }
        boot = _ps.boot_time()
        import datetime as _dt

        info["uptime_seconds"] = int((_dt.datetime.now().timestamp() - boot))
    else:
        # Fallback: shell commands
        info["uptime"] = _run(["uptime"])
        info["memory"] = _run(["vm_stat"] if _IS_DARWIN else ["free", "-h"])
        info["disk_root"] = _run(["df", "-h", "/"])

    return info


def _service_status(service: str) -> dict[str, Any]:
    """Check a system service status (systemctl on Linux, launchctl on macOS)."""
    if not service:
        return {"error": "service name is required"}

    if _IS_LINUX:
        out = _run(["systemctl", "status", service])
        active = _run(["systemctl", "is-active", service])
        return {"service": service, "active": active, "details": out[:2000]}
    elif _IS_DARWIN:
        # launchctl list filters by label
        out = _run(["launchctl", "list"])
        lines = [l for l in out.splitlines() if service.lower() in l.lower()]
        return {
            "service": service,
            "backend": "launchctl",
            "matches": lines[:20],
            "note": "use 'launchctl list <label>' via shell for full details",
        }
    else:
        return {"error": f"service status not supported on {sys.platform}"}


def _check_ports(host: str = "localhost", ports: str = "80,443,8080") -> dict[str, Any]:
    """Check if TCP ports are accessible on a host."""
    results: list[dict[str, Any]] = []
    port_list: list[int] = []
    for p in str(ports).replace(" ", "").split(","):
        try:
            port_list.append(int(p))
        except ValueError:
            continue

    for port in port_list[:20]:  # cap at 20 ports
        try:
            with socket.create_connection((host, port), timeout=3):
                results.append({"port": port, "status": "open"})
        except (ConnectionRefusedError, OSError):
            results.append({"port": port, "status": "closed"})
        except socket.timeout:
            results.append({"port": port, "status": "timeout"})

    return {"host": host, "results": results}


def _process_list(filter: str = "") -> dict[str, Any]:
    """List running processes, optionally filtered by name."""
    if _HAS_PSUTIL:
        import psutil as _ps

        procs = []
        for p in _ps.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                info = p.info
                if filter and filter.lower() not in (info.get("name") or "").lower():
                    continue
                procs.append(info)
            except (_ps.NoSuchProcess, _ps.AccessDenied):
                continue
        # Sort by CPU usage descending, limit to top 50
        procs.sort(key=lambda x: x.get("cpu_percent") or 0, reverse=True)
        return {"count": len(procs), "processes": procs[:50]}
    else:
        if filter:
            out = _run(["ps", "aux"])
            lines = [l for l in out.splitlines() if filter.lower() in l.lower()]
            return {"count": len(lines), "output": "\n".join(lines[:50])}
        else:
            out = _run(["ps", "aux", "--sort=-%cpu"] if _IS_LINUX else ["ps", "aux"])
            lines = out.splitlines()
            return {"count": max(0, len(lines) - 1), "output": "\n".join(lines[:51])}


def _disk_usage(path: str = "/") -> dict[str, Any]:
    """Detailed disk usage for a path."""
    if _HAS_PSUTIL:
        import psutil as _ps

        try:
            usage = _ps.disk_usage(path)
            return {
                "path": path,
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
                "percent": usage.percent,
            }
        except OSError as e:
            return {"error": str(e)}
    else:
        out = _run(["df", "-h", path])
        return {"path": path, "output": out}


def _system_logs(service: str = "", lines: int = 50) -> dict[str, Any]:
    """Read system/service logs (journalctl on Linux, log show on macOS)."""
    n = min(max(1, lines), 500)  # cap at 500 lines

    if _IS_LINUX:
        cmd = ["journalctl", "--no-pager", "-n", str(n)]
        if service:
            cmd += ["-u", service]
        out = _run(cmd, timeout=15)
        return {"source": "journalctl", "service": service or "(all)", "lines": n, "output": out[:10000]}
    elif _IS_DARWIN:
        cmd = ["log", "show", "--last", "1h", "--style", "compact"]
        if service:
            cmd += ["--predicate", f'process == "{service}"']
        out = _run(cmd, timeout=15)
        # log show can be very verbose; take last N lines
        log_lines = out.splitlines()
        tail = log_lines[-n:] if len(log_lines) > n else log_lines
        return {
            "source": "log show",
            "service": service or "(all)",
            "lines": len(tail),
            "output": "\n".join(tail)[:10000],
        }
    else:
        return {"error": f"system logs not supported on {sys.platform}"}


# ---------------------------------------------------------------------------
# Schema definitions (aisuite tool format)
# ---------------------------------------------------------------------------

_SERVER_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "server_status",
        "description": (
            "Check local server status: CPU usage, memory, disk, uptime, and platform info. "
            "Read-only, no side effects."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_SERVICE_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "service_status",
        "description": (
            "Check a system service status. Uses systemctl on Linux, launchctl on macOS."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name (e.g. 'nginx', 'postgresql', 'docker').",
                },
            },
            "required": ["service"],
        },
    },
}

_CHECK_PORTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "check_ports",
        "description": (
            "Check if TCP ports are accessible on a host. Returns open/closed/timeout for each port."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Hostname or IP to check (default: localhost).",
                },
                "ports": {
                    "type": "string",
                    "description": "Comma-separated port numbers (default: '80,443,8080'). Max 20.",
                },
            },
        },
    },
}

_PROCESS_LIST_SCHEMA = {
    "type": "function",
    "function": {
        "name": "process_list",
        "description": (
            "List running processes, optionally filtered by name. Returns top 50 by CPU usage."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Filter processes by name (case-insensitive substring match).",
                },
            },
        },
    },
}

_DISK_USAGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "disk_usage",
        "description": "Detailed disk usage for a path: total, used, free, and percentage.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Filesystem path to check (default: '/').",
                },
            },
        },
    },
}

_SYSTEM_LOGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "system_logs",
        "description": (
            "Read system or service logs. Uses journalctl on Linux, 'log show' on macOS. "
            "Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service/process name to filter logs (empty for all).",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return (default 50, max 500).",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory — called by catalog.py
# ---------------------------------------------------------------------------

def server_monitor_tools(context: Any = None) -> list:
    """Return the server monitoring toolset: server_status, service_status, check_ports,
    process_list, disk_usage, system_logs. All read-only, no approval required."""

    def server_status() -> dict:
        return _server_status()

    def service_status(service: str) -> dict:
        return _service_status(service)

    def check_ports(host: str = "localhost", ports: str = "80,443,8080") -> dict:
        return _check_ports(host, ports)

    def process_list(filter: str = "") -> dict:
        return _process_list(filter)

    def disk_usage(path: str = "/") -> dict:
        return _disk_usage(path)

    def system_logs(service: str = "", lines: int = 50) -> dict:
        return _system_logs(service, lines)

    _meta = ai.ToolMetadata(
        category="server_monitor",
        risk_level="low",
        capabilities=["monitor"],
        requires_approval=False,
    )

    tools = []
    for fn, schema in [
        (server_status, _SERVER_STATUS_SCHEMA),
        (service_status, _SERVICE_STATUS_SCHEMA),
        (check_ports, _CHECK_PORTS_SCHEMA),
        (process_list, _PROCESS_LIST_SCHEMA),
        (disk_usage, _DISK_USAGE_SCHEMA),
        (system_logs, _SYSTEM_LOGS_SCHEMA),
    ]:
        wrapped = ai.tool(fn, metadata=_meta)
        wrapped.__coworker_schema__ = schema
        tools.append(wrapped)

    return tools
