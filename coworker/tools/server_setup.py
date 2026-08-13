"""Server onboarding tools — register, test, document servers in one workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import aisuite as ai

from ..connectors.ssh.accounts import add_server, get_server, list_servers, remove_server
from ..connectors.ssh.client import SSHClient
from ..registry import ServiceRegistry

# ---------------------------------------------------------------------------
# Schema helpers (mirrors cloud_infra.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="server_setup",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["server"],
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
# Helpers
# ---------------------------------------------------------------------------

_INFO_COMMANDS = {
    "uname": "uname -a",
    "uptime": "uptime",
    "memory": "free -h 2>/dev/null || vm_stat 2>/dev/null",
    "disk": "df -h",
    "cpu": "nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null",
    "os_release": "cat /etc/os-release 2>/dev/null || sw_vers 2>/dev/null",
}


def _collect_server_info(client: SSHClient) -> dict[str, str]:
    """Run diagnostic commands and return collected info."""
    info: dict[str, str] = {}
    for key, cmd in _INFO_COMMANDS.items():
        result = client.execute(cmd, timeout=15)
        if result.get("ok"):
            info[key] = result.get("stdout", "").strip()
        else:
            info[key] = f"(failed: {result.get('error', 'unknown')})"
    return info


def _build_server_wiki_content(server_id: str, host: str, port: int,
                               username: str, label: str, tags: list[str],
                               info: dict[str, str]) -> str:
    """Build markdown content for a server wiki page."""
    tag_str = ", ".join(tags) if tags else "none"
    lines = [
        f"# Server: {server_id}",
        "",
        f"- **Host**: `{host}`",
        f"- **Port**: `{port}`",
        f"- **Username**: `{username}`",
        f"- **Label**: {label or 'N/A'}",
        f"- **Tags**: {tag_str}",
        f"- **Registered**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## System Information",
        "",
    ]
    for key, value in info.items():
        lines.append(f"### {key}")
        lines.append(f"```\n{value}\n```")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def server_setup_tools(context: Any) -> list:
    """Return server onboarding tools."""
    secrets = getattr(context, "secrets", None)
    wiki_store = getattr(context, "wiki_store", None)
    vault = getattr(context, "vault", None)
    if not secrets:
        return []

    tools: list[Callable[..., Any]] = []

    # 1. register_server -----------------------------------------------
    def register_server(
        server_id: str,
        host: str,
        port: int = 22,
        username: str = "deploy",
        key_path: str = "",
        label: str = "",
        tags: str = "",
        create_wiki: bool = True,
    ) -> dict:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        # Register via accounts module
        reg = add_server(
            secrets,
            server_id=server_id,
            host=host,
            port=port,
            username=username,
            key_path=key_path,
            label=label,
            tags=tag_list,
            vault=vault,
        )
        if not reg.get("ok"):
            return reg

        # Resolve to SSHServer and test connection
        server = get_server(secrets, server_id, vault=vault)
        if server is None:
            return {"ok": False, "error": f"Server registered but lookup failed: {server_id}"}

        client = SSHClient(server)
        conn_test = client.test_connection()
        if not conn_test.get("ok"):
            return {
                "ok": True,
                "server_id": server_id,
                "registered": True,
                "connection_test": False,
                "warning": f"Registered but connection failed: {conn_test.get('error', '')}",
            }

        # Collect server info
        info = _collect_server_info(client)

        # Create wiki page if requested
        wiki_created = False
        if create_wiki and wiki_store:
            try:
                content = _build_server_wiki_content(
                    server_id, host, port, username, label, tag_list, info
                )
                wiki_store.create_page(
                    page_id=f"server-{server_id}",
                    name=f"Server: {server_id}",
                    category="server",
                    content=content,
                    linked_service=f"ssh:server:{server_id}",
                    tags=tag_list,
                    updated_by="server_setup",
                )
                wiki_created = True
            except Exception:
                pass  # Wiki creation is best-effort

        return {
            "ok": True,
            "server_id": server_id,
            "registered": True,
            "connection_test": True,
            "info": info,
            "wiki_created": wiki_created,
        }

    tools.append(
        _attach(
            register_server,
            _schema(
                "register_server",
                "Register an SSH server, test connectivity, collect system info, "
                "and optionally create a Wiki page.",
                {
                    "server_id": {
                        "type": "string",
                        "description": "Unique server identifier (e.g. 'web-01').",
                    },
                    "host": {
                        "type": "string",
                        "description": "Hostname or IP address.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port (default 22).",
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username (default 'deploy').",
                    },
                    "key_path": {
                        "type": "string",
                        "description": "Path to SSH private key (optional).",
                    },
                    "label": {
                        "type": "string",
                        "description": "Human-readable label for the server.",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Comma-separated tags (e.g. 'production,web').",
                    },
                    "create_wiki": {
                        "type": "boolean",
                        "description": "Auto-create Wiki page (default true).",
                    },
                },
                ["server_id", "host"],
            ),
            approval=True,
            caps=["server", "write"],
        )
    )

    # 2. list_infrastructure -------------------------------------------
    def list_infrastructure() -> dict:
        try:
            registry = ServiceRegistry(wiki_store, secrets, vault)
            all_services = registry.list_services()
        except Exception as e:
            return {"ok": False, "error": f"Failed to list services: {e}"}

        categorized: dict[str, list[dict]] = {
            "servers": [],
            "databases": [],
            "cloud_providers": [],
            "other": [],
        }
        for svc in all_services:
            stype = svc.get("type", "")
            if stype == "ssh":
                categorized["servers"].append(svc)
            elif stype == "database":
                categorized["databases"].append(svc)
            elif stype == "cloud":
                categorized["cloud_providers"].append(svc)
            else:
                categorized["other"].append(svc)

        return {
            "ok": True,
            **categorized,
            "total": len(all_services),
        }

    tools.append(
        _attach(
            list_infrastructure,
            _schema(
                "list_infrastructure",
                "List all registered infrastructure: servers, databases, "
                "cloud providers, and other services.",
                {},
                [],
            ),
            caps=["server", "read"],
        )
    )

    # 3. refresh_server_info -------------------------------------------
    def refresh_server_info(server_id: str) -> dict:
        server = get_server(secrets, server_id, vault=vault)
        if server is None:
            return {"ok": False, "error": f"Server '{server_id}' not found"}

        client = SSHClient(server)
        conn_test = client.test_connection()
        if not conn_test.get("ok"):
            return {
                "ok": False,
                "error": f"Connection failed: {conn_test.get('error', '')}",
            }

        info = _collect_server_info(client)

        # Update wiki page if available
        wiki_updated = False
        if wiki_store:
            page_id = f"server-{server_id}"
            try:
                content = _build_server_wiki_content(
                    server_id,
                    server.host,
                    server.port,
                    server.username,
                    server.label,
                    server.tags,
                    info,
                )
                result = wiki_store.update_page(
                    page_id=page_id,
                    content=content,
                    updated_by="server_setup",
                    change_note="Server info refreshed",
                )
                wiki_updated = result.get("ok", False)
            except Exception:
                pass

        return {
            "ok": True,
            "server_id": server_id,
            "info": info,
            "wiki_updated": wiki_updated,
        }

    tools.append(
        _attach(
            refresh_server_info,
            _schema(
                "refresh_server_info",
                "Re-collect system info from an SSH server and update its Wiki page.",
                {
                    "server_id": {
                        "type": "string",
                        "description": "Server identifier to refresh.",
                    },
                },
                ["server_id"],
            ),
            caps=["server", "read"],
        )
    )

    # 4. decommission_server -------------------------------------------
    def decommission_server(server_id: str) -> dict:
        server = get_server(secrets, server_id, vault=vault)
        if server is None:
            return {"ok": False, "error": f"Server '{server_id}' not found"}

        # Archive wiki page (soft-delete)
        wiki_archived = False
        if wiki_store:
            page_id = f"server-{server_id}"
            try:
                # Add decommission note before archiving
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                wiki_store.update_page(
                    page_id=page_id,
                    content=None,
                    updated_by="server_setup",
                    change_note=f"Server decommissioned at {now_str}",
                )
                result = wiki_store.delete_page(page_id)
                wiki_archived = result.get("ok", False)
            except Exception:
                pass

        # Remove from SSH accounts
        removal = remove_server(secrets, server_id)
        if not removal.get("ok"):
            return {
                "ok": False,
                "error": removal.get("error", "Failed to remove server"),
                "wiki_archived": wiki_archived,
            }

        return {
            "ok": True,
            "server_id": server_id,
            "removed": True,
            "wiki_archived": wiki_archived,
        }

    tools.append(
        _attach(
            decommission_server,
            _schema(
                "decommission_server",
                "Decommission a server: remove registration and archive its Wiki page.",
                {
                    "server_id": {
                        "type": "string",
                        "description": "Server identifier to decommission.",
                    },
                },
                ["server_id"],
            ),
            approval=True,
            caps=["server", "write"],
        )
    )

    return tools
