"""Tests for coworker.security.envelope_crypto."""

import pytest

from coworker.security.envelope_crypto import (
    decrypt_secrets,
    encrypt_secrets,
    is_encrypted,
)


class TestEnvelopeCrypto:
    def test_roundtrip(self):
        data = {"openai": {"api_key": "sk-test123"}, "slack": {"token": "xoxb-abc"}}
        password = "master-password"
        envelope = encrypt_secrets(data, password)
        decrypted = decrypt_secrets(envelope, password)
        assert decrypted == data

    def test_wrong_password(self):
        data = {"key": "value"}
        envelope = encrypt_secrets(data, "correct")
        with pytest.raises(ValueError):
            decrypt_secrets(envelope, "wrong")

    def test_is_encrypted(self):
        envelope = encrypt_secrets({"a": 1}, "pw")
        assert is_encrypted(envelope)

    def test_is_not_encrypted(self):
        assert not is_encrypted({"profile": "openai", "api_key": "sk-test"})
        assert not is_encrypted({})

    def test_different_encryptions(self):
        """Same data, same password -> different ciphertext (random DEK/nonce)."""
        data = {"key": "value"}
        e1 = encrypt_secrets(data, "pw")
        e2 = encrypt_secrets(data, "pw")
        assert e1["data_encrypted"] != e2["data_encrypted"]

    def test_empty_data(self):
        envelope = encrypt_secrets({}, "pw")
        assert decrypt_secrets(envelope, "pw") == {}

    def test_unicode_data(self):
        data = {"name": "한국어 데이터", "emoji": "🔐"}
        envelope = encrypt_secrets(data, "password")
        assert decrypt_secrets(envelope, "password") == data

    def test_version_check(self):
        envelope = encrypt_secrets({"a": 1}, "pw")
        envelope["v"] = 99
        with pytest.raises(ValueError, match="Unsupported"):
            decrypt_secrets(envelope, "pw")


class TestSecretStoreEncryption:
    def test_enable_encryption(self, tmp_path):
        from coworker.secrets import SecretStore

        store = SecretStore(path=tmp_path / "secrets.json")
        store.put("openai", {"api_key": "sk-test123"})

        # Before encryption — plaintext
        assert not store.is_encrypted()

        # Enable encryption
        store.enable_encryption("master-pw")
        assert store.is_encrypted()

        # Read back
        data = store.get("openai")
        assert data is not None
        assert data["api_key"] == "sk-test123"

    def test_encrypted_store_without_password(self, tmp_path):
        from coworker.secrets import SecretStore

        # Write encrypted
        store1 = SecretStore(path=tmp_path / "secrets.json", encryption_password="pw")
        store1.put("test", {"key": "value"})

        # Read without password — should return empty
        store2 = SecretStore(path=tmp_path / "secrets.json")
        assert store2.get("test") is None

    def test_encrypted_store_with_password(self, tmp_path):
        from coworker.secrets import SecretStore

        store1 = SecretStore(path=tmp_path / "secrets.json", encryption_password="pw")
        store1.put("test", {"key": "value"})

        store2 = SecretStore(path=tmp_path / "secrets.json", encryption_password="pw")
        data = store2.get("test")
        assert data is not None
        assert data["key"] == "value"
