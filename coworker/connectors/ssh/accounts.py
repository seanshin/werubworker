"""SSH server registration and management — secrets-backed.

Server profiles live in ``secrets.json`` under the key pattern
``ssh:server:<server_id>``, exactly like connector account profiles.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ...secrets import SecretStore
from .client import SSHServer

PREFIX = "ssh:server:"

# Allowed key_path directories (expanded from ~)
_ALLOWED_KEY_DIRS = (".ssh", ".config")


def _validate_key_path(key_path: str) -> str | None:
    """Return error if key_path is unsafe, else None."""
    import os
    from pathlib import Path

    expanded = os.path.expanduser(key_path)
    resolved = Path(expanded).resolve()
    home = Path.home().resolve()
    # Must be under home directory
    if not str(resolved).startswith(str(home)):
        return "key_path must be under home directory"
    # Must not follow symlinks outside home
    if resolved.is_symlink():
        target = resolved.resolve()
        if not str(target).startswith(str(home)):
            return "key_path symlink target must be under home directory"
    return None


def list_servers(secrets: SecretStore) -> list[dict[str, Any]]:
    """Return metadata for every registered SSH server (never leaks keys)."""
    servers: list[dict[str, Any]] = []
    for entry in secrets.status():
        profile_key = entry["profile"]
        if not profile_key.startswith(PREFIX):
            continue
        server_id = profile_key[len(PREFIX) :]
        data = secrets.get(profile_key) or {}
        servers.append(
            {
                "server_id": server_id,
                "host": data.get("host", ""),
                "port": data.get("port", 22),
                "username": data.get("username", "deploy"),
                "label": data.get("label", ""),
                "tags": data.get("tags", []),
                "added_at": data.get("added_at", ""),
            }
        )
    return servers


def add_server(
    secrets: SecretStore,
    server_id: str,
    host: str,
    port: int = 22,
    username: str = "deploy",
    key_path: str = "",
    label: str = "",
    tags: Optional[list[str]] = None,
    vault: Any = None,
) -> dict[str, Any]:
    """Register a new SSH server. Returns ``{ok: True}`` or an error dict."""
    server_id = server_id.strip()
    if not server_id:
        return {"ok": False, "error": "server_id is required"}
    if not host.strip():
        return {"ok": False, "error": "host is required"}

    key = PREFIX + server_id
    if secrets.get(key) is not None:
        return {"ok": False, "error": f"server '{server_id}' already exists"}

    profile: dict[str, Any] = {
        "host": host.strip(),
        "port": int(port),
        "username": username.strip() or "deploy",
        "added_at": str(date.today()),
    }
    if key_path:
        err = _validate_key_path(key_path.strip())
        if err:
            return {"ok": False, "error": err}
        # Store key_path in vault when available; keep in profile as fallback
        if vault is not None:
            try:
                vault.store(f"ssh:{server_id}:key_path", key_path.strip())
            except Exception:
                # Vault store failed — fall back to secrets profile
                profile["key_path"] = key_path.strip()
        else:
            profile["key_path"] = key_path.strip()
    if label:
        profile["label"] = label.strip()
    if tags:
        profile["tags"] = [t.strip() for t in tags if t.strip()]

    secrets.put(key, profile)
    return {"ok": True, "server_id": server_id}


def remove_server(secrets: SecretStore, server_id: str) -> dict[str, Any]:
    """Remove a registered SSH server."""
    key = PREFIX + server_id.strip()
    if secrets.delete(key):
        return {"ok": True, "removed": server_id}
    return {"ok": False, "error": f"server '{server_id}' not found"}


def get_server(secrets: SecretStore, server_id: str, vault: Any = None) -> Optional[SSHServer]:
    """Look up a server by id, returning an ``SSHServer`` or ``None``."""
    data = secrets.get(PREFIX + server_id.strip())
    if data is None:
        return None
    # Try vault first for key_path, fall back to secrets profile
    key_path = data.get("key_path")
    if vault is not None:
        try:
            key_path = vault.retrieve(f"ssh:{server_id.strip()}:key_path")
        except (KeyError, RuntimeError):
            pass  # Not in vault or vault locked — use profile value
    return SSHServer(
        server_id=server_id.strip(),
        host=data.get("host", ""),
        port=int(data.get("port", 22)),
        username=data.get("username", "deploy"),
        key_path=key_path,
        label=data.get("label", ""),
        tags=data.get("tags", []),
    )
