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

try:
    import argon2.low_level  # type: ignore[import-untyped]

    _HAS_ARGON2 = True
except ImportError:
    _HAS_ARGON2 = False


_AUDIT_MAX_ENTRIES = 1000
_AUDIT_LOG_RETENTION_DAYS = 30


def _audit_log_dir() -> Path:
    return Path.home() / ".config" / "werubworker"


def _audit_log_path() -> Path:
    """Legacy single-file path (kept for backward-compatible reads)."""
    return _audit_log_dir() / "audit.log"


def _audit_log_path_for_date(dt: datetime | None = None) -> Path:
    """Return the date-partitioned audit log path: audit-YYYY-MM-DD.log."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return _audit_log_dir() / f"audit-{dt.strftime('%Y-%m-%d')}.log"


def _compress_old_audit_logs() -> None:
    """Gzip audit log files older than *_AUDIT_LOG_RETENTION_DAYS*."""
    import gzip as _gzip

    log_dir = _audit_log_dir()
    if not log_dir.is_dir():
        return
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Calculate the cutoff date string
    from datetime import timedelta

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=_AUDIT_LOG_RETENTION_DAYS)).strftime(
        "%Y-%m-%d"
    )
    for p in log_dir.glob("audit-*.log"):
        # Extract date from filename: audit-YYYY-MM-DD.log
        name = p.stem  # audit-YYYY-MM-DD
        if not name.startswith("audit-") or len(name) != 16:
            continue
        file_date = name[6:]  # YYYY-MM-DD
        if file_date < cutoff_date:
            try:
                data = p.read_bytes()
                gz_path = p.with_suffix(".log.gz")
                with _gzip.open(gz_path, "wb") as gz:
                    gz.write(data)
                p.unlink()
            except OSError:
                pass


def _write_audit(action: str, key_name: str) -> None:
    """Append a single audit entry to the date-partitioned log file.

    Rotates by date (``audit-YYYY-MM-DD.log``) and compresses files older than
    30 days. A per-file trim to *_AUDIT_MAX_ENTRIES* is kept as a safety net.
    """
    now = datetime.now(timezone.utc)
    path = _audit_log_path_for_date(now)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = now.isoformat()
    entry = f"{ts}  {action}  {key_name}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
        # Trim per-file safety net.
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > _AUDIT_MAX_ENTRIES:
            path.write_text("".join(lines[-_AUDIT_MAX_ENTRIES:]), encoding="utf-8")
        # Compress old logs (best-effort, runs infrequently).
        _compress_old_audit_logs()
    except OSError:
        pass  # best-effort; never break vault operations for logging


def read_audit_entries(days: int = 7) -> list[dict]:
    """Read recent audit log entries across date-partitioned files.

    Returns a list of ``{timestamp, action, key}`` dicts, newest first.
    """
    from datetime import timedelta

    entries: list[dict] = []
    log_dir = _audit_log_dir()
    if not log_dir.is_dir():
        return entries

    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Gather from date-partitioned files.
    for p in sorted(log_dir.glob("audit-*.log"), reverse=True):
        name = p.stem
        if not name.startswith("audit-") or len(name) != 16:
            continue
        file_date_str = name[6:]
        try:
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date.date() < start_date.date():
            break
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                parts = line.split("  ", 2)
                if len(parts) >= 3:
                    entries.append(
                        {"timestamp": parts[0], "action": parts[1], "key": parts[2]}
                    )
        except OSError:
            continue

    # Also read legacy audit.log if it exists (migration period).
    legacy = _audit_log_path()
    if legacy.is_file():
        try:
            for line in legacy.read_text(encoding="utf-8").splitlines():
                parts = line.split("  ", 2)
                if len(parts) >= 3:
                    ts = parts[0]
                    try:
                        entry_dt = datetime.fromisoformat(ts)
                        if entry_dt < start_date:
                            continue
                    except ValueError:
                        pass
                    entries.append(
                        {"timestamp": ts, "action": parts[1], "key": parts[2]}
                    )
        except OSError:
            pass

    # Sort newest first.
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries


_MIN_MASTER_LEN = 12
_MAX_UNLOCK_ATTEMPTS = 5
_LOCKOUT_SECONDS = 30

log = logging.getLogger(__name__)


def _validate_master_password(password: str) -> str | None:
    """Return error message if password is too weak, else None."""
    if len(password) < _MIN_MASTER_LEN:
        return f"Master password must be at least {_MIN_MASTER_LEN} characters"
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_upper and has_lower and has_digit):
        return "Master password must contain uppercase, lowercase, and digit"
    return None


class Vault:
    """Encrypted (optional) credentials vault backed by a JSON file."""

    def __init__(self, data_dir: Path):
        self._vault_file = data_dir / "vault.json"
        self._salt_file = data_dir / "vault.salt"
        self._kdf_file = data_dir / "vault.kdf"  # tracks KDF type ("argon2id" or "pbkdf2")
        self._fernet: Any | None = None  # set on unlock
        self._lock = threading.Lock()
        self._failed_attempts = 0
        self._lockout_until: float = 0.0
        self._last_access: float = time.monotonic()

    # ------------------------------------------------------------------
    # Lock / Unlock
    # ------------------------------------------------------------------

    def _derive_key_argon2(self, password: str, salt: bytes) -> bytes:
        """Derive a 32-byte key using Argon2id (low-level, raw output)."""
        raw = argon2.low_level.hash_secret_raw(
            password.encode("utf-8"),
            salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            type=argon2.low_level.Type.ID,
        )
        return base64.urlsafe_b64encode(raw)

    def _derive_key_pbkdf2(self, password: str, salt: bytes) -> bytes:
        """Derive a 32-byte key using PBKDF2-HMAC-SHA256 (600k iterations)."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))

    def _read_kdf_marker(self) -> str:
        """Read stored KDF type. Returns 'argon2id', 'pbkdf2', or '' (unknown)."""
        try:
            if self._kdf_file.is_file():
                return self._kdf_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    def _write_kdf_marker(self, kdf_type: str) -> None:
        """Persist the KDF type used for this vault."""
        try:
            self._kdf_file.parent.mkdir(parents=True, exist_ok=True)
            self._kdf_file.write_text(kdf_type, encoding="utf-8")
        except OSError:
            pass

    def unlock(self, master_password: str) -> dict:
        """Derive encryption key from master password using Argon2id (preferred) or PBKDF2."""
        if not _HAS_CRYPTO:
            return {"ok": False, "error": "cryptography package not installed"}
        # Brute-force protection
        now = time.monotonic()
        if now < self._lockout_until:
            remaining = int(self._lockout_until - now) + 1
            return {"ok": False, "error": f"Too many attempts. Retry in {remaining}s"}
        # Password policy (only enforced on first-time setup, not on re-unlock)
        is_new_vault = not self._salt_file.exists()
        if is_new_vault:
            err = _validate_master_password(master_password)
            if err:
                return {"ok": False, "error": err}
        salt = self._load_or_create_salt()
        stored_kdf = self._read_kdf_marker()

        # Determine derivation order: try the stored KDF first, then fallback.
        # For new vaults: prefer argon2id if available.
        if is_new_vault:
            kdf_type = "argon2id" if _HAS_ARGON2 else "pbkdf2"
            if kdf_type == "argon2id":
                key = self._derive_key_argon2(master_password, salt)
            else:
                key = self._derive_key_pbkdf2(master_password, salt)
            fernet = Fernet(key)
            self._failed_attempts = 0
            self._fernet = fernet
            self._write_kdf_marker(kdf_type)
            self._migrate_plaintext()
            _write_audit("unlock_success", f"vault:kdf={kdf_type}")
            return {"ok": True, "kdf": kdf_type}

        # Existing vault — build derivation attempts in order of likelihood.
        attempts: list[tuple[str, bytes]] = []
        if stored_kdf == "argon2id" and _HAS_ARGON2:
            attempts.append(("argon2id", self._derive_key_argon2(master_password, salt)))
            attempts.append(("pbkdf2", self._derive_key_pbkdf2(master_password, salt)))
        elif stored_kdf == "pbkdf2":
            attempts.append(("pbkdf2", self._derive_key_pbkdf2(master_password, salt)))
            if _HAS_ARGON2:
                attempts.append(("argon2id", self._derive_key_argon2(master_password, salt)))
        else:
            # No marker — legacy vault, try PBKDF2 first then argon2id.
            attempts.append(("pbkdf2", self._derive_key_pbkdf2(master_password, salt)))
            if _HAS_ARGON2:
                attempts.append(("argon2id", self._derive_key_argon2(master_password, salt)))

        # Check if vault has encrypted entries to verify against.
        data = self._read()
        has_encrypted = any(
            e.get("encrypted") and e.get("value") for e in data.values()
        )

        if not has_encrypted:
            # No encrypted entries — any key works; use the preferred KDF.
            kdf_type, key = attempts[0]
            fernet = Fernet(key)
            self._failed_attempts = 0
            self._fernet = fernet
            self._write_kdf_marker(kdf_type)
            self._migrate_plaintext()
            _write_audit("unlock_success", f"vault:kdf={kdf_type}")
            return {"ok": True, "kdf": kdf_type}

        # Try each derivation to see which one decrypts existing data.
        sample_value: str = ""
        for entry in data.values():
            if entry.get("encrypted") and entry.get("value"):
                sample_value = entry["value"]
                break

        for kdf_type, key in attempts:
            fernet = Fernet(key)
            try:
                fernet.decrypt(sample_value.encode("utf-8"))
            except (InvalidToken, Exception):
                continue
            # Success with this KDF.
            self._failed_attempts = 0
            self._fernet = fernet
            self._write_kdf_marker(kdf_type)
            self._migrate_plaintext()
            _write_audit("unlock_success", f"vault:kdf={kdf_type}")
            return {"ok": True, "kdf": kdf_type}

        # All derivations failed — wrong password.
        self._failed_attempts += 1
        _write_audit("unlock_failed", f"attempt={self._failed_attempts}")
        log.warning("Vault unlock failed (attempt %d)", self._failed_attempts)
        if self._failed_attempts >= _MAX_UNLOCK_ATTEMPTS:
            self._lockout_until = time.monotonic() + _LOCKOUT_SECONDS
            self._failed_attempts = 0
            return {"ok": False, "error": f"Too many failed attempts. Locked for {_LOCKOUT_SECONDS}s"}
        return {"ok": False, "error": "Wrong master password"}

    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def lock(self) -> dict:
        self._fernet = None
        return {"ok": True}

    def check_idle(self, timeout_sec: int = 1800) -> bool:
        """Lock the vault if idle for more than *timeout_sec* seconds (default 30 min).

        Returns True if the vault was locked due to inactivity.
        """
        if not self.is_unlocked():
            return False
        if time.monotonic() - self._last_access > timeout_sec:
            self.lock()
            _write_audit("auto_lock", "idle_timeout")
            return True
        return False

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
        self._last_access = time.monotonic()
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
        self._last_access = time.monotonic()
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

    def change_master(self, old_password: str, new_password: str) -> dict:
        """Change master password — re-encrypts all vault entries."""
        if not _HAS_CRYPTO:
            return {"ok": False, "error": "cryptography package not installed"}
        # Validate new password
        err = _validate_master_password(new_password)
        if err:
            return {"ok": False, "error": err}
        # Verify old password by attempting unlock
        old_result = self.unlock(old_password)
        if not old_result.get("ok"):
            return {"ok": False, "error": "Current password is incorrect"}
        # Decrypt all entries with old key
        data = self._read()
        decrypted: dict[str, str] = {}
        for key, entry in data.items():
            if entry.get("encrypted") and entry.get("value"):
                try:
                    decrypted[key] = self._decrypt(entry["value"])
                except Exception:
                    pass
        # Generate new salt and key
        new_salt = os.urandom(16)
        self._salt_file.write_bytes(new_salt)
        # Use best available KDF for the new key
        kdf_type = "argon2id" if _HAS_ARGON2 else "pbkdf2"
        if kdf_type == "argon2id":
            new_key = self._derive_key_argon2(new_password, new_salt)
        else:
            new_key = self._derive_key_pbkdf2(new_password, new_salt)
        self._fernet = Fernet(new_key)
        self._write_kdf_marker(kdf_type)
        # Re-encrypt all entries
        for key, plaintext in decrypted.items():
            data[key]["value"] = self._encrypt(plaintext)
        self._write(data)
        _write_audit("change_master", "vault")
        return {"ok": True, "re_encrypted": len(decrypted)}

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
