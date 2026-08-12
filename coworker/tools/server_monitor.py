"""Server monitoring tools — CPU, memory, disk, ports, processes, logs.

Portable across macOS and Linux: tries ``psutil`` first for richer data, falls back to
shell commands (``ps``, ``df``, ``uptime``, etc.) via ``subprocess``. Never installs
packages — the agent already has ``shell`` for anything these tools don't cover.

All tools are read-only and don't require approval. They report local-machine state;
remote-server monitoring is handled via the shell tool + SSH.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
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
# Alert thresholds
# ---------------------------------------------------------------------------


def _check_thresholds(status: dict, thresholds: dict) -> list[dict]:
    """Check if any metric exceeds configured thresholds. Returns list of alerts."""
    alerts: list[dict] = []
    cpu = status.get("cpu_percent", 0)
    mem = status.get("memory", {}).get("percent", 0) if isinstance(status.get("memory"), dict) else 0
    disk = status.get("disk_root", {}).get("percent", 0) if isinstance(status.get("disk_root"), dict) else 0

    if cpu > thresholds.get("cpu", 90):
        alerts.append({"metric": "cpu", "value": cpu, "threshold": thresholds["cpu"]})
    if mem > thresholds.get("memory", 85):
        alerts.append({"metric": "memory", "value": mem, "threshold": thresholds["memory"]})
    if disk > thresholds.get("disk", 90):
        alerts.append({"metric": "disk", "value": disk, "threshold": thresholds["disk"]})
    return alerts


# ---------------------------------------------------------------------------
# Metrics history store (SQLite)
# ---------------------------------------------------------------------------


class MetricsStore:
    def __init__(self, data_dir: Path):
        self._db = data_dir / "metrics.db"
        self._init_db()

    def _init_db(self) -> None:
        import sqlite3

        with sqlite3.connect(str(self._db)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    server_id TEXT NOT NULL DEFAULT 'local',
                    cpu REAL, memory REAL, disk REAL,
                    extra TEXT DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(timestamp)")

    def record(self, server_id: str, cpu: float, mem: float, disk: float) -> None:
        import sqlite3

        with sqlite3.connect(str(self._db)) as conn:
            conn.execute(
                "INSERT INTO metrics (timestamp, server_id, cpu, memory, disk) VALUES (?, ?, ?, ?, ?)",
                (time.time(), server_id, cpu, mem, disk),
            )
            # Prune old entries (keep 7 days)
            conn.execute("DELETE FROM metrics WHERE timestamp < ?", (time.time() - 7 * 86400,))

    def get_history(self, server_id: str = "local", range_seconds: int = 3600) -> list[dict]:
        import sqlite3

        since = time.time() - range_seconds
        with sqlite3.connect(str(self._db)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, cpu, memory, disk FROM metrics WHERE server_id = ? AND timestamp > ? ORDER BY timestamp",
                (server_id, since),
            ).fetchall()
        return [dict(r) for r in rows]


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

        # CPU detail
        cpu_freq = _ps.cpu_freq()
        cpu_times = _ps.cpu_times_percent(interval=0.5)
        per_cpu = _ps.cpu_percent(percpu=True)

        info["cpu_percent"] = _ps.cpu_percent()
        info["cpu_count"] = _ps.cpu_count(logical=False)
        info["cpu_count_logical"] = _ps.cpu_count(logical=True)
        info["cpu_freq_mhz"] = round(cpu_freq.current) if cpu_freq else 0
        info["cpu_per_core"] = per_cpu
        info["cpu_times"] = {
            "user": cpu_times.user,
            "system": cpu_times.system,
            "idle": cpu_times.idle,
        }

        # Load average
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        info["load_avg"] = {
            "1m": round(load_avg[0], 2),
            "5m": round(load_avg[1], 2),
            "15m": round(load_avg[2], 2),
        }

        # Memory detail
        mem = _ps.virtual_memory()
        info["memory"] = {
            "total_gb": round(mem.total / (1024**3), 1),
            "available_gb": round(mem.available / (1024**3), 1),
            "used_gb": round(mem.used / (1024**3), 1),
            "percent": mem.percent,
        }

        # Swap
        swap = _ps.swap_memory()
        info["swap"] = {
            "total_gb": round(swap.total / (1024**3), 1),
            "used_gb": round(swap.used / (1024**3), 1),
            "percent": swap.percent,
        }

        # Disk root
        disk = _ps.disk_usage("/")
        info["disk_root"] = {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "percent": disk.percent,
        }

        # Disk partitions — all mount points
        disk_partitions: list[dict[str, Any]] = []
        for part in _ps.disk_partitions():
            try:
                usage = _ps.disk_usage(part.mountpoint)
                disk_partitions.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "free_gb": round(usage.free / (1024**3), 1),
                    "percent": usage.percent,
                })
            except (PermissionError, OSError):
                continue
        info["disk_partitions"] = disk_partitions

        # Boot time & uptime
        boot = _ps.boot_time()
        info["uptime_seconds"] = int(time.time() - boot)
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
        for p in _ps.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status",
                                    "cmdline", "create_time", "num_threads", "username"]):
            try:
                info = p.info
                if filter and filter.lower() not in (info.get("name") or "").lower():
                    continue
                # Add cmdline as truncated string
                cmdline_parts = info.get("cmdline")
                if cmdline_parts and isinstance(cmdline_parts, list):
                    info["cmdline"] = " ".join(cmdline_parts)[:100]
                else:
                    info["cmdline"] = ""
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
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
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
        return {
            "source": "journalctl",
            "service": service or "(all)",
            "lines": n,
            "output": out[:10000],
        }
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


def _kill_process(pid: int, signal_name: str = "TERM") -> dict:
    """Kill a process by PID. Requires approval."""
    import signal as sig

    signals = {"TERM": sig.SIGTERM, "KILL": sig.SIGKILL, "HUP": sig.SIGHUP}
    s = signals.get(signal_name.upper(), sig.SIGTERM)
    try:
        os.kill(pid, s)
        return {"ok": True, "pid": pid, "signal": signal_name}
    except ProcessLookupError:
        return {"ok": False, "error": f"Process {pid} not found"}
    except PermissionError:
        return {"ok": False, "error": f"Permission denied for PID {pid}"}


def _system_info() -> dict[str, Any]:
    """Comprehensive system information for the agent."""
    info: dict[str, Any] = {
        "os": platform.system(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "cpu_model": platform.processor(),
    }
    if _HAS_PSUTIL:
        import psutil as _ps

        info["cpu_count"] = _ps.cpu_count()
        info["memory_total_gb"] = round(_ps.virtual_memory().total / (1024**3), 1)
        info["disk_total_gb"] = round(_ps.disk_usage("/").total / (1024**3), 1)
        info["boot_time"] = _ps.boot_time()
        info["uptime_hours"] = round((time.time() - _ps.boot_time()) / 3600, 1)
    return info


def _network_stats() -> dict:
    """Get network interface statistics + addresses."""
    try:
        import psutil

        interfaces: dict = {}
        counters = psutil.net_io_counters(pernic=True)
        addrs = psutil.net_if_addrs()
        if_stats = psutil.net_if_stats()

        for iface, c in counters.items():
            # Skip empty/virtual interfaces
            if c.bytes_sent == 0 and c.bytes_recv == 0:
                continue
            info: dict = {
                "bytes_sent": c.bytes_sent,
                "bytes_recv": c.bytes_recv,
                "packets_sent": c.packets_sent,
                "packets_recv": c.packets_recv,
                "errin": c.errin,
                "errout": c.errout,
                "dropin": c.dropin,
                "dropout": c.dropout,
            }
            # Add IP addresses
            iface_addrs = addrs.get(iface, [])
            ips = []
            for a in iface_addrs:
                if a.family.name in ("AF_INET", "AF_INET6"):
                    ips.append({"family": a.family.name, "address": a.address})
            info["addresses"] = ips
            # Add link status
            st = if_stats.get(iface)
            if st:
                info["is_up"] = st.isup
                info["speed_mbps"] = st.speed
                info["mtu"] = st.mtu
            interfaces[iface] = info

        # net_connections requires root on macOS — graceful fallback
        conns = -1
        try:
            conns = len(psutil.net_connections())
        except (psutil.AccessDenied, PermissionError, OSError):
            pass

        # Total throughput
        total = psutil.net_io_counters()
        return {
            "ok": True,
            "interfaces": interfaces,
            "connections": conns,
            "total": {
                "bytes_sent": total.bytes_sent,
                "bytes_recv": total.bytes_recv,
                "packets_sent": total.packets_sent,
                "packets_recv": total.packets_recv,
            },
        }
    except ImportError:
        # Fallback: netstat
        try:
            result = subprocess.run(["netstat", "-i", "-b"], capture_output=True, text=True, timeout=5)
            return {"ok": True, "raw": result.stdout[:5000], "interfaces": {}, "connections": -1}
        except Exception:
            return {"ok": False, "error": "psutil not available"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Health check schedule (S12)
# ---------------------------------------------------------------------------


class HealthChecker:
    """Periodic health checks with configurable interval and history."""

    def __init__(self, check_interval: int = 300):
        self.interval = check_interval
        self.enabled = False
        self.checks: list[dict] = []
        # History: last 100 results per check
        self._history: dict[str, list[dict]] = {}

    def _check_key(self, check: dict) -> str:
        return f"{check['type']}:{check['target']}"

    def add_check(self, check_type: str, target: str, name: str = "",
                  expected_status: int = 200, timeout_sec: int = 5) -> dict:
        """Add a health check. Types: port, http, https, tcp, dns, ping, disk, memory."""
        for c in self.checks:
            if c["type"] == check_type and c["target"] == target:
                return {"ok": True, "message": "already exists"}
        check = {
            "type": check_type,
            "target": target,
            "name": name or f"{check_type}:{target}",
            "expected_status": expected_status,
            "timeout_sec": timeout_sec,
            "last_status": "unknown",
            "last_check": 0,
            "last_latency_ms": 0,
            "last_error": "",
            "consecutive_failures": 0,
            "total_checks": 0,
            "total_failures": 0,
        }
        self.checks.append(check)
        return {"ok": True, "name": check["name"]}

    def remove_check(self, index: int) -> dict:
        if 0 <= index < len(self.checks):
            removed = self.checks.pop(index)
            return {"ok": True, "removed": removed["name"]}
        return {"ok": False, "error": "invalid index"}

    def get_history(self, check_key: str = "", limit: int = 50) -> list[dict]:
        if check_key:
            return self._history.get(check_key, [])[-limit:]
        all_history = []
        for entries in self._history.values():
            all_history.extend(entries)
        all_history.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return all_history[:limit]

    async def run_checks(self) -> list[dict]:
        results = []
        for check in self.checks:
            start = time.time()
            status = "unknown"
            error = ""
            latency_ms = 0

            try:
                if check["type"] == "port":
                    r = _check_ports(host="localhost", ports=check["target"])
                    port_results = r.get("results", r.get("ports", []))
                    status = "ok" if all(p.get("status") == "open" for p in port_results) else "fail"
                    if status == "fail":
                        failed = [p for p in port_results if p.get("status") != "open"]
                        error = f"Ports closed: {', '.join(str(p.get('port')) for p in failed)}"

                elif check["type"] in ("http", "https"):
                    import urllib.request
                    url = check["target"]
                    if not url.startswith("http"):
                        url = f"{check['type']}://{url}"
                    req = urllib.request.Request(url, method="GET")
                    resp = urllib.request.urlopen(req, timeout=check.get("timeout_sec", 5))
                    code = resp.getcode()
                    expected = check.get("expected_status", 200)
                    if code == expected:
                        status = "ok"
                    else:
                        status = "warn"
                        error = f"Expected {expected}, got {code}"

                elif check["type"] == "tcp":
                    import socket
                    host, _, port_str = check["target"].rpartition(":")
                    port = int(port_str) if port_str else 80
                    host = host or "localhost"
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(check.get("timeout_sec", 5))
                    result = sock.connect_ex((host, port))
                    sock.close()
                    status = "ok" if result == 0 else "fail"
                    if result != 0:
                        error = f"Connection refused (errno {result})"

                elif check["type"] == "dns":
                    import socket
                    socket.getaddrinfo(check["target"], None, socket.AF_INET, socket.SOCK_STREAM)
                    status = "ok"

                elif check["type"] == "ping":
                    cmd = ["ping", "-c", "1", "-W", str(check.get("timeout_sec", 3)), check["target"]]
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=check.get("timeout_sec", 5) + 2)
                    status = "ok" if r.returncode == 0 else "fail"
                    if r.returncode != 0:
                        error = "Host unreachable"
                    else:
                        # Extract latency from ping output
                        import re
                        m = re.search(r"time=(\d+\.?\d*)", r.stdout)
                        if m:
                            latency_ms = float(m.group(1))

                elif check["type"] == "disk":
                    if _HAS_PSUTIL:
                        import psutil
                        usage = psutil.disk_usage(check["target"] or "/")
                        if usage.percent > 90:
                            status = "fail"
                            error = f"Disk {usage.percent}% full"
                        elif usage.percent > 80:
                            status = "warn"
                            error = f"Disk {usage.percent}% full"
                        else:
                            status = "ok"

                elif check["type"] == "memory":
                    if _HAS_PSUTIL:
                        import psutil
                        mem = psutil.virtual_memory()
                        threshold = int(check["target"] or "85")
                        if mem.percent > threshold:
                            status = "fail"
                            error = f"Memory {mem.percent}% (threshold {threshold}%)"
                        else:
                            status = "ok"

            except Exception as e:
                status = "fail"
                error = str(e)[:200]

            elapsed = time.time() - start
            if latency_ms == 0:
                latency_ms = round(elapsed * 1000, 1)

            check["last_status"] = status
            check["last_check"] = time.time()
            check["last_latency_ms"] = latency_ms
            check["last_error"] = error
            check["total_checks"] = check.get("total_checks", 0) + 1
            if status == "fail":
                check["consecutive_failures"] = check.get("consecutive_failures", 0) + 1
                check["total_failures"] = check.get("total_failures", 0) + 1
            else:
                check["consecutive_failures"] = 0

            # Record history
            key = self._check_key(check)
            if key not in self._history:
                self._history[key] = []
            self._history[key].append({
                "timestamp": time.time(),
                "status": status,
                "latency_ms": latency_ms,
                "error": error,
            })
            # Keep last 100
            if len(self._history[key]) > 100:
                self._history[key] = self._history[key][-100:]

            results.append({**check})
        return results


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

_SYSTEM_INFO_SCHEMA = {
    "type": "function",
    "function": {
        "name": "system_info",
        "description": (
            "Comprehensive system information: OS, architecture, CPU model, memory, disk, "
            "uptime. Read-only, no side effects."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_SYSTEM_LOGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "system_logs",
        "description": (
            "Read system or service logs. Uses journalctl on Linux, 'log show' on macOS. Read-only."
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

    def system_info() -> dict:
        return _system_info()

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
        (system_info, _SYSTEM_INFO_SCHEMA),
        (system_logs, _SYSTEM_LOGS_SCHEMA),
    ]:
        wrapped = ai.tool(fn, metadata=_meta)
        wrapped.__coworker_schema__ = schema
        tools.append(wrapped)

    return tools
