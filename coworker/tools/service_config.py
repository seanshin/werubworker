"""Service configuration tools — register services, manage configs, dependency mapping."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import aisuite as ai

# ---------------------------------------------------------------------------
# Schema helpers (mirrors cloud_infra.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="service_config",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["service"],
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
# Constants
# ---------------------------------------------------------------------------

_SERVICE_PREFIX = "service:"


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def service_config_tools(context: Any) -> list:
    """Return service configuration tools."""
    secrets = getattr(context, "secrets", None)
    wiki_store = getattr(context, "wiki_store", None)
    if not secrets:
        return []

    tools: list[Callable[..., Any]] = []

    # 1. register_service ----------------------------------------------
    def register_service(
        service_id: str,
        name: str,
        service_type: str,
        server_id: str = "",
        port: int = 0,
        health_url: str = "",
        repo: str = "",
        dependencies: str = "",
    ) -> dict:
        dep_list = [d.strip() for d in dependencies.split(",") if d.strip()] if dependencies else []

        profile: dict[str, Any] = {
            "name": name,
            "type": service_type,
            "server_id": server_id,
            "port": port,
            "health_url": health_url,
            "repo": repo,
            "dependencies": dep_list,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }

        key = f"{_SERVICE_PREFIX}{service_id}"

        # Check if already exists
        if secrets.get(key) is not None:
            return {"ok": False, "error": f"Service '{service_id}' already exists"}

        secrets.put(key, profile)

        # Create wiki page
        wiki_created = False
        if wiki_store:
            try:
                dep_str = ", ".join(dep_list) if dep_list else "none"
                content = (
                    f"# Service: {name}\n\n"
                    f"- **ID**: `{service_id}`\n"
                    f"- **Type**: {service_type}\n"
                    f"- **Server**: {server_id or 'N/A'}\n"
                    f"- **Port**: {port or 'N/A'}\n"
                    f"- **Health URL**: {health_url or 'N/A'}\n"
                    f"- **Repository**: {repo or 'N/A'}\n"
                    f"- **Dependencies**: {dep_str}\n"
                    f"- **Registered**: {profile['registered_at']}\n"
                )
                wiki_store.create_page(
                    page_id=f"service-{service_id}",
                    name=f"Service: {name}",
                    category="service",
                    content=content,
                    linked_service=f"{_SERVICE_PREFIX}{service_id}",
                    updated_by="service_config",
                )
                wiki_created = True
            except Exception:
                pass

        return {
            "ok": True,
            "service_id": service_id,
            "name": name,
            "wiki_created": wiki_created,
        }

    tools.append(
        _attach(
            register_service,
            _schema(
                "register_service",
                "Register a service with metadata and optionally create a Wiki page.",
                {
                    "service_id": {
                        "type": "string",
                        "description": "Unique service identifier (e.g. 'api-gateway').",
                    },
                    "name": {
                        "type": "string",
                        "description": "Human-readable service name.",
                    },
                    "service_type": {
                        "type": "string",
                        "description": "Service type (e.g. 'web', 'api', 'worker', 'database').",
                    },
                    "server_id": {
                        "type": "string",
                        "description": "Server ID where this service runs (optional).",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Service port number (optional).",
                    },
                    "health_url": {
                        "type": "string",
                        "description": "Health check URL (optional).",
                    },
                    "repo": {
                        "type": "string",
                        "description": "Git repository URL (optional).",
                    },
                    "dependencies": {
                        "type": "string",
                        "description": "Comma-separated service IDs this depends on.",
                    },
                },
                ["service_id", "name", "service_type"],
            ),
            approval=True,
            caps=["service", "write"],
        )
    )

    # 2. service_dependency_map ----------------------------------------
    def service_dependency_map(service_id: str = "") -> dict:
        # Gather all service profiles from secrets
        all_services: dict[str, dict] = {}
        for entry in secrets.status():
            key = entry["profile"]
            if key.startswith(_SERVICE_PREFIX):
                sid = key[len(_SERVICE_PREFIX):]
                data = secrets.get(key)
                if data:
                    all_services[sid] = data

        if not all_services:
            return {"ok": True, "mermaid": "graph LR\n  empty[No services registered]", "services": 0}

        # Build Mermaid diagram
        lines = ["graph LR"]
        edges: list[str] = []
        nodes: set[str] = set()

        for sid, data in all_services.items():
            if service_id and sid != service_id:
                # If filtering, only include this service and its direct deps
                deps = data.get("dependencies", [])
                if service_id not in deps and sid != service_id:
                    continue

            nodes.add(sid)
            stype = data.get("type", "unknown")
            lines.append(f"  {sid}[{data.get('name', sid)}<br/>{stype}]")
            for dep in data.get("dependencies", []):
                nodes.add(dep)
                edges.append(f"  {sid} --> {dep}")

        # Add nodes for dependencies that aren't registered services
        for node in nodes:
            if node not in all_services:
                lines.append(f"  {node}[{node}<br/>external]")

        lines.extend(edges)
        mermaid = "\n".join(lines)

        return {
            "ok": True,
            "mermaid": mermaid,
            "services": len(nodes),
            "edges": len(edges),
        }

    tools.append(
        _attach(
            service_dependency_map,
            _schema(
                "service_dependency_map",
                "Generate a Mermaid dependency diagram for services. "
                "Optionally filter to a single service and its dependencies.",
                {
                    "service_id": {
                        "type": "string",
                        "description": "Service ID to filter (empty = all services).",
                    },
                },
                [],
            ),
            caps=["service", "read"],
        )
    )

    # 3. manage_config_file --------------------------------------------
    def manage_config_file(
        service_id: str,
        action: str,
        config_type: str = "",
        content: str = "",
        server_id: str = "",
    ) -> dict:
        page_id = f"config-{service_id}-{config_type}" if config_type else f"config-{service_id}"

        if action == "get":
            if not wiki_store:
                return {"ok": False, "error": "Wiki store not available"}
            page = wiki_store.get_page(page_id)
            if page is None:
                return {"ok": False, "error": f"Config page '{page_id}' not found"}
            return {
                "ok": True,
                "page_id": page_id,
                "content": page.get("content", ""),
                "version": page.get("version", 0),
                "updated_at": page.get("updated_at", ""),
            }

        elif action == "set":
            if not content:
                return {"ok": False, "error": "content is required for 'set' action"}
            if not wiki_store:
                return {"ok": False, "error": "Wiki store not available"}
            # Try update first; create if not found
            result = wiki_store.update_page(
                page_id=page_id,
                content=content,
                updated_by="service_config",
                change_note=f"Config updated for {service_id}",
            )
            if not result.get("ok") and "not found" in result.get("error", ""):
                config_name = f"{config_type or 'main'} config" if config_type else "config"
                result = wiki_store.create_page(
                    page_id=page_id,
                    name=f"Config: {service_id} ({config_name})",
                    category="config",
                    content=content,
                    linked_service=f"{_SERVICE_PREFIX}{service_id}",
                    updated_by="service_config",
                )
            return result

        elif action == "diff":
            if not server_id:
                return {"ok": False, "error": "server_id is required for 'diff' action"}
            if not wiki_store:
                return {"ok": False, "error": "Wiki store not available"}

            # Get stored config from wiki
            page = wiki_store.get_page(page_id)
            stored = page.get("content", "") if page else ""

            # Get live config from server
            from ..connectors.ssh.accounts import get_server as _get_server

            vault = getattr(context, "vault", None)
            server = _get_server(secrets, server_id, vault=vault)
            if server is None:
                return {"ok": False, "error": f"Server '{server_id}' not found"}

            from ..connectors.ssh.client import SSHClient as _SSHClient

            client = _SSHClient(server)
            # Attempt to read the config file from the server
            if not config_type:
                return {"ok": False, "error": "config_type is required for 'diff' action"}
            result = client.execute(f"cat /etc/{config_type} 2>/dev/null", timeout=15)
            live = result.get("stdout", "") if result.get("ok") else ""

            if stored == live:
                return {"ok": True, "diff": "identical", "page_id": page_id}

            # Simple line-based diff
            stored_lines = stored.splitlines()
            live_lines = live.splitlines()
            diff_lines: list[str] = []
            max_len = max(len(stored_lines), len(live_lines))
            for i in range(max_len):
                s = stored_lines[i] if i < len(stored_lines) else ""
                l_ = live_lines[i] if i < len(live_lines) else ""
                if s != l_:
                    diff_lines.append(f"L{i + 1}: wiki='{s}' | server='{l_}'")

            return {
                "ok": True,
                "diff": "different",
                "changes": len(diff_lines),
                "details": diff_lines[:50],
                "page_id": page_id,
            }

        elif action == "history":
            if not wiki_store:
                return {"ok": False, "error": "Wiki store not available"}
            try:
                history = wiki_store.get_history(page_id)
                return {"ok": True, "page_id": page_id, "history": history}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        else:
            return {
                "ok": False,
                "error": f"Unknown action '{action}'. Use: get, set, diff, history",
            }

    tools.append(
        _attach(
            manage_config_file,
            _schema(
                "manage_config_file",
                "Manage service configuration files via Wiki versioning. "
                "Actions: get, set, diff (server vs wiki), history.",
                {
                    "service_id": {
                        "type": "string",
                        "description": "Service identifier.",
                    },
                    "action": {
                        "type": "string",
                        "description": "Action: 'get', 'set', 'diff', or 'history'.",
                        "enum": ["get", "set", "diff", "history"],
                    },
                    "config_type": {
                        "type": "string",
                        "description": "Config type label (e.g. 'nginx', 'env', 'systemd').",
                    },
                    "content": {
                        "type": "string",
                        "description": "Config content (required for 'set' action).",
                    },
                    "server_id": {
                        "type": "string",
                        "description": "Server ID for 'diff' action.",
                    },
                },
                ["service_id", "action"],
            ),
            approval=True,
            caps=["service", "write"],
        )
    )

    # 4. generate_web_config -------------------------------------------
    def generate_web_config(
        service_id: str,
        domain: str,
        upstream_port: int,
        ssl: bool = True,
        config_type: str = "nginx",
    ) -> dict:
        if config_type == "nginx":
            if ssl:
                config = (
                    f"server {{\n"
                    f"    listen 80;\n"
                    f"    server_name {domain};\n"
                    f"    return 301 https://$host$request_uri;\n"
                    f"}}\n\n"
                    f"server {{\n"
                    f"    listen 443 ssl http2;\n"
                    f"    server_name {domain};\n\n"
                    f"    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n"
                    f"    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n\n"
                    f"    location / {{\n"
                    f"        proxy_pass http://127.0.0.1:{upstream_port};\n"
                    f"        proxy_set_header Host $host;\n"
                    f"        proxy_set_header X-Real-IP $remote_addr;\n"
                    f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                    f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
                    f"    }}\n"
                    f"}}"
                )
            else:
                config = (
                    f"server {{\n"
                    f"    listen 80;\n"
                    f"    server_name {domain};\n\n"
                    f"    location / {{\n"
                    f"        proxy_pass http://127.0.0.1:{upstream_port};\n"
                    f"        proxy_set_header Host $host;\n"
                    f"        proxy_set_header X-Real-IP $remote_addr;\n"
                    f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
                    f"        proxy_set_header X-Forwarded-Proto $scheme;\n"
                    f"    }}\n"
                    f"}}"
                )
        elif config_type == "caddy":
            if ssl:
                config = (
                    f"{domain} {{\n"
                    f"    reverse_proxy localhost:{upstream_port}\n"
                    f"}}"
                )
            else:
                config = (
                    f"http://{domain} {{\n"
                    f"    reverse_proxy localhost:{upstream_port}\n"
                    f"}}"
                )
        else:
            return {"ok": False, "error": f"Unsupported config_type '{config_type}'. Use: nginx, caddy"}

        # Save to wiki
        wiki_saved = False
        if wiki_store:
            page_id = f"config-{service_id}-{config_type}"
            try:
                result = wiki_store.update_page(
                    page_id=page_id,
                    content=config,
                    updated_by="service_config",
                    change_note=f"Web config generated for {domain}",
                )
                if not result.get("ok") and "not found" in result.get("error", ""):
                    wiki_store.create_page(
                        page_id=page_id,
                        name=f"Config: {service_id} ({config_type})",
                        category="config",
                        content=config,
                        linked_service=f"{_SERVICE_PREFIX}{service_id}",
                        updated_by="service_config",
                    )
                wiki_saved = True
            except Exception:
                pass

        return {
            "ok": True,
            "service_id": service_id,
            "config_type": config_type,
            "domain": domain,
            "upstream_port": upstream_port,
            "ssl": ssl,
            "config": config,
            "wiki_saved": wiki_saved,
        }

    tools.append(
        _attach(
            generate_web_config,
            _schema(
                "generate_web_config",
                "Generate Nginx or Caddy reverse proxy configuration and save to Wiki.",
                {
                    "service_id": {
                        "type": "string",
                        "description": "Service identifier.",
                    },
                    "domain": {
                        "type": "string",
                        "description": "Domain name (e.g. 'app.example.com').",
                    },
                    "upstream_port": {
                        "type": "integer",
                        "description": "Upstream application port.",
                    },
                    "ssl": {
                        "type": "boolean",
                        "description": "Enable SSL/TLS (default true).",
                    },
                    "config_type": {
                        "type": "string",
                        "description": "Config type: 'nginx' or 'caddy' (default 'nginx').",
                        "enum": ["nginx", "caddy"],
                    },
                },
                ["service_id", "domain", "upstream_port"],
            ),
            caps=["service", "write"],
        )
    )

    # 5. generate_systemd_unit -----------------------------------------
    def generate_systemd_unit(
        service_id: str,
        exec_start: str,
        working_directory: str = "",
        user: str = "",
        restart: str = "always",
    ) -> dict:
        lines = [
            "[Unit]",
            f"Description={service_id} service",
            "After=network.target",
            "",
            "[Service]",
            f"Type=simple",
            f"ExecStart={exec_start}",
        ]
        if working_directory:
            lines.append(f"WorkingDirectory={working_directory}")
        if user:
            lines.append(f"User={user}")
        lines.extend([
            f"Restart={restart}",
            "RestartSec=5",
            "StandardOutput=journal",
            "StandardError=journal",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
        ])
        unit_content = "\n".join(lines) + "\n"

        # Save to wiki
        wiki_saved = False
        if wiki_store:
            page_id = f"config-{service_id}-systemd"
            try:
                result = wiki_store.update_page(
                    page_id=page_id,
                    content=unit_content,
                    updated_by="service_config",
                    change_note="systemd unit file generated",
                )
                if not result.get("ok") and "not found" in result.get("error", ""):
                    wiki_store.create_page(
                        page_id=page_id,
                        name=f"Config: {service_id} (systemd)",
                        category="config",
                        content=unit_content,
                        linked_service=f"{_SERVICE_PREFIX}{service_id}",
                        updated_by="service_config",
                    )
                wiki_saved = True
            except Exception:
                pass

        return {
            "ok": True,
            "service_id": service_id,
            "unit_name": f"{service_id}.service",
            "config": unit_content,
            "wiki_saved": wiki_saved,
        }

    tools.append(
        _attach(
            generate_systemd_unit,
            _schema(
                "generate_systemd_unit",
                "Generate a systemd unit file for a service and save to Wiki.",
                {
                    "service_id": {
                        "type": "string",
                        "description": "Service identifier (used as unit name).",
                    },
                    "exec_start": {
                        "type": "string",
                        "description": "ExecStart command (e.g. '/usr/bin/node /app/server.js').",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "WorkingDirectory for the service (optional).",
                    },
                    "user": {
                        "type": "string",
                        "description": "User to run the service as (optional).",
                    },
                    "restart": {
                        "type": "string",
                        "description": "Restart policy: 'always', 'on-failure', 'no' (default 'always').",
                    },
                },
                ["service_id", "exec_start"],
            ),
            caps=["service", "write"],
        )
    )

    return tools
