"""Tests for coworker.security.hmac_signer."""

import time

from coworker.security.hmac_signer import (
    build_webhook_headers,
    generate_secret,
    sign_payload,
    verify_signature,
    verify_webhook_headers,
)


class TestSignAndVerify:
    def test_roundtrip_bytes(self):
        secret = generate_secret()
        payload = b'{"event": "test"}'
        sig = sign_payload(payload, secret)
        assert verify_signature(payload, secret, sig)

    def test_roundtrip_str(self):
        secret = "my-secret"
        payload = "hello world"
        sig = sign_payload(payload, secret)
        assert verify_signature(payload, secret, sig)

    def test_roundtrip_dict(self):
        secret = "s3cret"
        payload = {"action": "deploy", "target": "prod"}
        sig = sign_payload(payload, secret)
        assert verify_signature(payload, secret, sig)

    def test_wrong_secret_fails(self):
        sig = sign_payload(b"data", "correct-secret")
        assert not verify_signature(b"data", "wrong-secret", sig)

    def test_tampered_payload_fails(self):
        secret = "key"
        sig = sign_payload(b"original", secret)
        assert not verify_signature(b"tampered", secret, sig)

    def test_deterministic(self):
        secret = "k"
        sig1 = sign_payload(b"data", secret)
        sig2 = sign_payload(b"data", secret)
        assert sig1 == sig2


class TestGenerateSecret:
    def test_length(self):
        s = generate_secret()
        assert len(s) > 20

    def test_unique(self):
        assert generate_secret() != generate_secret()


class TestWebhookHeaders:
    def test_has_required_headers(self):
        headers = build_webhook_headers(b"payload", "secret", event_type="push")
        assert "X-Signature-256" in headers
        assert headers["X-Signature-256"].startswith("sha256=")
        assert "X-Event-Id" in headers
        assert "X-Timestamp" in headers
        assert headers["X-Event-Type"] == "push"

    def test_custom_event_id(self):
        headers = build_webhook_headers(b"p", "s", event_id="my-id-123")
        assert headers["X-Event-Id"] == "my-id-123"


class TestVerifyWebhookHeaders:
    def test_valid(self):
        secret = "test-secret"
        payload = b'{"ok": true}'
        headers = build_webhook_headers(payload, secret)
        valid, err = verify_webhook_headers(payload, secret, headers)
        assert valid
        assert err == ""

    def test_bad_signature(self):
        headers = {
            "X-Signature-256": "sha256=deadbeef",
            "X-Timestamp": str(int(time.time())),
        }
        valid, err = verify_webhook_headers(b"data", "secret", headers)
        assert not valid
        assert "mismatch" in err.lower()

    def test_missing_header(self):
        valid, err = verify_webhook_headers(b"data", "secret", {})
        assert not valid
        assert "Missing" in err

    def test_replay_protection(self):
        secret = "s"
        payload = b"data"
        headers = build_webhook_headers(payload, secret)
        # Fake an old timestamp
        headers["X-Timestamp"] = str(int(time.time()) - 600)
        valid, err = verify_webhook_headers(payload, secret, headers, max_age_seconds=300)
        assert not valid
        assert "old" in err.lower()
