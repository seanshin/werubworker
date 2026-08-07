"""SSH connector — remote server access via the system ``ssh`` command.

Server configs are stored in ``secrets.json`` as ``ssh:server:<id>`` entries.
No paramiko dependency: uses ``subprocess`` + the system ``ssh`` binary, which
is always available on macOS/Linux.
"""

from __future__ import annotations

from .accounts import add_server, get_server, list_servers, remove_server
from .client import SSHClient, SSHServer
from .tools import ssh_tools

__all__ = [
    "SSHClient",
    "SSHServer",
    "add_server",
    "get_server",
    "list_servers",
    "remove_server",
    "ssh_tools",
]
