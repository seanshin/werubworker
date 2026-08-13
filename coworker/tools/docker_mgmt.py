"""Docker management tools — containers, images, compose, stats.

Supports both local and remote (via SSH) Docker operations. Read-only tools
(ps, logs, stats, images, compose status) don't require approval; write tools
(restart, compose up) do.
"""

from __future__ import annotations

import json as _json
import subprocess
from typing import Any

import aisuite as ai

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str], server: str = "local", timeout: int = 30) -> dict[str, Any]:
    """Run a command locally or on a remote server via SSH.

    For ``server="local"`` the command is executed directly.  Otherwise
    *server* is treated as an ``user@host`` SSH target and the command is
    tunnelled through the system ``ssh`` binary (same pattern as
    ``coworker.connectors.ssh.client``).
    """
    if server and server != "local":
        # Wrap the command for remote execution via SSH
        remote_cmd = " ".join(cmd)
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "BatchMode=yes",
            server,
            remote_cmd,
        ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
            "server": server,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Command timed out after {timeout}s", "server": server}
    except FileNotFoundError:
        return {"ok": False, "error": "docker not found on PATH", "server": server}
    except Exception as e:
        return {"ok": False, "error": str(e), "server": server}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _docker_ps(server: str = "local", filter: str = "") -> dict[str, Any]:
    """List running containers."""
    cmd = [
        "docker",
        "ps",
        "--format",
        "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}",
    ]
    if filter:
        cmd.extend(["--filter", filter])
    return _run_cmd(cmd, server=server)


def _docker_logs(container: str, lines: int = 50, server: str = "local") -> dict[str, Any]:
    """View container logs."""
    n = min(max(1, lines), 1000)
    cmd = ["docker", "logs", "--tail", str(n), container]
    return _run_cmd(cmd, server=server)


def _docker_restart(container: str, server: str = "local") -> dict[str, Any]:
    """Restart a container."""
    cmd = ["docker", "restart", container]
    return _run_cmd(cmd, server=server, timeout=60)


def _docker_compose_status(path: str = ".", server: str = "local") -> dict[str, Any]:
    """Check docker-compose service status."""
    cmd = ["docker", "compose", "-f", f"{path}/docker-compose.yml", "ps"]
    return _run_cmd(cmd, server=server)


def _docker_compose_up(path: str = ".", service: str = "", server: str = "local") -> dict[str, Any]:
    """Start docker-compose services."""
    cmd = ["docker", "compose", "-f", f"{path}/docker-compose.yml", "up", "-d"]
    if service:
        cmd.append(service)
    return _run_cmd(cmd, server=server, timeout=120)


def _docker_stats(server: str = "local") -> dict[str, Any]:
    """Container resource usage (CPU, MEM, NET)."""
    cmd = [
        "docker",
        "stats",
        "--no-stream",
        "--format",
        "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.PIDs}}",
    ]
    return _run_cmd(cmd, server=server)


def _docker_images(server: str = "local") -> dict[str, Any]:
    """List Docker images."""
    cmd = [
        "docker",
        "images",
        "--format",
        "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}",
    ]
    return _run_cmd(cmd, server=server)


# ---------------------------------------------------------------------------
# REST API helpers (CLI-based, no SDK dependency)
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Check if docker CLI is available."""
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _list_containers(all: bool = False) -> dict[str, Any]:
    """List containers in JSON format for the REST API."""
    cmd = ["docker", "ps", "--format", "json"]
    if all:
        cmd.insert(2, "-a")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        containers: list[dict] = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    containers.append(_json.loads(line))
                except _json.JSONDecodeError:
                    pass
        return {"ok": True, "containers": containers}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _container_action(container_id: str, action: str) -> dict[str, Any]:
    """Perform start/stop/restart on a container."""
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "error": f"Invalid action: {action}"}
    try:
        result = subprocess.run(
            ["docker", action, container_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {"ok": result.returncode == 0, "output": result.stdout + result.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _container_logs(container_id: str, tail: int = 100) -> dict[str, Any]:
    """Get container logs for the REST API."""
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(min(tail, 500)), container_id],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {"ok": True, "logs": result.stdout[-10000:]}  # Cap at 10k chars
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Schema definitions (aisuite tool format)
# ---------------------------------------------------------------------------

_DOCKER_PS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_ps",
        "description": (
            "List running Docker containers. Returns container ID, name, image, status, "
            "and port mappings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' for this machine, or an SSH target like 'user@host'.",
                },
                "filter": {
                    "type": "string",
                    "description": "Docker ps filter (e.g. 'name=web', 'status=running').",
                },
            },
        },
    },
}

_DOCKER_LOGS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_logs",
        "description": "View the tail of a Docker container's logs.",
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of log lines to return (default 50, max 1000).",
                },
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
            "required": ["container"],
        },
    },
}

_DOCKER_RESTART_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_restart",
        "description": "Restart a Docker container. Requires approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID to restart.",
                },
                "server": {
                    "type": "string",
                    "description": "Server to target: 'local' or an SSH target.",
                },
            },
            "required": ["container"],
        },
    },
}

_DOCKER_COMPOSE_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_compose_status",
        "description": "Check the status of docker-compose services.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing docker-compose.yml (default: '.').",
                },
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_COMPOSE_UP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_compose_up",
        "description": "Start docker-compose services in detached mode. Requires approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory containing docker-compose.yml (default: '.').",
                },
                "service": {
                    "type": "string",
                    "description": "Specific service to start (empty for all services).",
                },
                "server": {
                    "type": "string",
                    "description": "Server to target: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_STATS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_stats",
        "description": "Show container resource usage: CPU, memory, network I/O, and PIDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_IMAGES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_images",
        "description": "List Docker images with repository, tag, size, and age.",
        "parameters": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_INSPECT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_inspect",
        "description": (
            "컨테이너 상세 설정 조회 (네트워크, 볼륨, 환경변수, 포트 매핑). Read-only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "container": {
                    "type": "string",
                    "description": "Container name or ID.",
                },
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
            "required": ["container"],
        },
    },
}

_DOCKER_NETWORKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_networks",
        "description": "Docker 네트워크 목록 및 연결된 컨테이너. Read-only.",
        "parameters": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_VOLUMES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_volumes",
        "description": "Docker 볼륨 목록 (사용량 포함). Read-only.",
        "parameters": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Server to query: 'local' or an SSH target.",
                },
            },
        },
    },
}

_DOCKER_PRUNE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "docker_prune",
        "description": (
            "미사용 Docker 리소스 정리. target: all, containers, images, "
            "volumes, networks. Requires approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "Prune target: 'all', 'containers', 'images', "
                        "'volumes', 'networks' (default: 'all')."
                    ),
                },
                "server": {
                    "type": "string",
                    "description": "Server to target: 'local' or an SSH target.",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory -- called by catalog.py
# ---------------------------------------------------------------------------


def docker_tools(context: Any = None) -> list:
    """Return Docker management tools: docker_ps, docker_logs, docker_restart,
    docker_compose_status, docker_compose_up, docker_stats, docker_images."""

    def docker_ps(server: str = "local", filter: str = "") -> dict:
        """List running containers. server='local' for this machine, or an SSH server ID."""
        return _docker_ps(server, filter)

    def docker_logs(container: str, lines: int = 50, server: str = "local") -> dict:
        """View container logs."""
        return _docker_logs(container, lines, server)

    def docker_restart(container: str, server: str = "local") -> dict:
        """Restart a container (requires approval)."""
        return _docker_restart(container, server)

    def docker_compose_status(path: str = ".", server: str = "local") -> dict:
        """Check docker-compose service status."""
        return _docker_compose_status(path, server)

    def docker_compose_up(path: str = ".", service: str = "", server: str = "local") -> dict:
        """Start docker-compose services (requires approval)."""
        return _docker_compose_up(path, service, server)

    def docker_stats(server: str = "local") -> dict:
        """Container resource usage (CPU, MEM, NET)."""
        return _docker_stats(server)

    def docker_images(server: str = "local") -> dict:
        """List Docker images."""
        return _docker_images(server)

    def docker_inspect(container: str, server: str = "local") -> dict:
        """컨테이너 상세 설정 조회 (네트워크, 볼륨, 환경변수, 포트 매핑)."""
        cmd = ["docker", "inspect", container, "--format", "{{json .}}"]
        r = _run_cmd(cmd, server)
        if not r["ok"]:
            return r
        try:
            data = _json.loads(r["stdout"])
            # 주요 정보만 추출
            if isinstance(data, list) and data:
                data = data[0]
            summary = {
                "name": data.get("Name", ""),
                "image": data.get("Config", {}).get("Image", ""),
                "state": data.get("State", {}),
                "ports": data.get("NetworkSettings", {}).get("Ports", {}),
                "mounts": [
                    {
                        "source": m.get("Source"),
                        "destination": m.get("Destination"),
                        "mode": m.get("Mode"),
                    }
                    for m in data.get("Mounts", [])
                ],
                "env": data.get("Config", {}).get("Env", []),
                "networks": list(
                    data.get("NetworkSettings", {}).get("Networks", {}).keys()
                ),
                "restart_count": data.get("RestartCount", 0),
                "created": data.get("Created", ""),
            }
            return {"ok": True, "container": container, **summary}
        except Exception:
            return {"ok": True, "container": container, "raw": r["stdout"][:2000]}

    def docker_networks(server: str = "local") -> dict:
        """Docker 네트워크 목록 및 연결된 컨테이너."""
        cmd = ["docker", "network", "ls", "--format", "{{json .}}"]
        r = _run_cmd(cmd, server)
        if not r["ok"]:
            return r
        networks = []
        for line in r["stdout"].strip().split("\n"):
            if line.strip():
                try:
                    networks.append(_json.loads(line))
                except Exception:
                    pass
        return {"ok": True, "count": len(networks), "networks": networks}

    def docker_volumes(server: str = "local") -> dict:
        """Docker 볼륨 목록 (사용량 포함)."""
        cmd = ["docker", "volume", "ls", "--format", "{{json .}}"]
        r = _run_cmd(cmd, server)
        if not r["ok"]:
            return r
        volumes = []
        for line in r["stdout"].strip().split("\n"):
            if line.strip():
                try:
                    volumes.append(_json.loads(line))
                except Exception:
                    pass
        return {"ok": True, "count": len(volumes), "volumes": volumes}

    def docker_prune(target: str = "all", server: str = "local") -> dict:
        """미사용 Docker 리소스 정리 (requires approval)."""
        targets = {
            "all": ["docker", "system", "prune", "-af", "--volumes"],
            "containers": ["docker", "container", "prune", "-f"],
            "images": ["docker", "image", "prune", "-af"],
            "volumes": ["docker", "volume", "prune", "-af"],
            "networks": ["docker", "network", "prune", "-f"],
        }
        cmd = targets.get(target, targets["all"])
        return _run_cmd(cmd, server)

    _read_meta = ai.ToolMetadata(
        category="docker",
        risk_level="low",
        capabilities=["monitor"],
        requires_approval=False,
    )

    _write_meta = ai.ToolMetadata(
        category="docker",
        risk_level="high",
        capabilities=["docker_management"],
        requires_approval=True,
    )

    tools = []
    for fn, schema, meta in [
        (docker_ps, _DOCKER_PS_SCHEMA, _read_meta),
        (docker_logs, _DOCKER_LOGS_SCHEMA, _read_meta),
        (docker_restart, _DOCKER_RESTART_SCHEMA, _write_meta),
        (docker_compose_status, _DOCKER_COMPOSE_STATUS_SCHEMA, _read_meta),
        (docker_compose_up, _DOCKER_COMPOSE_UP_SCHEMA, _write_meta),
        (docker_stats, _DOCKER_STATS_SCHEMA, _read_meta),
        (docker_images, _DOCKER_IMAGES_SCHEMA, _read_meta),
        (docker_inspect, _DOCKER_INSPECT_SCHEMA, _read_meta),
        (docker_networks, _DOCKER_NETWORKS_SCHEMA, _read_meta),
        (docker_volumes, _DOCKER_VOLUMES_SCHEMA, _read_meta),
        (docker_prune, _DOCKER_PRUNE_SCHEMA, _write_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        tools.append(wrapped)

    return tools
