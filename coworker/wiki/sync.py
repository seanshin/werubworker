"""WikiSync — bidirectional synchronization between wiki pages and secrets.json.

Bridges the wiki's structured credential metadata with the existing SecretStore so
credential values flow in both directions without duplication.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..secrets import SecretStore
from .store import WikiStore
from .vault import Vault


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
