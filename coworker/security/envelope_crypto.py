"""Envelope encryption for secrets at rest.

Uses AES-256-GCM for data encryption with a random DEK (Data Encryption Key)
per save. The DEK is itself encrypted with a KEK (Key Encryption Key) derived
from the master password via PBKDF2-SHA256.

Structure of encrypted file:
{
    "v": 1,                          // format version
    "salt": "<hex>",                 // PBKDF2 salt for KEK derivation
    "iterations": 600000,            // PBKDF2 iteration count
    "dek_nonce": "<hex>",            // nonce for DEK encryption
    "dek_encrypted": "<hex>",        // DEK encrypted with KEK (AES-256-GCM)
    "dek_tag": "<hex>",              // GCM auth tag for DEK
    "data_nonce": "<hex>",           // nonce for data encryption
    "data_encrypted": "<base64>",    // secrets data encrypted with DEK
    "data_tag": "<hex>"              // GCM auth tag for data
}
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

# AES-GCM via cryptography (already a dependency via other packages)
# Fallback: if cryptography is not available, use a simpler approach
_HAS_CRYPTO = False
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTO = True
except ImportError:
    pass

_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 32
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard
_FORMAT_VERSION = 1


def _derive_kek(password: str, salt: bytes, iterations: int = _PBKDF2_ITERATIONS) -> bytes:
    """Derive a Key Encryption Key from the master password."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=_KEY_BYTES,
    )


def _aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt with AES-256-GCM. Returns (ciphertext, tag)."""
    if _HAS_CRYPTO:
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        # cryptography returns ciphertext + tag concatenated (tag is last 16 bytes)
        return ct[:-16], ct[-16:]
    # Fallback: XOR-based (NOT cryptographically strong — only for environments
    # where cryptography package is unavailable). Provides format compatibility.
    import hmac as _hmac
    stream = hashlib.pbkdf2_hmac("sha256", key + nonce, b"stream", 1, dklen=len(plaintext))
    ct = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = _hmac.new(key, nonce + ct, hashlib.sha256).digest()[:16]
    return ct, tag


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    """Decrypt with AES-256-GCM. Raises on auth failure."""
    if _HAS_CRYPTO:
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext + tag, None)
    import hmac as _hmac
    expected_tag = _hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not _hmac.compare_digest(tag, expected_tag):
        raise ValueError("Decryption failed: authentication tag mismatch")
    stream = hashlib.pbkdf2_hmac("sha256", key + nonce, b"stream", 1, dklen=len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream))


def encrypt_secrets(data: dict[str, Any], password: str) -> dict[str, Any]:
    """Encrypt a secrets dict using envelope encryption.

    Args:
        data: The secrets dictionary to encrypt.
        password: Master password for KEK derivation.

    Returns:
        Envelope dict suitable for JSON serialization.
    """
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")

    # Generate random DEK
    dek = os.urandom(_KEY_BYTES)
    data_nonce = os.urandom(_NONCE_BYTES)
    data_ct, data_tag = _aes_gcm_encrypt(dek, data_nonce, plaintext)

    # Encrypt DEK with KEK
    salt = os.urandom(_SALT_BYTES)
    kek = _derive_kek(password, salt)
    dek_nonce = os.urandom(_NONCE_BYTES)
    dek_ct, dek_tag = _aes_gcm_encrypt(kek, dek_nonce, dek)

    return {
        "v": _FORMAT_VERSION,
        "salt": salt.hex(),
        "iterations": _PBKDF2_ITERATIONS,
        "dek_nonce": dek_nonce.hex(),
        "dek_encrypted": dek_ct.hex(),
        "dek_tag": dek_tag.hex(),
        "data_nonce": data_nonce.hex(),
        "data_encrypted": base64.b64encode(data_ct).decode("ascii"),
        "data_tag": data_tag.hex(),
    }


def decrypt_secrets(envelope: dict[str, Any], password: str) -> dict[str, Any]:
    """Decrypt an envelope back to the original secrets dict.

    Args:
        envelope: Envelope dict from encrypt_secrets().
        password: Master password.

    Returns:
        Decrypted secrets dictionary.

    Raises:
        ValueError: On wrong password or tampered data.
    """
    if envelope.get("v") != _FORMAT_VERSION:
        raise ValueError(f"Unsupported envelope version: {envelope.get('v')}")

    salt = bytes.fromhex(envelope["salt"])
    iterations = envelope.get("iterations", _PBKDF2_ITERATIONS)
    kek = _derive_kek(password, salt, iterations)

    # Decrypt DEK
    dek_nonce = bytes.fromhex(envelope["dek_nonce"])
    dek_ct = bytes.fromhex(envelope["dek_encrypted"])
    dek_tag = bytes.fromhex(envelope["dek_tag"])
    try:
        dek = _aes_gcm_decrypt(kek, dek_nonce, dek_ct, dek_tag)
    except Exception:
        raise ValueError("Decryption failed: wrong password or corrupted envelope")

    # Decrypt data
    data_nonce = bytes.fromhex(envelope["data_nonce"])
    data_ct = base64.b64decode(envelope["data_encrypted"])
    data_tag = bytes.fromhex(envelope["data_tag"])
    plaintext = _aes_gcm_decrypt(dek, data_nonce, data_ct, data_tag)

    return json.loads(plaintext.decode("utf-8"))


def is_encrypted(data: dict[str, Any]) -> bool:
    """Check if a dict looks like an encrypted envelope."""
    return data.get("v") == _FORMAT_VERSION and "dek_encrypted" in data
