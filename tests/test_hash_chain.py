"""Tests for coworker.security.hash_chain."""

from coworker.security.hash_chain import GENESIS_HASH, HashChain


class TestComputeHash:
    def test_deterministic(self):
        h1 = HashChain.compute_hash(GENESIS_HASH, "a", "b")
        h2 = HashChain.compute_hash(GENESIS_HASH, "a", "b")
        assert h1 == h2

    def test_hex_64_chars(self):
        h = HashChain.compute_hash(GENESIS_HASH, "data")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_inputs_different_hashes(self):
        h1 = HashChain.compute_hash(GENESIS_HASH, "a")
        h2 = HashChain.compute_hash(GENESIS_HASH, "b")
        assert h1 != h2

    def test_prev_hash_matters(self):
        h1 = HashChain.compute_hash("aaa", "data")
        h2 = HashChain.compute_hash("bbb", "data")
        assert h1 != h2


class TestVerifyChain:
    def test_empty_chain(self):
        valid, idx = HashChain.verify_chain([])
        assert valid is True
        assert idx is None

    def test_valid_chain(self):
        entries = []
        prev = GENESIS_HASH
        for i in range(5):
            h = HashChain.compute_hash(prev, str(i))
            entries.append({"prev_hash": prev, "hash": h, "val": str(i)})
            prev = h

        valid, idx = HashChain.verify_chain(entries, field_keys=["val"])
        assert valid is True
        assert idx is None

    def test_tampered_entry(self):
        entries = []
        prev = GENESIS_HASH
        for i in range(5):
            h = HashChain.compute_hash(prev, str(i))
            entries.append({"prev_hash": prev, "hash": h, "val": str(i)})
            prev = h

        # Tamper with entry 2
        entries[2]["val"] = "TAMPERED"
        valid, idx = HashChain.verify_chain(entries, field_keys=["val"])
        assert valid is False
        assert idx == 2

    def test_broken_prev_hash_link(self):
        entries = []
        prev = GENESIS_HASH
        for i in range(3):
            h = HashChain.compute_hash(prev, str(i))
            entries.append({"prev_hash": prev, "hash": h, "val": str(i)})
            prev = h

        # Break the chain link at entry 1
        entries[1]["prev_hash"] = "bad_hash"
        valid, idx = HashChain.verify_chain(entries, field_keys=["val"])
        assert valid is False
        assert idx == 1

    def test_legacy_records_skipped(self):
        # Simulate migration: first 2 records have no hash
        entries = [
            {"prev_hash": "", "hash": "", "val": "old1"},
            {"prev_hash": "", "hash": "", "val": "old2"},
        ]
        # Then new records with hashes
        prev = GENESIS_HASH
        for i in range(3):
            h = HashChain.compute_hash(prev, f"new{i}")
            entries.append({"prev_hash": prev, "hash": h, "val": f"new{i}"})
            prev = h

        valid, idx = HashChain.verify_chain(entries, field_keys=["val"])
        assert valid is True

    def test_all_legacy_records(self):
        entries = [
            {"prev_hash": "", "hash": "", "val": "old"},
        ]
        valid, idx = HashChain.verify_chain(entries, field_keys=["val"])
        assert valid is True
        assert idx is None
