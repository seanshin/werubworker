"""Tests for coworker.security.sign_bridge."""

from __future__ import annotations

import pytest

from coworker.security.sign_bridge import AnchorResult, SignBridge


class TestSignBridgeInit:
    def test_default_url(self):
        bridge = SignBridge()
        assert "4100" in bridge._base

    def test_custom_url(self):
        bridge = SignBridge(base_url="http://localhost:9999/v1/")
        assert bridge._base == "http://localhost:9999/v1"

    def test_api_key(self):
        bridge = SignBridge(api_key="test-key")
        headers = bridge._headers()
        assert headers["x-api-key"] == "test-key"

    def test_no_api_key(self):
        bridge = SignBridge(api_key="")
        headers = bridge._headers()
        assert "x-api-key" not in headers


class TestAnchorResult:
    def test_success(self):
        r = AnchorResult(ok=True, anchor_id="abc-123")
        assert r.ok
        assert r.anchor_id == "abc-123"

    def test_failure(self):
        r = AnchorResult(ok=False, error="connection refused")
        assert not r.ok
        assert r.error == "connection refused"


@pytest.mark.asyncio
async def test_submit_anchor_network_error():
    """Sign 서비스 미가동 시 graceful failure."""
    bridge = SignBridge(base_url="http://127.0.0.1:1/v1")
    result = await bridge.submit_anchor("deadbeef" * 8)
    assert not result.ok
    assert result.error  # Should contain error message


@pytest.mark.asyncio
async def test_verify_anchor_network_error():
    bridge = SignBridge(base_url="http://127.0.0.1:1/v1")
    result = await bridge.verify_anchor("nonexistent")
    assert not result["ok"]


@pytest.mark.asyncio
async def test_list_anchors_network_error():
    bridge = SignBridge(base_url="http://127.0.0.1:1/v1")
    result = await bridge.list_anchors()
    assert not result["ok"]
