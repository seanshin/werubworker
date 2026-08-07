"""Wiki store, vault, and analyzer tests."""

from __future__ import annotations

from pathlib import Path

from coworker.wiki.store import WikiStore
from coworker.wiki.vault import Vault
from coworker.wiki.analyzer import analyze_document, _detect_category, _is_false_positive
from coworker.wiki.sync import WikiSync
from coworker.secrets import SecretStore


# ---------------------------------------------------------------------------
# WikiStore
# ---------------------------------------------------------------------------


def test_wiki_store_crud(tmp_path):
    store = WikiStore(tmp_path)

    # Create
    result = store.create_page(
        page_id="pg-01",
        name="Production DB",
        category="database",
        content="PostgreSQL host: 10.0.0.5, port 5432",
        tags=["production", "database"],
        updated_by="test",
    )
    assert result["ok"] is True
    assert result["version"] == 1

    # Read
    page = store.get_page("pg-01")
    assert page is not None
    assert page["name"] == "Production DB"
    assert page["category"] == "database"
    assert page["content"].startswith("PostgreSQL")
    assert "production" in page["tags"]

    # Update
    result = store.update_page("pg-01", content="Updated content", change_note="fix typo")
    assert result["ok"] is True
    assert result["version"] == 2

    page = store.get_page("pg-01")
    assert page["content"] == "Updated content"
    assert page["version"] == 2

    # List
    pages = store.list_pages()
    assert len(pages) == 1
    assert pages[0]["page_id"] == "pg-01"

    # Delete
    result = store.delete_page("pg-01")
    assert result["ok"] is True
    assert store.get_page("pg-01") is None


def test_wiki_store_delete_nonexistent(tmp_path):
    store = WikiStore(tmp_path)
    result = store.delete_page("nonexistent")
    assert result["ok"] is False


def test_wiki_store_update_nonexistent(tmp_path):
    store = WikiStore(tmp_path)
    result = store.update_page("nonexistent", content="new")
    assert result["ok"] is False


def test_wiki_store_history(tmp_path):
    store = WikiStore(tmp_path)
    store.create_page("pg-02", "Test Page", "general", "v1 content")
    store.update_page("pg-02", content="v2 content", change_note="second edit")
    store.update_page("pg-02", content="v3 content", change_note="third edit")

    history = store.get_history("pg-02")
    assert len(history) == 3
    assert history[0]["version"] == 3  # most recent first
    assert history[2]["version"] == 1

    # Get specific version
    v2 = store.get_version("pg-02", 2)
    assert v2 is not None
    assert v2["content"] == "v2 content"

    # Non-existent version
    assert store.get_version("pg-02", 99) is None


def test_wiki_store_categories(tmp_path):
    store = WikiStore(tmp_path)
    store.create_page("p1", "A", "database", "content")
    store.create_page("p2", "B", "database", "content")
    store.create_page("p3", "C", "server", "content")

    cats = store.categories()
    assert len(cats) == 2
    db_cat = next(c for c in cats if c["category"] == "database")
    assert db_cat["count"] == 2


def test_wiki_store_list_by_category(tmp_path):
    store = WikiStore(tmp_path)
    store.create_page("p1", "A", "database", "content")
    store.create_page("p2", "B", "server", "content")

    pages = store.list_pages(category="database")
    assert len(pages) == 1
    assert pages[0]["page_id"] == "p1"


def test_wiki_store_list_by_query(tmp_path):
    store = WikiStore(tmp_path)
    store.create_page("p1", "Production DB", "database", "host is 10.0.0.5")
    store.create_page("p2", "Staging API", "api", "no db info here")

    pages = store.list_pages(query="10.0.0.5")
    assert len(pages) == 1
    assert pages[0]["page_id"] == "p1"


def test_wiki_store_alerts(tmp_path):
    store = WikiStore(tmp_path)
    store.create_page("p1", "AWS Keys", "cloud", "content")

    result = store.add_alert("p1", "api_key", "expiring", "2026-09-01")
    assert result["ok"] is True
    alert_id = result["alert_id"]

    alerts = store.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["credential_key"] == "api_key"
    assert alerts[0]["alert_type"] == "expiring"

    # Acknowledge
    store.ack_alert(alert_id)
    assert store.list_alerts() == []  # acknowledged alerts are filtered out


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------


def test_vault_store_retrieve(tmp_path):
    """Store and retrieve without encryption (no master password)."""
    vault = Vault(tmp_path)
    vault.store("db_password", "hunter2")
    assert vault.retrieve("db_password") == "hunter2"


def test_vault_store_list(tmp_path):
    vault = Vault(tmp_path)
    vault.store("key1", "val1", expires="2026-12-31")
    vault.store("key2", "val2")
    entries = vault.list_entries()
    assert len(entries) == 2
    assert entries[0]["key"] in ("key1", "key2")


def test_vault_delete(tmp_path):
    vault = Vault(tmp_path)
    vault.store("temp", "value")
    result = vault.delete("temp")
    assert result["ok"] is True
    result = vault.delete("temp")
    assert result["ok"] is False


def test_vault_rotate(tmp_path):
    vault = Vault(tmp_path)
    vault.store("api_key", "old_value")
    result = vault.rotate("api_key", "new_value")
    assert result["ok"] is True
    assert result["history_count"] == 1
    assert vault.retrieve("api_key") == "new_value"


def test_vault_rotate_not_found(tmp_path):
    vault = Vault(tmp_path)
    result = vault.rotate("nonexistent", "value")
    assert result["ok"] is False


def test_vault_retrieve_not_found(tmp_path):
    vault = Vault(tmp_path)
    try:
        vault.retrieve("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass


def test_vault_encryption(tmp_path):
    """When unlocked with a master password, values should be encrypted."""
    vault = Vault(tmp_path)
    # Store plaintext first
    vault.store("plain_key", "plain_value")
    assert vault.retrieve("plain_key") == "plain_value"

    # Unlock (enables encryption)
    result = vault.unlock("my_master_password")
    if result["ok"]:
        # Store encrypted
        vault.store("enc_key", "secret_data")
        assert vault.is_unlocked()
        assert vault.retrieve("enc_key") == "secret_data"

        # Lock and try to retrieve encrypted value
        vault.lock()
        assert not vault.is_unlocked()
        try:
            vault.retrieve("enc_key")
            assert False, "Should have raised RuntimeError"
        except RuntimeError:
            pass  # expected — vault is locked
    else:
        # cryptography package not installed, skip encryption test
        pass


def test_vault_check_expiring(tmp_path):
    vault = Vault(tmp_path)
    vault.store("expired_key", "val", expires="2020-01-01")
    vault.store("future_key", "val", expires="2099-12-31")
    expiring = vault.check_expiring(days=30)
    assert any(e["key"] == "expired_key" for e in expiring)
    assert not any(e["key"] == "future_key" for e in expiring)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


def test_wiki_analyzer_extract_hosts():
    content = "서버 IP: 192.168.1.20\nDB 서버: 10.0.0.5"
    result = analyze_document(content, "서버 목록")
    hosts = [c for c in result["credentials"] if c["pattern_name"] == "host"]
    assert len(hosts) >= 1
    values = [h["value"] for h in hosts]
    assert "192.168.1.20" in values


def test_wiki_analyzer_extract_passwords():
    content = "PostgreSQL\n비밀번호: super_secret_123\nport: 5432"
    result = analyze_document(content, "DB 설정")
    passwords = [c for c in result["credentials"] if c["pattern_name"] == "password"]
    assert len(passwords) >= 1
    assert passwords[0]["secret"] is True


def test_wiki_analyzer_extract_api_keys():
    content = "OpenAI key: sk-abcdefghij1234567890abcdefghij"
    result = analyze_document(content, "API 키")
    api_keys = [c for c in result["credentials"] if "api_key" in c["pattern_name"]]
    assert len(api_keys) >= 1
    assert api_keys[0]["secret"] is True


def test_wiki_analyzer_detect_category():
    assert _detect_category("PostgreSQL database server", "") == "database"
    assert _detect_category("AWS EC2 instance", "") == "cloud"
    assert _detect_category("SSH server access", "") == "server"
    assert _detect_category("nothing special here", "") == "general"


def test_wiki_analyzer_empty_document():
    result = analyze_document("", "")
    assert result["credentials"] == []
    assert result["summary"] == "추출 가능한 정보 없음"


def test_wiki_analyzer_false_positives():
    """Version numbers should not be detected as hosts."""
    assert _is_false_positive("1.2.3.4", "host") is True
    assert _is_false_positive("localhost", "host") is True
    assert _is_false_positive("192.168.1.20", "host") is False


# ---------------------------------------------------------------------------
# WikiSync
# ---------------------------------------------------------------------------


def test_wiki_sync_page_to_secrets(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    vault = Vault(tmp_path / "vault")
    secrets = SecretStore(tmp_path / "secrets.json")
    sync = WikiSync(wiki, vault, secrets)

    # Create a wiki page with credentials
    wiki.create_page(
        page_id="db-prod",
        name="Production DB",
        category="database",
        content="DB connection info",
        credentials=[{"key": "host"}, {"key": "password"}],
        linked_service="database:production",
    )

    # Store credential values in the vault
    vault.store("db-prod:host", "10.0.0.5")
    vault.store("db-prod:password", "secret123")

    # Sync page credentials to secrets.json
    result = sync.sync_page_to_secrets("db-prod")
    assert result["ok"] is True
    assert result["synced_keys"] == 2

    # Verify secrets were written
    profile = secrets.get("database:production")
    assert profile is not None
    assert profile["host"] == "10.0.0.5"
    assert profile["password"] == "secret123"


def test_wiki_sync_page_not_found(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    vault = Vault(tmp_path / "vault")
    secrets = SecretStore(tmp_path / "secrets.json")
    sync = WikiSync(wiki, vault, secrets)

    result = sync.sync_page_to_secrets("nonexistent")
    assert result["ok"] is False


def test_wiki_sync_secrets_to_page(tmp_path):
    wiki = WikiStore(tmp_path / "wiki")
    vault = Vault(tmp_path / "vault")
    secrets = SecretStore(tmp_path / "secrets.json")
    sync = WikiSync(wiki, vault, secrets)

    # Put a secret profile
    secrets.put("database:staging", {"type": "postgresql", "host": "staging.db.local", "password": "stg_pass"})

    # Sync to wiki
    result = sync.sync_secrets_to_page("database:staging")
    assert result["ok"] is True

    # Wiki page should exist
    pages = wiki.list_pages()
    assert len(pages) == 1
    assert pages[0]["linked_service"] == "database:staging"
