"""ServiceResolver — natural language service resolution via Wiki."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from coworker.wiki.resolver import ServiceResolver


@pytest.fixture
def resolver(tmp_path):
    """Resolver with mock wiki_store and secrets."""
    mock_wiki = MagicMock()
    mock_secrets = MagicMock()
    return ServiceResolver(mock_wiki, mock_secrets)


def test_resolve_natural_found(resolver):
    resolver._wiki.search_fts.return_value = [
        {"page_id": "db-prod", "name": "DB: production",
         "linked_service": "database:prod", "category": "database"},
    ]
    resolver._secrets.get.return_value = {
        "type": "postgresql", "host": "10.0.1.10", "port": 5432,
        "user": "app", "password": "secret123",
    }
    result = resolver.resolve_natural("production DB")
    assert result["ok"]
    assert result["page_id"] == "db-prod"
    assert result["linked_service"] == "database:prod"
    # password should be stripped
    assert "password" not in (result.get("config") or {})


def test_resolve_natural_not_found(resolver):
    resolver._wiki.search_fts.return_value = []
    result = resolver.resolve_natural("nonexistent service")
    assert not result["ok"]


def test_resolve_natural_page_without_config(resolver):
    resolver._wiki.search_fts.return_value = [
        {"page_id": "svc-api", "name": "API 서비스",
         "linked_service": "", "category": "service"},
    ]
    result = resolver.resolve_natural("API")
    assert result["ok"]
    assert result["config"] is None


def test_get_connection_context(resolver):
    resolver._wiki.get_page.return_value = {
        "page_id": "server-web-01", "name": "서버: web-01",
        "category": "server", "linked_service": "ssh:server:web-01",
        "structured_data": {"host": "10.0.1.1", "port": 22},
        "credentials": [{"key": "ssh_key", "type": "ssh_key"}],
    }
    resolver._wiki.list_pages.return_value = [
        {"page_id": "deploy-api", "name": "배포 런북", "category": "runbook",
         "linked_service": "ssh:server:web-01"},
    ]
    result = resolver.get_connection_context("server-web-01")
    assert result["ok"]
    assert result["structured_data"]["host"] == "10.0.1.1"
    assert "ssh_key" in result["credentials"]


def test_get_connection_context_not_found(resolver):
    resolver._wiki.get_page.return_value = None
    result = resolver.get_connection_context("nonexistent")
    assert not result["ok"]


def test_list_services_with_wiki(resolver):
    resolver._secrets.status.return_value = [
        {"profile": "ssh:server:web-01"},
        {"profile": "database:prod"},
    ]
    resolver._secrets.get.return_value = None
    resolver._wiki.list_pages.return_value = [
        {"page_id": "server-web-01", "name": "서버: web-01",
         "linked_service": "ssh:server:web-01"},
    ]
    services = resolver.list_services_with_wiki()
    assert len(services) == 2
    web = next(s for s in services if s["name"] == "web-01")
    assert web["wiki_page"] == "server-web-01"
