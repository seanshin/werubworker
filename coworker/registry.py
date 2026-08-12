"""Service Registry — cross-references wiki pages, SSH/DB/cloud configs, and vault credentials.

Allows agents to resolve a service reference like "database:production" into
the actual configuration needed to connect, along with related wiki documentation.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


class ServiceRegistry:
    """Resolve service references across wiki, secrets, and vault."""

    def __init__(self, wiki_store, secrets, vault=None):
        self._wiki = wiki_store
        self._secrets = secrets
        self._vault = vault

    def resolve(self, service_ref: str) -> dict[str, Any]:
        """Resolve a service reference to its full context.

        Examples:
            "database:production" → DB config + related wiki pages
            "ssh:server:web-01"   → SSH profile + related wiki pages
        """
        result: dict[str, Any] = {
            "ref": service_ref,
            "type": "",
            "config": None,
            "wiki_pages": [],
            "status": "unknown",
        }

        # Determine type from prefix
        if service_ref.startswith("database:"):
            result["type"] = "database"
            name = service_ref[len("database:"):]
            cfg = self._secrets.get(f"database:{name}")
            if cfg:
                # Strip password from config
                safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
                result["config"] = safe_cfg
                result["status"] = "configured"
        elif service_ref.startswith("ssh:server:"):
            result["type"] = "ssh"
            server_id = service_ref[len("ssh:server:"):]
            cfg = self._secrets.get(f"ssh:server:{server_id}")
            if cfg:
                safe_cfg = {k: v for k, v in cfg.items() if k not in ("key_path", "password")}
                result["config"] = safe_cfg
                result["status"] = "configured"
        elif service_ref.startswith("cloud:"):
            result["type"] = "cloud"
            name = service_ref[len("cloud:"):]
            # Try cloud:provider: prefix
            cfg = self._secrets.get(f"cloud:provider:{name}")
            if cfg:
                safe_cfg = {k: v for k, v in cfg.items() if k not in ("api_key", "api_secret")}
                result["config"] = safe_cfg
                result["status"] = "configured"
        elif ":" in service_ref:
            result["type"] = service_ref.split(":")[0]

        # Find related wiki pages
        try:
            pages = self._wiki.list_pages()
            for page in pages:
                ls = page.get("linked_service", "")
                if ls and (ls == service_ref or service_ref.startswith(ls) or ls.startswith(service_ref)):
                    result["wiki_pages"].append({
                        "page_id": page.get("page_id", page.get("id", "")),
                        "name": page.get("name", ""),
                        "category": page.get("category", ""),
                    })
        except Exception:
            pass

        return result

    def list_services(self) -> list[dict[str, Any]]:
        """List all known services from secrets + wiki."""
        services: dict[str, dict] = {}

        # From secrets: databases, ssh servers, cloud providers
        for entry in self._secrets.status():
            key = entry["profile"]
            if key.startswith("database:"):
                name = key[len("database:"):]
                services[key] = {"ref": key, "type": "database", "name": name, "source": "config"}
            elif key.startswith("ssh:server:"):
                sid = key[len("ssh:server:"):]
                services[key] = {"ref": key, "type": "ssh", "name": sid, "source": "config"}
            elif key.startswith("cloud:provider:"):
                name = key[len("cloud:provider:"):]
                services[key] = {"ref": f"cloud:{name}", "type": "cloud", "name": name, "source": "config"}

        # From wiki: linked_service values
        try:
            pages = self._wiki.list_pages()
            for page in pages:
                ls = page.get("linked_service", "")
                if ls and ls not in services:
                    services[ls] = {"ref": ls, "type": ls.split(":")[0] if ":" in ls else "unknown",
                                    "name": ls, "source": "wiki"}
        except Exception:
            pass

        return list(services.values())
