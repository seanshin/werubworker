"""WikiSync — bidirectional synchronization between wiki pages and secrets.json.

Bridges the wiki's structured credential metadata with the existing SecretStore so
credential values flow in both directions without duplication.

WikiAutoSync hooks into TurnEngine tool execution to keep Wiki pages
automatically updated with the latest operational data.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from ..secrets import SecretStore
from .store import WikiStore
from .vault import Vault

log = logging.getLogger(__name__)


class WikiSync:
    def __init__(self, wiki_store: WikiStore, vault: Vault, secrets: SecretStore):
        self.wiki = wiki_store
        self.vault = vault
        self.secrets = secrets

    def sync_page_to_secrets(self, page_id: str) -> dict:
        """Read credentials from wiki page, resolve vault refs, update secrets.json."""
        page = self.wiki.get_page(page_id)
        if page is None:
            return {"ok": False, "error": f"page '{page_id}' not found"}

        service = page.get("linked_service", "")
        if not service:
            return {"ok": False, "error": "page has no linked_service"}

        # Build a secrets profile from the page's credential keys
        creds = page.get("credentials", [])
        profile: dict[str, Any] = {"type": "wiki", "source_page": page_id}
        synced = 0
        for cred in creds:
            key = cred.get("key", "")
            if not key:
                continue
            vault_key = f"{page_id}:{key}"
            try:
                value = self.vault.retrieve(vault_key)
                profile[key] = value
                synced += 1
            except (KeyError, RuntimeError):
                # Credential not in vault — skip
                continue

        if synced > 0:
            self.secrets.put(service, profile)
        return {"ok": True, "service": service, "synced_keys": synced}

    def sync_secrets_to_page(self, service_key: str) -> dict:
        """Create/update wiki page from existing secrets.json entry."""
        data = self.secrets.get(service_key)
        if data is None:
            return {"ok": False, "error": f"secret profile '{service_key}' not found"}

        # Check if a page already exists for this service
        existing = self.wiki.list_pages(query=service_key)
        page_for_service = None
        for p in existing:
            if p.get("linked_service") == service_key:
                page_for_service = p
                break

        # Build credential list from the secret data (keys only)
        credentials: list[dict[str, Any]] = []
        skip_keys = {"type", "source_page", "account_id", "expires"}
        for key, value in data.items():
            if key in skip_keys:
                continue
            cred_entry = {"key": key, "label": key.replace("_", " ").title()}
            credentials.append(cred_entry)
            # Store the actual value in the vault
            vault_key = f"{service_key}:{key}" if page_for_service else None
            if vault_key is None:
                # Will set vault_key after page creation
                pass

        if page_for_service:
            page_id = page_for_service["page_id"]
            # Store values in vault
            for key, value in data.items():
                if key in skip_keys:
                    continue
                vault_key = f"{page_id}:{key}"
                self.vault.store(vault_key, str(value), linked_services=[service_key])
            result = self.wiki.update_page(
                page_id,
                credentials=credentials,
                updated_by="sync",
                change_note=f"Synced from secrets.json ({service_key})",
            )
        else:
            page_id = service_key.replace(":", "-").replace(" ", "-").lower()
            # Determine category from the service key
            category = "service"
            if ":" in service_key:
                category = service_key.split(":")[0]
            name = service_key.replace(":", " — ").replace("_", " ").title()
            result = self.wiki.create_page(
                page_id=page_id,
                name=name,
                category=category,
                content=f"Auto-imported from secrets.json profile: {service_key}",
                credentials=credentials,
                linked_service=service_key,
                tags=["imported", "auto-sync"],
                updated_by="sync",
            )
            # Now store values in vault with the new page_id
            for key, value in data.items():
                if key in skip_keys:
                    continue
                vault_key = f"{page_id}:{key}"
                self.vault.store(vault_key, str(value), linked_services=[service_key])

        return {"ok": True, "page_id": page_id, "service": service_key}

    def import_all_secrets(self) -> dict:
        """Import all existing secrets.json entries as wiki pages."""
        statuses = self.secrets.status()
        imported = 0
        errors: list[str] = []
        for entry in statuses:
            profile = entry["profile"]
            result = self.sync_secrets_to_page(profile)
            if result.get("ok"):
                imported += 1
            else:
                errors.append(f"{profile}: {result.get('error', 'unknown')}")
        return {"ok": True, "imported": imported, "errors": errors}


class WikiAutoSync:
    """도구 실행 결과를 Wiki에 자동 동기화.

    TurnEngine에서 도구 실행 후 on_tool_result()를 호출하면,
    관련 Wiki 페이지가 자동으로 업데이트됩니다.
    """

    def __init__(self, wiki_store: WikiStore, vault: Vault | None = None):
        self._wiki = wiki_store
        self._vault = vault
        self._handlers: dict[str, Any] = {
            "ssh_server_status": self._sync_server_status,
            "ssh_execute": self._sync_server_activity,
            "db_status": self._sync_db_status,
            "db_query": self._sync_db_activity,
            "docker_ps": self._sync_docker_status,
            "k8s_pods": self._sync_k8s_status,
            "server_status": self._sync_local_server,
        }

    def on_tool_result(self, tool_name: str, args: dict, result: dict) -> None:
        """동기 호출 — 도구 실행 후 관련 Wiki 자동 업데이트."""
        handler = self._handlers.get(tool_name)
        if handler and isinstance(result, dict) and result.get("ok", True):
            try:
                handler(args, result)
            except Exception:
                log.debug("WikiAutoSync: %s handler failed", tool_name, exc_info=True)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _sync_server_status(self, args: dict, result: dict) -> None:
        """SSH 서버 상태 → Wiki structured_data 업데이트."""
        server_id = args.get("server", "")
        page_id = f"server-{server_id}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        sd = page.get("structured_data", {}) or {}
        mem = result.get("memory")
        disk = result.get("disk_root")
        sd.update({
            "last_check": time.time(),
            "cpu_percent": result.get("cpu_percent"),
            "memory_percent": mem.get("percent") if isinstance(mem, dict) else None,
            "disk_percent": disk.get("percent") if isinstance(disk, dict) else None,
            "uptime": result.get("uptime"),
            "status": "healthy" if (result.get("cpu_percent") or 0) < 90 else "warning",
        })
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: server status update",
        )

    def _sync_server_activity(self, args: dict, result: dict) -> None:
        """SSH 명령 실행 기록 → 해당 서버 Wiki에 마지막 접근 시각 업데이트."""
        server_id = args.get("server", "")
        page_id = f"server-{server_id}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        sd = page.get("structured_data", {}) or {}
        sd["last_access"] = time.time()
        sd["last_command"] = args.get("command", "")[:200]
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: SSH activity",
        )

    def _sync_db_status(self, args: dict, result: dict) -> None:
        """DB 상태 → Wiki structured_data 업데이트."""
        db_name = args.get("database", args.get("name", ""))
        page_id = f"database-{db_name}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        sd = page.get("structured_data", {}) or {}
        sd.update({
            "last_check": time.time(),
            "version": result.get("version", ""),
            "connections_active": result.get("connections_active"),
            "size_mb": result.get("size_mb"),
            "status": "healthy" if result.get("ok") else "warning",
        })
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: DB status update",
        )

    def _sync_db_activity(self, args: dict, result: dict) -> None:
        """DB 쿼리 → 마지막 접근 시각."""
        db_name = args.get("database", args.get("name", ""))
        page_id = f"database-{db_name}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        sd = page.get("structured_data", {}) or {}
        sd["last_access"] = time.time()
        sd["last_query_type"] = args.get("query", "")[:50].split()[0] if args.get("query") else ""
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: DB activity",
        )

    def _sync_docker_status(self, args: dict, result: dict) -> None:
        """Docker ps → 서버 Wiki에 컨테이너 목록 업데이트."""
        server_id = args.get("server", "__local__")
        page_id = f"server-{server_id}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        containers = result.get("containers", [])
        sd = page.get("structured_data", {}) or {}
        sd["docker_updated"] = time.time()
        sd["containers"] = [
            {
                "name": c.get("name", ""),
                "image": c.get("image", ""),
                "status": c.get("status", ""),
            }
            for c in containers[:50]  # 최대 50개만
        ]
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: Docker container list",
        )

    def _sync_k8s_status(self, args: dict, result: dict) -> None:
        """K8s pods → Pod 상태 요약."""
        cluster = args.get("cluster", args.get("context", "default"))
        page_id = f"server-k8s-{cluster}"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        pods = result.get("pods", [])
        sd = page.get("structured_data", {}) or {}
        sd["k8s_updated"] = time.time()
        sd["pod_count"] = len(pods)
        sd["pods_running"] = sum(1 for p in pods if p.get("status") == "Running")
        sd["pods_failed"] = sum(1 for p in pods if p.get("status") == "Failed")
        sd["namespace"] = args.get("namespace", "default")
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: K8s pod status",
        )

    def _sync_local_server(self, args: dict, result: dict) -> None:
        """로컬 서버 모니터링 → __local__ Wiki."""
        page_id = "server-__local__"
        page = self._wiki.get_page(page_id)
        if not page:
            return

        sd = page.get("structured_data", {}) or {}
        sd.update({
            "last_check": time.time(),
            "cpu_percent": result.get("cpu_percent"),
            "memory_percent": result.get("memory_percent"),
            "disk_percent": result.get("disk_percent"),
            "load_avg": result.get("load_avg"),
            "status": "healthy" if (result.get("cpu_percent") or 0) < 90 else "warning",
        })
        self._wiki.update_page(
            page_id,
            structured_data=sd,
            updated_by="auto-sync",
            change_note="Auto-sync: local server status",
        )
