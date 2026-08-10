"""Server REST API tests — split from test_server.py for maintainability."""

from __future__ import annotations

from fastapi.testclient import TestClient

from coworker.server import SessionManager, create_app
from coworker.sessions import SessionRecord
from conftest import ScriptedProvider, _client, _text, _tool

# -- REST -----------------------------------------------------------------------


def test_chat_completions_openai_shape(tmp_path):
    client = _client(tmp_path, [_text("hello world")])
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5.5", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "hello world"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_agents_and_memory_rest(tmp_path):
    client = _client(tmp_path, [])
    agents = client.get("/v1/agents").json()["agents"]
    # The picker lists enabled+surfaced personas — a fresh install is cowork-only
    # (non-default personas ship disabled, opt-in from Settings ▸ Personas).
    names = [a["name"] for a in agents]
    assert names == ["cowork"]
    assert "skills" in client.get("/v1/skills").json()  # catalog (may be empty)

    added = client.post("/v1/memory", json={"content": "prefer pathlib"}).json()
    assert added["content"] == "prefer pathlib"
    assert any(m["content"] == "prefer pathlib" for m in client.get("/v1/memory").json()["memory"])


def test_disable_persona_archives_its_sessions(tmp_path):
    """Disable = "put this coworker and its history away": the persona's real sessions are
    archived atomically server-side (so its sidebar section disappears with it), internal
    __run__ threads and other personas are untouched, and re-enable never unarchives."""
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    store = manager.session_store

    def mk(sid, agent):
        store.save(
            SessionRecord(
                session_id=sid,
                workspace=str(tmp_path),
                model="m",
                mode="interactive",
                agent=agent,
            )
        )

    mk("chat-a", "chat")
    mk("chat-b", "chat")
    mk("chat-old", "chat")
    store.set_flags("chat-old", archived=True)  # already archived — must not be re-counted
    mk("cowork-a", "cowork")
    mk("__run__r1", "chat")  # internal automation thread — never touched

    client = TestClient(create_app(manager))
    body = client.post("/v1/personas/chat", json={"enabled": False}).json()
    assert body["ok"] is True
    assert body["archived_sessions"] == 2
    assert store.load("chat-a").archived and store.load("chat-b").archived
    assert store.load("cowork-a").archived is False
    assert store.load("__run__r1").archived is False

    # Re-enable brings the persona back but never rewrites the user's archive state.
    client.post("/v1/personas/chat", json={"enabled": True})
    assert store.load("chat-a").archived

    # The dedicated §5/§8 enable route shares the same semantic.
    mk("chat-c", "chat")
    client.post("/v1/personas/chat/enable", json={"enabled": False})
    assert store.load("chat-c").archived


def test_connector_tool_settings_and_audit_rest(tmp_path):
    client = _client(tmp_path, [])
    connectors = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    assert any(t["name"] == "browser_open_url" for t in connectors["browser"]["tools"])

    res = client.patch(
        "/v1/connectors/browser/tools", json={"enabled": {"browser_open_url": False}}
    ).json()
    assert res["ok"] is True
    connectors = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}
    browser_tools = {t["name"]: t for t in connectors["browser"]["tools"]}
    assert browser_tools["browser_open_url"]["enabled"] is False

    assert client.get("/v1/audit", params={"session_id": "none"}).json()["events"] == []
    assert client.get("/v1/browser/state").json()["status"] in {
        "closed",
        "open",
        "error",
    }


def test_artifacts_list_and_read_previewable_files(tmp_path):
    (tmp_path / "brief.md").write_text("# Brief\n\nHello", encoding="utf-8")
    (tmp_path / "page.html").write_text("<h1>Preview</h1>", encoding="utf-8")
    (tmp_path / ".secret.md").write_text("hidden", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.md").write_text("skip", encoding="utf-8")

    client = _client(tmp_path, [])
    artifacts = client.get("/v1/sessions/unknown/artifacts").json()["artifacts"]
    by_path = {a["path"]: a for a in artifacts}

    assert by_path["brief.md"]["kind"] == "markdown"
    assert by_path["page.html"]["kind"] == "html"
    assert ".secret.md" not in by_path
    assert "node_modules/noise.md" not in by_path

    md = client.get("/v1/sessions/unknown/artifacts/read", params={"path": "brief.md"}).json()
    assert md["ok"] is True
    assert md["kind"] == "markdown"
    assert md["content"].startswith("# Brief")

    html = client.get("/v1/sessions/unknown/artifacts/read", params={"path": "page.html"}).json()
    assert html["ok"] is True
    assert html["kind"] == "html"
    assert "<h1>Preview</h1>" in html["content"]


def test_artifact_read_folder_returns_listing(tmp_path):
    """A linked directory (e.g. a skill package dir) renders as a listing, never a dead
    'not found' (owner report 2026-07-27). Dirs first, then files, sizes on files only."""
    pkg = tmp_path / "directory-statistics"
    pkg.mkdir()
    (pkg / "SKILL.md").write_text("---\nname: x\n---\nbody", encoding="utf-8")
    (pkg / "stats.py").write_text("print(1)", encoding="utf-8")
    (pkg / "examples").mkdir()

    client = _client(tmp_path, [])
    res = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "directory-statistics"}
    ).json()
    assert res["ok"] is True and res["kind"] == "folder"
    names = [e["name"] for e in res["entries"]]
    assert names == ["examples", "SKILL.md", "stats.py"]  # dirs first, then files by name
    assert res["entries"][0]["dir"] is True
    assert res["entries"][2]["size"] > 0

    # A genuinely missing path keeps a friendly, non-jargon error.
    missing = client.get("/v1/sessions/unknown/artifacts/read", params={"path": "nope.md"}).json()
    assert missing["ok"] is False
    assert "moved or deleted" in missing["error"]


def test_artifact_read_rejects_path_escape(tmp_path):
    client = _client(tmp_path, [])
    escaped = client.get(
        "/v1/sessions/unknown/artifacts/read", params={"path": "../outside.md"}
    ).json()
    assert escaped["ok"] is False
    assert "escapes" in escaped["error"]


def test_sessions_hide_scheduled_internal_runs(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    manager.session_store.save(
        SessionRecord(
            session_id="normal",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "normal task"}],
            title="Normal task",
            agent="cowork",
        )
    )
    manager.session_store.save(
        SessionRecord(
            session_id="__run__daily-news-1",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "scheduled run"}],
            title="Daily news briefing",
            agent="cowork",
        )
    )
    manager.session_store.save(
        SessionRecord(
            session_id="__task__daily-news",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "scheduled task"}],
            title="Daily news briefing",
            agent="cowork",
        )
    )
    client = TestClient(create_app(manager))
    session_ids = {s["session_id"] for s in client.get("/v1/sessions").json()["sessions"]}
    assert "normal" in session_ids
    assert "__run__daily-news-1" not in session_ids
    assert "__task__daily-news" not in session_ids


def test_sessions_can_be_renamed_and_deleted(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    manager.session_store.save(
        SessionRecord(
            session_id="rename-me",
            workspace=str(tmp_path),
            model="gpt-5.5",
            mode="interactive",
            messages=[{"role": "user", "content": "original"}],
            title="Original title",
            agent="cowork",
        )
    )
    client = TestClient(create_app(manager))

    renamed = client.patch("/v1/sessions/rename-me", json={"title": "  Better title  "}).json()
    assert renamed["ok"] is True
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert any(s["session_id"] == "rename-me" and s["title"] == "Better title" for s in sessions)

    deleted = client.delete("/v1/sessions/rename-me").json()
    assert deleted["ok"] is True
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert all(s["session_id"] != "rename-me" for s in sessions)
    assert client.get("/v1/sessions/rename-me/messages").json()["messages"] == []


def test_sessions_can_be_pinned_and_archived(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=ScriptedProvider([]))
    for sid in ("older", "newer"):
        manager.session_store.save(
            SessionRecord(
                session_id=sid,
                workspace=str(tmp_path),
                model="gpt-5.5",
                mode="interactive",
                messages=[{"role": "user", "content": sid}],
                agent="cowork",
            )
        )
    client = TestClient(create_app(manager))

    assert client.patch("/v1/sessions/older", json={"pinned": True}).json()["ok"] is True
    sessions = client.get("/v1/sessions").json()["sessions"]
    assert sessions[0]["session_id"] == "older" and sessions[0]["pinned"] is True

    assert client.patch("/v1/sessions/newer", json={"archived": True}).json()["ok"] is True
    by_id = {s["session_id"]: s for s in client.get("/v1/sessions").json()["sessions"]}
    assert by_id["newer"]["archived"] is True

    assert client.patch("/v1/sessions/older", json={"pinned": False}).json()["ok"] is True
    assert client.patch("/v1/sessions/newer", json={"archived": False}).json()["ok"] is True
    by_id = {s["session_id"]: s for s in client.get("/v1/sessions").json()["sessions"]}
    assert by_id["older"]["pinned"] is False and by_id["newer"]["archived"] is False


