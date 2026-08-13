"""SSH tunnel (port forwarding) support.

Manages local port forwarding tunnels using the system ``ssh`` binary.
Each tunnel runs as a background SSH process (``ssh -f -N -L ...``).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SSHTunnel:
    """An active SSH tunnel (local port forwarding)."""

    local_port: int
    remote_host: str
    remote_port: int
    server_id: str
    pid: int = 0

    def is_alive(self) -> bool:
        """Check whether the tunnel process is still running."""
        if not self.pid:
            return False
        try:
            os.kill(self.pid, 0)
            return True
        except OSError:
            return False

    def close(self) -> bool:
        """Terminate the tunnel process."""
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGTERM)
                return True
            except OSError:
                return False
        return False


class TunnelManager:
    """Manage SSH tunnels (local port forwarding)."""

    def __init__(self) -> None:
        self._tunnels: dict[str, SSHTunnel] = {}  # "local_port" -> tunnel

    def open(
        self,
        server: "SSHServer",  # noqa: F821
        local_port: int,
        remote_host: str,
        remote_port: int,
    ) -> dict:
        """Open an SSH tunnel: localhost:{local_port} -> {remote_host}:{remote_port}
        via *server*.

        Returns ``{"ok": True, "tunnel": {...}}`` on success.
        """
        from .client import SSHServer  # noqa: F811 — runtime import

        key = str(local_port)
        if key in self._tunnels and self._tunnels[key].is_alive():
            return {"ok": False, "error": f"port {local_port} already in use by tunnel"}

        cmd = [
            "ssh",
            "-f",
            "-N",
            "-L",
            f"{local_port}:{remote_host}:{remote_port}",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-p",
            str(server.port),
        ]
        if server.key_path:
            cmd += ["-i", server.key_path]
        cmd.append(f"{server.username}@{server.host}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {"ok": False, "error": result.stderr.strip()}

            # ssh -f backgrounds itself; find the PID via lsof
            pid_result = subprocess.run(
                ["lsof", "-ti", f":{local_port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pid = (
                int(pid_result.stdout.strip().split("\n")[0])
                if pid_result.stdout.strip()
                else 0
            )

            tunnel = SSHTunnel(local_port, remote_host, remote_port, server.server_id, pid)
            self._tunnels[key] = tunnel
            log.info(
                "Tunnel opened: localhost:%d -> %s:%d via %s (pid=%d)",
                local_port,
                remote_host,
                remote_port,
                server.server_id,
                pid,
            )
            return {
                "ok": True,
                "tunnel": {
                    "local_port": local_port,
                    "remote": f"{remote_host}:{remote_port}",
                    "pid": pid,
                },
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "ssh tunnel setup timed out after 10s"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self, local_port: int) -> dict:
        """Close a tunnel on *local_port*."""
        key = str(local_port)
        tunnel = self._tunnels.pop(key, None)
        if not tunnel:
            return {"ok": False, "error": f"no tunnel on port {local_port}"}
        tunnel.close()
        log.info("Tunnel closed: localhost:%d", local_port)
        return {"ok": True, "local_port": local_port}

    def list(self) -> list[dict]:
        """Return all alive tunnels, pruning dead ones."""
        alive = []
        dead_keys = []
        for key, t in self._tunnels.items():
            if t.is_alive():
                alive.append(
                    {
                        "local_port": t.local_port,
                        "remote": f"{t.remote_host}:{t.remote_port}",
                        "server": t.server_id,
                        "pid": t.pid,
                    }
                )
            else:
                dead_keys.append(key)
        for k in dead_keys:
            del self._tunnels[k]
        return alive
