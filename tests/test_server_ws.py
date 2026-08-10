"""Server WebSocket tests — split from test_server.py for maintainability."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
from coworker.server import SessionManager, create_app
from coworker.sessions import SessionRecord
from conftest import ScriptedProvider, _client, _drain, _text, _tool

# -- WebSocket ------------------------------------------------------------------


def test_ws_simple_turn(tmp_path):
    client = _client(tmp_path, [_text("done thinking")])
    with client.websocket_connect("/ws/session/s1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        types = _drain(ws)
        assert "assistant_message" in types
        assert "turn_end" in types


def test_ws_rejects_oversized_message(tmp_path):
    from coworker.attachments import MAX_ATTACHMENTS
    from coworker.server import app as app_mod

    client = _client(tmp_path, [_text("should not run")])
    with client.websocket_connect("/ws/session/big") as ws:
        assert ws.receive_json()["type"] == "ready"

        # Oversized text → single input-rejected frame, no turn runs.
        ws.send_json({"type": "user_message", "text": "x" * (app_mod._MAX_MESSAGE_TEXT_CHARS + 1)})
        evt = ws.receive_json()
        assert evt["type"] == "input_rejected"
        assert "too long" in evt["data"]["error"].lower()

        # The ingress cap is the same cap the attachment builder enforces.
        assert app_mod._MAX_ATTACHMENTS == MAX_ATTACHMENTS
        ws.send_json(
            {
                "type": "user_message",
                "text": "hi",
                "attachments": ["a"] * (app_mod._MAX_ATTACHMENTS + 1),
            }
        )
        evt = ws.receive_json()
        assert evt["type"] == "input_rejected"
        assert "attachment" in evt["data"]["error"].lower()

        # A normal message still works afterwards (the socket wasn't torn down).
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_done" in _drain(ws)


def test_ws_rejects_malformed_payloads_without_killing_socket(tmp_path):
    client = _client(tmp_path, [_text("normal")])
    with client.websocket_connect("/ws/session/malformed") as ws:
        assert ws.receive_json()["type"] == "ready"

        invalid = [
            [],
            {"type": "user_message", "text": ["not", "text"]},
            {"type": "user_message", "text": "x", "attachments": {}},
            {
                "type": "user_message",
                "text": "x",
                "attachments": [{"kind": "image", "data_url": "https://example.com/x"}],
            },
            {"type": "set_model", "model": {"unexpected": True}},
            {"type": "unknown"},
        ]
        for payload in invalid:
            ws.send_json(payload)
            evt = ws.receive_json()
            assert evt["type"] == "input_rejected"

        ws.send_json({"type": "user_message", "text": "still works"})
        assert "turn_done" in _drain(ws)


def test_ws_allows_only_one_inflight_turn_per_session(tmp_path):
    import threading
    import time

    class SlowProvider(ProviderClient):
        def __init__(self):
            self._lock = threading.Lock()
            self.active = 0
            self.max_active = 0

        def complete(self, *, model, messages, tools=None, **settings):
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(0.08)
                return _text("done")
            finally:
                with self._lock:
                    self.active -= 1

        def capabilities(self, model):
            return ModelCapabilities()

    provider = SlowProvider()
    manager = SessionManager(workspace=tmp_path, provider=provider)
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/serialized") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "first"})
        ws.send_json({"type": "user_message", "text": "second"})

        types = []
        while "turn_done" not in types:
            types.append(ws.receive_json()["type"])

    assert "input_rejected" in types
    assert provider.max_active == 1
    engine = manager._engines["serialized"]
    user_messages = [m for m in engine.messages if m.get("role") == "user"]
    assert [m["content"] for m in user_messages] == ["first"]


def test_ws_rate_limits_inbound_frames(tmp_path):
    from starlette.websockets import WebSocketDisconnect

    from coworker.server import app as app_mod

    client = _client(tmp_path, [])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session/rate") as ws:
            assert ws.receive_json()["type"] == "ready"
            for _ in range(app_mod._WS_RATE_LIMIT_COUNT):
                ws.send_json({"type": "unknown"})
                assert ws.receive_json()["type"] == "input_rejected"
            ws.send_json({"type": "unknown"})
            assert ws.receive_json()["type"] == "input_rejected"
            ws.receive_json()


def test_server_sets_explicit_websocket_frame_limit(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from coworker.server import run as server_run

    seen = {}
    fake_app = object()

    monkeypatch.setattr(server_run, "_ensure_ca_bundle", lambda: None)
    monkeypatch.setattr(server_run, "_exit_when_orphaned", lambda: None)
    monkeypatch.setattr(server_run, "build_app", lambda *args: fake_app)
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda app, **kwargs: seen.update(app=app, **kwargs)),
    )

    server_run.main(["--cwd", str(tmp_path), "--port", "8766"])

    assert seen["app"] is fake_app
    assert seen["ws_max_size"] == server_run._WS_MAX_FRAME_BYTES


def test_standalone_server_token_file_is_user_only(tmp_path, monkeypatch):
    import os

    from coworker.server import run as server_run

    monkeypatch.delenv("COWORKER_API_TOKEN", raising=False)
    path = server_run._ensure_api_token(9876)
    try:
        assert path == tmp_path / "coworker-state" / "sidecar-9876.token"
        assert path.read_text().strip() == os.environ["COWORKER_API_TOKEN"]
        assert len(path.read_text().strip()) == 64
        assert (path.stat().st_mode & 0o777) == 0o600
    finally:
        path.unlink(missing_ok=True)
        os.environ.pop("COWORKER_API_TOKEN", None)


def test_ws_error_persists_notice_and_retry_reruns(tmp_path):
    class FlakyProvider(ProviderClient):
        def __init__(self):
            self.calls = 0

        def complete(self, *, model, messages, tools=None, **settings):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("outage")
            return _text("recovered")

        def capabilities(self, model):
            return ModelCapabilities()

    manager = SessionManager(workspace=tmp_path, provider=FlakyProvider())
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/flaky") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "error" in _drain(ws)
        # The error survives as a persisted notice (reload shows what happened)…
        messages = client.get("/v1/sessions/flaky/messages").json()["messages"]
        assert messages[-1]["role"] == "notice" and messages[-1]["kind"] == "error"
        # …and retry re-runs the turn without a new user message.
        ws.send_json({"type": "retry"})
        types = _drain(ws)
        assert "turn_start" in types and "assistant_message" in types
    messages = client.get("/v1/sessions/flaky/messages").json()["messages"]
    assert messages[-1]["role"] == "assistant" and messages[-1]["content"] == "recovered"
    assert sum(1 for m in messages if m["role"] == "user") == 1


# -- origin gate (local-API hardening): a browser page on a foreign origin must not be able to
# read the API cross-origin or open the driving WebSocket. -------------------------------------


def test_cors_rejects_foreign_origin(tmp_path):
    client = _client(tmp_path, [])
    # A random website's origin gets no ACAO header, so the browser blocks the read.
    resp = client.get("/v1/sessions", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}
    # The desktop webview's own origin is allowed.
    ok = client.get("/v1/sessions", headers={"Origin": "tauri://localhost"})
    assert ok.headers.get("access-control-allow-origin") == "tauri://localhost"
    # Localhost dev/browser build is allowed too.
    dev = client.get("/v1/sessions", headers={"Origin": "http://localhost:1420"})
    assert dev.headers.get("access-control-allow-origin") == "http://localhost:1420"


def test_ws_rejects_foreign_origin(tmp_path):
    from starlette.websockets import WebSocketDisconnect as WSD

    client = _client(tmp_path, [_text("hi")])
    with pytest.raises(WSD) as e:
        with client.websocket_connect(
            "/ws/session/x", headers={"Origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()
    assert e.value.code == 1008


def test_ws_allows_webview_origin(tmp_path):
    client = _client(tmp_path, [_text("hi")])
    with client.websocket_connect(
        "/ws/session/x", headers={"Origin": "http://tauri.localhost"}
    ) as ws:
        assert ws.receive_json()["type"] == "ready"


def test_sidecar_token_gates_rest_and_websockets(tmp_path, monkeypatch):
    from starlette.websockets import WebSocketDisconnect as WSD

    from coworker.mcp.config import global_mcp_path

    monkeypatch.setenv("COWORKER_API_TOKEN", "a" * 64)
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))

    assert client.get("/v1/health").json() == {"status": "ok"}
    assert client.get("/v1/sessions").status_code == 401
    assert client.get("/v1/sessions", headers={"X-OpenWorker-Token": "wrong"}).status_code == 401

    headers = {"X-OpenWorker-Token": "a" * 64}
    assert client.get("/v1/health", headers=headers).json()["default_workspace"] == str(
        tmp_path.resolve()
    )
    assert client.get("/v1/sessions", headers=headers).status_code == 200

    rejected = client.post(
        "/v1/mcp",
        json={"name": "evil", "config": {"command": "sh", "args": ["-c", "id"]}},
    )
    assert rejected.status_code == 401
    assert not global_mcp_path().exists()

    with pytest.raises(WSD) as denied:
        with client.websocket_connect("/ws/session/tokenless") as ws:
            ws.receive_json()
    assert denied.value.code == 1008

    with client.websocket_connect(
        "/ws/session/authed", subprotocols=["werubworker", "a" * 64]
    ) as ws:
        assert ws.accepted_subprotocol == "werubworker"
        assert ws.receive_json()["type"] == "ready"

    with client.websocket_connect("/ws/events", subprotocols=["werubworker", "a" * 64]) as ws:
        assert ws.accepted_subprotocol == "werubworker"

    # Redirect callbacks remain tokenless, then enforce their own signed state.
    assert client.get("/auth/callback", params={"code": "x", "state": "bad"}).status_code == 400
    assert client.get("/mcp/oauth/callback").status_code == 400
    assert client.post("/oauth/callback", data={"app_state": "bad"}).status_code == 400


def test_ws_approval_round_trip(tmp_path):
    client = _client(
        tmp_path,
        [
            _tool("write_file", {"path": "made.py", "content": "print(1)\n"}),
            _text("wrote it"),
        ],
    )
    with client.websocket_connect("/ws/session/s2") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "create made.py"})
        types = _drain(ws, on_permission="once")
        assert "permission_required" in types
        assert "tool_finished" in types
    assert (tmp_path / "made.py").read_text() == "print(1)\n"


def test_ws_session_persisted_while_parked_on_approval(tmp_path):
    """A crash mid-turn must not eat the conversation: by the time the engine parks on an
    approval, the session (user message + assistant tool call) is already on disk."""
    manager = SessionManager(
        workspace=tmp_path,
        provider=ScriptedProvider(
            [_tool("write_file", {"path": "x.py", "content": "1\n"}), _text("done")]
        ),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/persist1") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "make x.py"})
        while ws.receive_json()["type"] != "permission_required":
            pass
        # Parked on the approval — nothing approved, turn far from done. Already saved?
        rec = manager.session_store.load("persist1")
        assert rec is not None
        roles = [m.get("role") for m in rec.messages]
        assert "user" in roles  # turn_start checkpoint
        assert "assistant" in roles  # iteration progress checkpoint
        ws.send_json({"type": "approval", "decision": "deny"})
        while ws.receive_json()["type"] != "turn_done":
            pass


def test_ws_browser_tool_audit_round_trip(tmp_path):
    client = _client(tmp_path, [_tool("browser_close", {}), _text("closed")])
    with client.websocket_connect("/ws/session/browser-audit?agent=cowork") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "close browser"})
        types = _drain(ws, on_permission="once")
        assert "permission_required" in types
        assert "tool_finished" in types

    rows = client.get(
        "/v1/audit", params={"session_id": "browser-audit", "connector": "browser"}
    ).json()["events"]
    assert any(r["tool"] == "browser_close" and r["stage"] == "approval_resolved" for r in rows)
    assert any(r["tool"] == "browser_close" and r["stage"] == "finished" for r in rows)


def test_open_and_recent_workspaces(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    client = _client(tmp_path, [])
    opened = client.post("/v1/workspaces/open", json={"path": str(proj)}).json()
    assert opened["ok"] is True
    recents = client.get("/v1/workspaces/recent").json()["workspaces"]
    assert any(w["path"] == str(proj.resolve()) for w in recents)


def test_workspace_command_trust_controls_live_engine(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "trusted-project"
    (proj / ".coworker").mkdir(parents=True)
    (proj / ".coworker" / "config.toml").write_text(
        'allowed_commands = ["pytest"]\nauto_allow = ["write_file"]\n'
    )
    manager = SessionManager(
        workspace=None, data_dir=tmp_path / "data", provider=ScriptedProvider([])
    )
    client = TestClient(create_app(manager))

    with client.websocket_connect(f"/ws/session/trust?workspace={quote(str(proj))}") as ws:
        ready = ws.receive_json()
        policy = ready["data"]["command_trust"]
        assert policy["required"] is True
        assert policy["requested_commands"] == ["pytest"]

        engine = manager._engines["trust"]
        before = engine.permissions.evaluate("run_shell", {"command": "pytest -q"}, None)
        assert not before.allowed and before.needs_user
        # Workspace auto_allow remains ignored even after command trust.
        assert "write_file" not in engine.permissions.auto_allow_tools

        trusted = client.post(
            "/v1/workspaces/trust",
            json={"path": str(proj), "trusted": True},
        ).json()
        assert trusted["ok"] and trusted["trusted"]
        assert engine.permissions.evaluate("run_shell", {"command": "pytest -q"}, None).allowed

        listed = client.get("/v1/workspaces/trusted").json()["workspaces"]
        assert [item["workspace"] for item in listed] == [str(proj.resolve())]

        revoked = client.post(
            "/v1/workspaces/trust",
            json={"path": str(proj), "trusted": False},
        ).json()
        assert revoked["ok"] and not revoked["trusted"]
        after = engine.permissions.evaluate("run_shell", {"command": "pytest -q"}, None)
        assert not after.allowed and after.needs_user

    manager.workspace_trust.set_trusted(proj, True)
    proj.rename(tmp_path / "moved-project")
    assert client.post(
        "/v1/workspaces/trust",
        json={"path": str(proj), "trusted": False},
    ).json()["ok"]
    assert manager.trusted_workspaces() == []


def test_recent_workspaces_exclude_scratch_dirs(tmp_path):
    # Scratch dirs get touched like any workspace, but must never show up as
    # "recent projects" in the folder gate (owner call, 2026-07-03).
    from coworker.server.manager import SessionManager

    proj = tmp_path / "real-project"
    proj.mkdir()
    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")
    scratch = mgr._provision_scratch("sess-1")
    mgr.session_store.touch_workspace(str(proj.resolve()))
    mgr.session_store.touch_workspace(scratch)
    paths = [w["path"] for w in mgr.recent_workspaces()]
    assert str(proj.resolve()) in paths
    assert scratch not in paths


def test_delete_session_removes_its_scratch_dir_only(tmp_path):
    # Deleting a session also deletes its per-conversation scratch dir (owner call,
    # 2026-07-03) — but NEVER a real project folder the user picked.
    from pathlib import Path

    from coworker.server.manager import SessionManager
    from coworker.sessions import SessionRecord

    mgr = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    mgr._prefs["scratch_base"] = str(tmp_path / "scratch")

    scratch = Path(mgr._provision_scratch("sess-scratch"))
    mgr.session_store.save(
        SessionRecord(
            session_id="sess-scratch",
            workspace=str(scratch),
            model="m",
            mode="interactive",
        )
    )
    assert mgr.delete_session("sess-scratch")["ok"]
    assert not scratch.exists()

    proj = tmp_path / "real-project"
    proj.mkdir()
    mgr.session_store.save(
        SessionRecord(session_id="sess-proj", workspace=str(proj), model="m", mode="interactive")
    )
    assert mgr.delete_session("sess-proj")["ok"]
    assert proj.is_dir()  # user folders are sacred


def test_open_invalid_workspace(tmp_path):
    client = _client(tmp_path, [])
    bad = client.post("/v1/workspaces/open", json={"path": str(tmp_path / "nope")}).json()
    assert bad["ok"] is False


def test_open_workspace_create(tmp_path):
    client = _client(tmp_path, [])
    fresh = tmp_path / "fresh-project"
    assert not fresh.exists()
    res = client.post("/v1/workspaces/open", json={"path": str(fresh), "create": True}).json()
    assert res["ok"] is True
    assert fresh.is_dir()


def test_ws_requires_workspace_when_no_default(tmp_path):
    # Manager with no default workspace: a session with no folder is rejected.
    manager = SessionManager(workspace=None, data_dir=tmp_path, provider=ScriptedProvider([]))
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/nofolder") as ws:
        first = ws.receive_json()
        assert first["type"] == "error"
        assert "workspace" in first["data"]["error"]


def test_ws_with_workspace_query(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider([_text("hi from proj")]),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect(f"/ws/session/s?workspace={quote(str(proj))}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["data"]["workspace"] == str(proj.resolve())
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_end" in _drain(ws)


def test_ws_chat_agent_needs_no_workspace(tmp_path):
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider([_text("hi from chat")]),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/chat1?agent=chat") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert ready["data"]["agent"] == "chat"
        assert ready["data"]["workspace"] is None
        ws.send_json({"type": "user_message", "text": "hello"})
        assert "turn_end" in _drain(ws)


def test_ws_set_mode_auto_skips_approval(tmp_path):
    from urllib.parse import quote

    proj = tmp_path / "proj"
    proj.mkdir()
    manager = SessionManager(
        workspace=None,
        data_dir=tmp_path,
        provider=ScriptedProvider(
            [_tool("write_file", {"path": "a.py", "content": "x"}), _text("done")]
        ),
    )
    client = TestClient(create_app(manager))
    with client.websocket_connect(f"/ws/session/sm?workspace={quote(str(proj))}") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "set_mode", "mode": "auto"})
        ws.send_json({"type": "user_message", "text": "write a.py"})
        types = _drain(ws)  # no approval handler — would hang if it asked
        assert "permission_required" not in types
    assert (proj / "a.py").read_text() == "x"


def test_ws_session_resume_via_store(tmp_path):
    # First connection runs a turn and persists the session.
    client = _client(tmp_path, [_text("first answer")])
    with client.websocket_connect("/ws/session/keep") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_message", "text": "remember this"})
        _drain(ws)
    # The session is now listed via REST.
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert any(s["session_id"] == "keep" and s["messages"] > 0 for s in sessions)


def test_ws_first_message_binds_then_midsession_switch_persists_notice(tmp_path):
    """The FIRST user_message's model binds the session silently (race-proof across
    reconnects — found 2026-07-04). Mid-session rebinds are ALLOWED (roadmap item 3,
    2026-07-22, supersedes the 07-04 lock): the switch lands as a persisted model_switch
    notice and a model_changed broadcast, and the next turn runs on the new model."""
    # 4 turns: 3 user turns + the autotitle's fire-and-forget complete() after turn 1.
    client = _client(
        tmp_path, [_text("ok"), _text("Session title"), _text("ok again"), _text("still ok")]
    )
    with client.websocket_connect("/ws/session/model-per-msg") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "hi", "model": "zai:glm-5.2"})
        assert "model_changed" not in _drain(ws)  # first bind is silent
        # message WITHOUT a model keeps the bound one (no silent reset to default)
        ws.send_json({"type": "user_message", "text": "again"})
        _drain(ws)
        ws.send_json({"type": "set_model", "model": "kimi:kimi-k2.6"})
        changed = ws.receive_json()
        assert changed["type"] == "model_changed"
        assert changed["data"]["model"] == "kimi:kimi-k2.6"
        assert "Kimi" in changed["data"]["text"]
        ws.send_json({"type": "user_message", "text": "switched now"})
        _drain(ws)
    mgr = client.app.state.manager
    engine = mgr._engines["model-per-msg"]
    assert engine.model == "kimi:kimi-k2.6"
    # The marker is persisted between the turns; the provider never sees it.
    messages = client.get("/v1/sessions/model-per-msg/messages").json()["messages"]
    notices = [m for m in messages if m["role"] == "notice"]
    assert [n["kind"] for n in notices] == ["model_switch"]
    assert all(m.get("role") != "notice" for m in engine._outbound_messages())


def test_session_messages_prefers_the_live_engine(tmp_path):
    """Opening a RUNNING session (e.g. a scheduled automation's first turn) must show the live
    conversation: the persisted record may not exist yet mid-turn — reading only the store gave
    a blank transcript on first open (owner report, 2026-07-04)."""
    client = _client(tmp_path, [_text("ok")])
    mgr = client.app.state.manager
    engine = mgr.get_engine("__run__live", agent="chat")
    engine.messages.append({"role": "user", "content": "hi from a running automation"})

    msgs = client.get("/v1/sessions/__run__live/messages").json()["messages"]
    assert any(m.get("content") == "hi from a running automation" for m in msgs)


def test_pick_native_folder_paths(tmp_path, monkeypatch):
    """The sidecar-side folder picker (for browser GUIs): picked path round-trips; cancel and
    missing-picker degrade to ok:False without raising."""
    import subprocess
    from types import SimpleNamespace

    client = _client(tmp_path, [])
    mgr = client.app.state.manager

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="/tmp/picked\n", stderr=""),
    )
    assert client.post("/v1/workspaces/pick").json() == {
        "ok": True,
        "path": "/tmp/picked",
    }

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="User canceled."),
    )
    assert client.post("/v1/workspaces/pick").json()["ok"] is False

    def boom(*a, **k):
        raise OSError("no zenity")

    monkeypatch.setattr(subprocess, "run", boom)
    out = mgr.pick_native_folder()
    assert out["ok"] is False and "picker" in out["error"]


def test_provider_set_and_remove_roundtrip(tmp_path):
    """Settings ▸ Models "Remove key": DELETE /v1/providers/{name} forgets the stored
    profile so the provider reads unconfigured again; unknown names are a clean error.
    """
    client = _client(tmp_path, [])
    assert client.post(
        "/v1/providers", json={"name": "zai", "fields": {"api_key": "zk-test"}}
    ).json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert prov["zai"]["configured"] and prov["zai"]["key_set_at"]

    assert client.delete("/v1/providers/zai").json()["ok"]
    prov = {p["name"]: p for p in client.get("/v1/providers").json()}
    assert not prov["zai"]["configured"]
    assert not prov["zai"]["key_set_at"]

    assert not client.delete("/v1/providers/nope").json()["ok"]


def test_always_allow_grants_survive_restart(tmp_path):
    """ "Always allow" is session-scoped, and the session outlives the process — a restart
    (fresh manager over the same store) must not re-ask for an approved command
    (owner-hit 2026-07-22 on the 0.1.6 walkthrough)."""

    def _shell_turns():
        return ScriptedProvider(
            [
                _tool("run_shell", {"command": "uname -a"}, call_id="c1"),
                _text("done"),
            ]
        )

    def _run_turn(client, expect_prompts):
        with client.websocket_connect("/ws/session/grants1?agent=cowork") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "user_message", "text": "run it"})
            asked = 0
            while True:
                ev = ws.receive_json()
                if ev["type"] == "permission_required":
                    asked += 1
                    ws.send_json({"type": "approval", "decision": "always_command"})
                if ev["type"] == "turn_done":
                    break
            assert asked == expect_prompts

    mgr = SessionManager(workspace=None, provider=_shell_turns())
    _run_turn(TestClient(create_app(mgr)), expect_prompts=1)

    # "Restart": new manager + engine rebuilt from the persisted record.
    mgr2 = SessionManager(workspace=None, provider=_shell_turns())
    _run_turn(TestClient(create_app(mgr2)), expect_prompts=0)


def test_google_one_click_paused_but_manual_alive(tmp_path):
    """CASA verification pending: Gmail/Calendar/Drive expose managed_paused (GUI badges
    "Coming soon"), the managed-connect route refuses, and the manual fields stay."""
    client = _client(tmp_path, [])
    connectors = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    for name in ("gmail", "google_calendar", "google_drive"):
        c = connectors[name]
        assert c["managed"] is True and c["managed_paused"] is True
        assert c["fields"], f"{name} lost its manual fields"
    assert connectors["slack"]["managed_paused"] is False  # only Google is paused

    refused = client.post("/v1/connectors/gmail/connect-managed", json={}).json()
    assert refused["ok"] is False and (
        "coming soon" in refused.get("error", "")
        or "Cloud not configured" in refused.get("error", "")
    )


def test_set_provider_persists_extra_fields(tmp_path):
    """Non-secret descriptor extras (ollama's endpoint) round-trip: saved into the
    profile, echoed by get_providers for form prefill, cleared by an empty save."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    assert manager.set_provider("ollama", {"base_url": "http://127.0.0.1:9999"})["ok"]
    providers = {p["name"]: p for p in manager.get_providers()}
    assert providers["ollama"]["values"]["base_url"] == "http://127.0.0.1:9999"

    manager.set_provider("ollama", {"base_url": ""})
    providers = {p["name"]: p for p in manager.get_providers()}
    assert "base_url" not in providers["ollama"]["values"]
