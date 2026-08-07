"""SSH client wrapper — uses the system ``ssh`` command via subprocess.

No paramiko dependency: the system ``ssh`` binary handles key-agent
negotiation, known_hosts, and all auth methods out of the box.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SSHServer:
    """Registered SSH server profile."""

    server_id: str  # e.g. "web-01"
    host: str  # e.g. "192.168.1.10"
    port: int = 22
    username: str = "deploy"
    key_path: Optional[str] = None
    label: str = ""
    tags: list[str] = field(default_factory=list)


class SSHClient:
    """Execute commands on a remote server via the system ``ssh`` binary."""

    def __init__(self, server: SSHServer) -> None:
        self.server = server

    def execute(
        self, command: str, *, sudo: bool = False, timeout: int = 30
    ) -> dict:
        """Run *command* on the remote host and return a result dict."""
        ssh_cmd = self._build_ssh_command(command, sudo=sudo)
        try:
            result = subprocess.run(
                ssh_cmd, capture_output=True, text=True, timeout=timeout
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
                "host": self.server.host,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": f"Command timed out after {timeout}s",
                "host": self.server.host,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "host": self.server.host}

    def test_connection(self) -> dict:
        """Quick connectivity check (runs ``echo ok``)."""
        return self.execute("echo ok", timeout=10)

    def _build_ssh_command(
        self, command: str, *, sudo: bool = False
    ) -> list[str]:
        args = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
        ]
        if self.server.key_path:
            args.extend(["-i", os.path.expanduser(self.server.key_path)])
        args.extend(["-p", str(self.server.port)])
        args.append(f"{self.server.username}@{self.server.host}")
        if sudo:
            args.append(f"sudo {command}")
        else:
            args.append(command)
        return args
