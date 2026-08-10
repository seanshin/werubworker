"""Vault — encrypted credentials store.

If unlocked (master password set), values are encrypted with Fernet (PBKDF2-derived key).
If no master password has ever been set, values are stored in plaintext — matching the
existing secrets.json behaviour. The encryption layer activates when the user first calls
``unlock()`` with a password.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


_AUDIT_MAX_ENTRIES = 1000


def _audit_log_path() -> Path:
    return Path.home() / ".config" / "werubworker" / "audit.log"


def _write_audit(action: str, key_name: str) -> None:
    """Append a single audit entry and trim the file to *_AUDIT_MAX_ENTRIES* lines."""
    path = _audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    entry = f"{ts}  {action}  {key_name}\n"
    try:
        # Append first, then trim if needed.
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
        # Trim to last N entries.
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > _AUDIT_MAX_ENTRIES:
            path.write_text("".join(lines[-_AUDIT_MAX_ENTRIES:]), encoding="utf-8")
    except OSError:
        pass  # best-effort; never break vault operations for logging


class Vault:
    """Encrypted (optional) credentials vault backed by a JSON file."""

    def __init__(self, data_dir: Path):
        self._vault_file = data_dir / "vault.json"
        self._salt_file = data_dir / "vault.salt"
        self._fernet: Any | None = None  # set on unlock
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lock / Unlock
    # ------------------------------------------------------------------

    def unlock(self, master_password: str) -> dict:
        """Derive encryption key from master password using PBKDF2."""
        if not _HAS_CRYPTO:
            return {"ok": False, "error": "cryptography package not installed"}
        salt = self._load_or_create_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))
        self._fernet = Fernet(key)
        # Re-encrypt any plaintext entries that exist
        self._migrate_plaintext()
        return {"ok": True}

    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def lock(self) -> dict:
        self._fernet = None
        return {"ok": True}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def store(
        self,
        key: str,
        value: str,
        expires: str = "",
        rotate_days: int = 0,
        linked_docs: list | None = None,
        linked_services: list | None = None,
    ) -> dict:
        """Encrypt (if unlocked) and store a credential."""
        with self._lock:
            data = self._read()
            encrypted_value = self._encrypt(value)
            entry: dict[str, Any] = {
                "value": encrypted_value,
                "encrypted": self.is_unlocked(),
                "expires": expires,
                "rotate_days": rotate_days,
                "linked_docs": linked_docs or [],
                "linked_services": linked_services or [],
                "created_at": time.time(),
                "updated_at": time.time(),
                "history": [],
            }
            # Preserve history from previous entry
            if key in data:
                entry["history"] = data[key].get("history", [])
            data[key] = entry
            self._write(data)
        _write_audit("store", key)
        return {"ok": True, "key": key}

    def retrieve(self, key: str) -> str:
        """Decrypt and return credential value. Raises if locked and value is encrypted."""
        data = self._read()
        entry = data.get(key)
        if entry is None:
            raise KeyError(f"credential '{key}' not found in vault")
        raw = entry["value"]
        _write_audit("retrieve", key)
        if entry.get("encrypted", False):
            if not self.is_unlocked():
                raise RuntimeError("vault is locked — unlock with master password first")
            return self._decrypt(raw)
        return raw

    def list_entries(self) -> list[dict]:
        """Return metadata only (no decrypted values)."""
        data = self._read()
        entries = []
        for key, entry in data.items():
            entries.append(
                {
                    "key": key,
                    "encrypted": entry.get("encrypted", False),
                    "expires": entry.get("expires", ""),
                    "rotate_days": entry.get("rotate_days", 0),
                    "linked_docs": entry.get("linked_docs", []),
                    "linked_services": entry.get("linked_services", []),
                    "created_at": entry.get("created_at", 0),
                    "updated_at": entry.get("updated_at", 0),
                    "history_count": len(entry.get("history", [])),
                }
            )
        return entries

    def delete(self, key: str) -> dict:
        with self._lock:
            data = self._read()
            if key not in data:
                return {"ok": False, "error": f"credential '{key}' not found"}
            del data[key]
            self._write(data)
        return {"ok": True, "key": key}

    def rotate(self, key: str, new_value: str) -> dict:
        """Store new value, keep previous in history."""
        with self._lock:
            data = self._read()
            entry = data.get(key)
            if entry is None:
                return {"ok": False, "error": f"credential '{key}' not found"}
            # Push current value to history
            history = entry.get("history", [])
            history.append(
                {
                    "value": entry["value"],
                    "encrypted": entry.get("encrypted", False),
                    "rotated_at": time.time(),
                }
            )
            entry["history"] = history
            entry["value"] = self._encrypt(new_value)
            entry["encrypted"] = self.is_unlocked()
            entry["updated_at"] = time.time()
            data[key] = entry
            self._write(data)
        _write_audit("rotate", key)
        return {"ok": True, "key": key, "history_count": len(history)}

    def check_expiring(self, days: int = 30) -> list[dict]:
        """Credentials expiring within N days."""
        from datetime import datetime, timedelta

        cutoff = (datetime.now() + timedelta(days=days)).isoformat()[:10]
        data = self._read()
        expiring = []
        for key, entry in data.items():
            exp = entry.get("expires", "")
            if exp and exp <= cutoff:
                expiring.append(
                    {
                        "key": key,
                        "expires": exp,
                        "expired": exp <= datetime.now().isoformat()[:10],
                        "linked_docs": entry.get("linked_docs", []),
                        "linked_services": entry.get("linked_services", []),
                    }
                )
        return expiring

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _encrypt(self, value: str) -> str:
        if self._fernet is not None:
            return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return value

    def _decrypt(self, value: str) -> str:
        if self._fernet is None:
            return value
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception:
            raise RuntimeError("failed to decrypt — wrong master password?")

    def _load_or_create_salt(self) -> bytes:
        if self._salt_file.is_file():
            return self._salt_file.read_bytes()
        salt = os.urandom(16)
        self._salt_file.parent.mkdir(parents=True, exist_ok=True)
        self._salt_file.write_bytes(salt)
        return salt

    def _migrate_plaintext(self) -> None:
        """Re-encrypt any plaintext entries now that we have a key."""
        data = self._read()
        changed = False
        for key, entry in data.items():
            if not entry.get("encrypted", False) and self._fernet is not None:
                entry["value"] = self._encrypt(entry["value"])
                entry["encrypted"] = True
                changed = True
        if changed:
            self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self._vault_file.is_file():
            return {}
        try:
            return json.loads(self._vault_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self._vault_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._vault_file.with_name(self._vault_file.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._vault_file)
