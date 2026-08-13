"""ServiceResolver — resolve natural-language service references via Wiki.

Bridges the gap between human-friendly names ("production DB", "web-03 서버")
and the actual configuration needed to connect. Uses FTS5 search + linked_service
to find the right Wiki page and extract connection details.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ServiceResolver:
    """Wiki 기반 자연어 서비스 해석기.

    SecretStore의 설정 키와 Wiki 페이지를 연결하여,
    자연어 질의로 서비스 연결 정보를 찾을 수 있도록 합니다.
    """

    def __init__(self, wiki_store, secrets=None, vault=None):
        self._wiki = wiki_store
        self._secrets = secrets
        self._vault = vault

    def resolve_natural(self, query: str) -> dict:
        """자연어 서비스 참조를 Wiki 기반으로 해석.

        "production DB" → database:production Wiki 페이지 + 설정 + 자격증명 키
        "web-03 서버"   → server-web-03 Wiki 페이지 + SSH 프로필
        "API 서비스"    → svc-prod-api Wiki 페이지 + 서비스 설정
        """
        # 1. FTS5 검색
        pages = self._wiki.search_fts(query, limit=10)

        # 2. linked_service가 있는 페이지 우선
        for page in pages:
            linked = page.get("linked_service", "")
            if linked and self._secrets:
                config = self._secrets.get(linked)
                if config:
                    # 비밀번호 등 민감 정보 제거
                    sensitive_keys = ("password", "key_path", "api_key", "api_secret")
                    safe_config = {
                        k: v for k, v in config.items() if k not in sensitive_keys
                    }
                    return {
                        "ok": True,
                        "page_id": page.get("page_id"),
                        "name": page.get("name"),
                        "linked_service": linked,
                        "config": safe_config,
                        "category": page.get("category", ""),
                    }

        # 3. 페이지만 반환 (config 없이)
        if pages:
            return {
                "ok": True,
                "page_id": pages[0].get("page_id"),
                "name": pages[0].get("name"),
                "linked_service": pages[0].get("linked_service", ""),
                "config": None,
                "category": pages[0].get("category", ""),
            }

        return {"ok": False, "error": f"'{query}'에 해당하는 서비스를 찾을 수 없습니다"}

    def get_connection_context(self, page_id: str) -> dict:
        """Wiki 페이지에서 서비스 연결에 필요한 모든 정보를 추출."""
        page = self._wiki.get_page(page_id)
        if not page:
            return {"ok": False, "error": f"page '{page_id}' not found"}

        context: dict[str, Any] = {
            "ok": True,
            "page_id": page_id,
            "name": page.get("name", ""),
            "category": page.get("category", ""),
            "structured_data": page.get("structured_data", {}),
            "linked_service": page.get("linked_service", ""),
            "credentials": {},
            "related_pages": [],
            "runbooks": [],
        }

        # Vault 자격증명 키 목록
        for cred in page.get("credentials", []):
            cred_key = cred.get("key", "")
            if not cred_key:
                continue
            context["credentials"][cred_key] = {
                "type": cred.get("type"),
                "expires_at": cred.get("expires_at"),
                "vault_key": f"{page_id}:{cred_key}",
            }

        # 관련 페이지 (같은 linked_service)
        linked = page.get("linked_service", "")
        if linked:
            all_pages = self._wiki.list_pages()
            for p in all_pages:
                pid = p.get("page_id", p.get("id", ""))
                if pid == page_id:
                    continue
                if p.get("linked_service") == linked:
                    context["related_pages"].append({
                        "page_id": pid,
                        "name": p.get("name", ""),
                    })
                if p.get("category") == "runbook" and linked in str(p):
                    context["runbooks"].append({
                        "page_id": pid,
                        "name": p.get("name", ""),
                    })

        return context

    def list_services_with_wiki(self) -> list[dict]:
        """모든 서비스와 관련 Wiki 페이지 매핑."""
        services: dict[str, dict] = {}

        # secrets에서 서비스 목록
        if self._secrets:
            for entry in self._secrets.status():
                key = entry.get("profile", "")
                if key.startswith("database:"):
                    name = key[len("database:"):]
                    services[key] = {
                        "ref": key, "type": "database",
                        "name": name, "wiki_page": None,
                    }
                elif key.startswith("ssh:server:"):
                    sid = key[len("ssh:server:"):]
                    services[key] = {
                        "ref": key, "type": "ssh",
                        "name": sid, "wiki_page": None,
                    }
                elif key.startswith("cloud:provider:"):
                    name = key[len("cloud:provider:"):]
                    services[f"cloud:{name}"] = {
                        "ref": f"cloud:{name}", "type": "cloud",
                        "name": name, "wiki_page": None,
                    }
                elif key.startswith("service:"):
                    sid = key[len("service:"):]
                    services[key] = {
                        "ref": key, "type": "service",
                        "name": sid, "wiki_page": None,
                    }

        # Wiki에서 linked_service 매핑
        try:
            pages = self._wiki.list_pages()
            for p in pages:
                ls = p.get("linked_service", "")
                if ls and ls in services:
                    services[ls]["wiki_page"] = p.get("page_id", p.get("id", ""))
                    services[ls]["wiki_name"] = p.get("name", "")
        except Exception:
            pass

        return list(services.values())
