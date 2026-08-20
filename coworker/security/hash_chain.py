"""SHA-256 based hash chain for audit log tamper detection.

Each audit record includes a hash computed from its own fields plus the
hash of the previous record, forming an append-only chain. Modifying or
deleting any record breaks the chain from that point forward.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Sequence

GENESIS_HASH = "0" * 64


class HashChain:
    """Append-only SHA-256 hash chain calculator."""

    @staticmethod
    def compute_hash(prev_hash: str, *fields: Any) -> str:
        """Compute SHA-256 hash linking to the previous record.

        Args:
            prev_hash: Hash of the previous record (GENESIS_HASH for first).
            *fields: Field values to include in the hash.

        Returns:
            64-character hex digest.
        """
        payload = prev_hash + "|" + "|".join(str(f) for f in fields)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def verify_chain(
        entries: Sequence[dict[str, Any]],
        hash_key: str = "hash",
        prev_hash_key: str = "prev_hash",
        field_keys: Sequence[str] = (),
    ) -> tuple[bool, int | None]:
        """Verify the integrity of a hash chain.

        Args:
            entries: Audit records in chronological order.
            hash_key: Name of the hash field in each entry.
            prev_hash_key: Name of the previous-hash field.
            field_keys: Field names used in hash computation.

        Returns:
            (True, None) if the chain is intact.
            (False, index) if broken at the given index.
        """
        if not entries:
            return True, None

        # Skip legacy records without hash values
        start = 0
        for i, entry in enumerate(entries):
            if entry.get(hash_key):
                start = i
                break
        else:
            # No hashed records at all — nothing to verify
            return True, None

        expected_prev = GENESIS_HASH
        for i in range(start, len(entries)):
            entry = entries[i]
            stored_prev = entry.get(prev_hash_key, "")
            stored_hash = entry.get(hash_key, "")

            if stored_prev != expected_prev:
                return False, i

            if field_keys:
                fields = [entry.get(k, "") for k in field_keys]
                recomputed = HashChain.compute_hash(stored_prev, *fields)
                if recomputed != stored_hash:
                    return False, i

            expected_prev = stored_hash

        return True, None

    @staticmethod
    def verify_chain_streaming(
        rows: Iterable[dict[str, Any]],
        hash_key: str = "hash",
        prev_hash_key: str = "prev_hash",
        field_keys: Sequence[str] = (),
        start_hash: str = GENESIS_HASH,
    ) -> tuple[bool, int | None]:
        """Verify hash chain integrity using streaming iteration.

        Unlike verify_chain(), this does not load all entries into memory.
        Suitable for large datasets (100K+ records) with O(1) memory.

        ``start_hash`` is the hash the first row must link back to. It defaults
        to the genesis value, but a store that has pruned its oldest records
        passes the anchor saved at prune time — otherwise verification would
        fail at row 0 because the record it chains from no longer exists.
        """
        expected_prev = start_hash
        started = False
        idx = 0

        for entry in rows:
            stored_hash = entry.get(hash_key, "")
            if not started:
                if not stored_hash:
                    idx += 1
                    continue
                started = True

            stored_prev = entry.get(prev_hash_key, "")

            if stored_prev != expected_prev:
                return False, idx

            if field_keys:
                fields = [entry.get(k, "") for k in field_keys]
                recomputed = HashChain.compute_hash(stored_prev, *fields)
                if recomputed != stored_hash:
                    return False, idx

            expected_prev = stored_hash
            idx += 1

        return True, None
