"""Tests for coworker.security.tool_signer."""

from coworker.security.tool_signer import (
    is_high_risk,
    sign_tool_call,
    verify_tool_call,
)


class TestToolSigner:
    def test_sign_and_verify(self):
        record = sign_tool_call(
            "ssh_execute",
            {"command": "uptime", "host": "web-01"},
            caller="agent:ops",
        )
        assert "signature" in record
        assert record["tool"] == "ssh_execute"
        assert verify_tool_call(record)

    def test_tampered_record(self):
        record = sign_tool_call("db_query", {"query": "SELECT 1"})
        record["caller"] = "attacker"
        assert not verify_tool_call(record)

    def test_custom_secret(self):
        secret = "my-custom-secret"
        record = sign_tool_call("k8s_scale", {}, secret=secret)
        assert verify_tool_call(record, secret=secret)
        assert not verify_tool_call(record, secret="wrong")

    def test_is_high_risk(self):
        assert is_high_risk("ssh_execute")
        assert is_high_risk("docker_restart")
        assert is_high_risk("db_write")
        assert not is_high_risk("metrics_latest")
        assert not is_high_risk("healthcheck_list")

    def test_args_hash_deterministic(self):
        r1 = sign_tool_call("test", {"a": 1, "b": 2})
        r2 = sign_tool_call("test", {"b": 2, "a": 1})
        assert r1["args_hash"] == r2["args_hash"]
