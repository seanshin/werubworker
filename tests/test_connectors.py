"""Tests for the messaging connector core (C2 increment 1): targets, the send_message
tool, settings/authorization, and the gateway inbound loop — all offline via FakeAdapter.
"""

from __future__ import annotations

import asyncio

import pytest

from coworker.connectors import (
    ConnectorSettings,
    FakeAdapter,
    Gateway,
    MessageEvent,
    SessionSource,
    format_target,
    is_authorized,
    make_send_message_tool,
    parse_target,
)
from coworker.connectors.base import SendResult
from coworker.secrets import SecretStore


# -- target tokens -------------------------------------------------------------
def test_target_round_trip():
    assert format_target("telegram", "12345") == "telegram:12345"
    assert format_target("slack", "C1", "168.9") == "slack:C1:168.9"
    assert parse_target("telegram:12345") == ("telegram", "12345", None)
    assert parse_target("slack:C1:168.9") == ("slack", "C1", "168.9")


def test_target_invalid():
    for bad in ("", "telegram", "telegram:", ":123"):
        with pytest.raises(ValueError):
            parse_target(bad)


def test_session_source_target_and_label():
    s = SessionSource(platform="telegram", chat_id="42", user_name="Alice", chat_type="dm")
    assert s.target == "telegram:42"
    assert "Alice" in s.label() and "telegram" in s.label()


def test_message_tagged_text_carries_reply_handle():
    s = SessionSource(platform="slack", chat_id="C9", user_name="Bob", chat_type="channel")
    ev = MessageEvent(text="ship it", source=s)
    tag = ev.tagged_text()
    assert "reply→slack:C9" in tag and "ship it" in tag


# -- send_message tool ---------------------------------------------------------
def _fake_senders(record):
    def sender(token, chat_id, text, thread_id=None):
        record.append({"token": token, "chat_id": chat_id, "text": text, "thread_id": thread_id})
        return SendResult(True, message_id="99")

    return {"telegram": sender, "slack": sender}


def test_send_message_success(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"type": "token", "bot_token": "T0K"})
    record = []
    tool = make_send_message_tool(secrets, senders=_fake_senders(record))

    out = tool(target="telegram:12345", text="hello")
    assert out == {"ok": True, "message_id": "99", "target": "telegram:12345"}
    assert record == [{"token": "T0K", "chat_id": "12345", "text": "hello", "thread_id": None}]
    # tool carries gating metadata + an explicit schema
    assert tool.__aisuite_tool_metadata__.requires_approval is True
    assert tool.__coworker_schema__["function"]["name"] == "send_message"


def test_send_message_missing_token(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    tool = make_send_message_tool(secrets, senders=_fake_senders([]))
    assert "error" in tool(target="telegram:1", text="x")


def test_send_message_unknown_platform(tmp_path):
    tool = make_send_message_tool(SecretStore(tmp_path / "secrets.json"), senders=_fake_senders([]))
    assert "unknown platform" in tool(target="discord:1", text="x")["error"]


def test_send_message_bad_target(tmp_path):
    tool = make_send_message_tool(SecretStore(tmp_path / "secrets.json"), senders=_fake_senders([]))
    assert "error" in tool(target="nonsense", text="x")


# -- settings / authorization --------------------------------------------------
def test_is_authorized():
    s = ConnectorSettings(platform="telegram", allowed_users={"u1"})
    assert is_authorized(s, SessionSource("telegram", "c", user_id="u1"))
    assert not is_authorized(s, SessionSource("telegram", "c", user_id="u2"))
    # empty allowlist = nobody
    assert not is_authorized(
        ConnectorSettings("telegram"), SessionSource("telegram", "c", user_id="u1")
    )
    # allow_all opens it
    assert is_authorized(
        ConnectorSettings("telegram", allow_all=True),
        SessionSource("telegram", "c", user_id="x"),
    )


def test_load_settings_from_secretstore(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"type": "token", "bot_token": "T", "allowed_users": ["u1"]})
    settings = __import__("coworker.connectors.config", fromlist=["load_settings"]).load_settings(
        secrets
    )
    assert settings["telegram"].enabled is True
    assert settings["telegram"].allowed_users == {"u1"}
    assert settings["slack"].enabled is False  # no token


def test_load_settings_env_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "a, b ,c")
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("telegram:default", {"bot_token": "T"})
    settings = __import__("coworker.connectors.config", fromlist=["load_settings"]).load_settings(
        secrets
    )
    assert settings["telegram"].allowed_users == {"a", "b", "c"}


# -- gateway inbound loop (FakeAdapter) ----------------------------------------
async def test_gateway_dispatches_authorized():
    received: list[MessageEvent] = []

    async def handler(ev: MessageEvent) -> None:
        received.append(ev)

    settings = {"fake": ConnectorSettings("fake", enabled=True, allowed_users={"u1"})}
    gw = Gateway(settings=settings, handler=handler)
    fake = FakeAdapter()
    gw.register(fake)
    live = await gw.start()
    assert live == ["fake"] and fake.connected

    await fake.inject("hi", user_id="u1")
    assert len(received) == 1 and received[0].text == "hi"

    await fake.inject("nope", user_id="intruder")  # not in allowlist
    assert len(received) == 1  # dropped

    await gw.stop()
    assert not fake.connected


async def test_gateway_deliver_via_adapter():
    gw = Gateway(settings={"fake": ConnectorSettings("fake", enabled=True, allow_all=True)})
    fake = FakeAdapter()
    gw.register(fake)
    result = await gw.deliver("fake:c9", "pong")
    assert result.ok
    assert fake.outbox == [{"chat_id": "c9", "text": "pong", "thread_id": None}]


async def test_gateway_full_echo_loop():
    """Inbound → handler replies via deliver → lands in the adapter outbox."""
    gw = Gateway(settings={"fake": ConnectorSettings("fake", enabled=True, allow_all=True)})
    fake = FakeAdapter()

    async def echo(ev: MessageEvent) -> None:
        await gw.deliver(ev.source.target, f"echo: {ev.text}")

    gw.set_handler(echo)
    gw.register(fake)
    await fake.inject("ping", chat_id="c1", user_id="u1")
    assert fake.outbox == [{"chat_id": "c1", "text": "echo: ping", "thread_id": None}]


# -- engine integration: send_message appears only when a connector is configured ----
class _StubProvider:
    """Minimal ProviderClient stand-in (build_engine never calls it)."""

    def complete(self, **_kw):  # pragma: no cover - never invoked at build time
        from coworker.providers import AssistantTurn

        return AssistantTurn()

    def capabilities(self, _model):  # pragma: no cover
        from coworker.providers.base import ModelCapabilities

        return ModelCapabilities()

    def stream(self, **_kw):  # pragma: no cover
        from coworker.providers.base import StreamChunk

        yield StreamChunk(turn=self.complete())


def test_engine_connector_tools_are_cowork_scoped(tmp_path):
    from coworker.agent import build_engine
    from coworker.agents import chat_agent, code_agent, cowork_agent, myhelper_agent

    secrets = SecretStore(tmp_path / "secrets.json")
    eng = build_engine(agent=chat_agent(), provider=_StubProvider(), secrets=secrets)
    assert "send_message" not in eng.registry.names()  # no connector yet
    assert "browser_read_url" not in eng.registry.names()

    secrets.put("telegram:default", {"bot_token": "T"})
    chat = build_engine(agent=chat_agent(), provider=_StubProvider(), secrets=secrets)
    code = build_engine(
        agent=code_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    cowork = build_engine(
        agent=cowork_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    helper = build_engine(
        agent=myhelper_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )

    assert "send_message" not in chat.registry.names()
    assert "send_message" not in code.registry.names()
    assert "browser_read_url" not in chat.registry.names()
    assert "browser_read_url" not in code.registry.names()

    assert "send_message" in cowork.registry.names()
    assert "browser_read_url" in cowork.registry.names()
    assert "browser_open_url" in cowork.registry.names()
    assert "browser_click" in cowork.registry.names()
    assert "browser_type" in cowork.registry.names()
    assert "github_search" not in cowork.registry.names()
    assert "send_message" in helper.registry.names()
    assert "browser_read_url" not in helper.registry.names()
    assert "browser_open_url" not in helper.registry.names()

    # §36: browser READS (registry kind) are free; interactions still gate.
    assert cowork.registry.get("browser_open_url").metadata.requires_approval is False
    assert cowork.registry.get("browser_snapshot").metadata.requires_approval is False
    assert cowork.registry.get("browser_click").metadata.requires_approval is True
    assert cowork.registry.get("browser_type").metadata.requires_approval is True
    cowork.permissions.allow_tool_for_session("browser_click")
    decision = cowork.permissions.evaluate(
        "browser_click",
        {"target": "button"},
        cowork.registry.get("browser_click").metadata,
    )
    assert decision.needs_user is True

    secrets.put("github:default", {"token": "ghp_test", "enabled": True})
    cowork_with_github = build_engine(
        agent=cowork_agent(),
        workspace=tmp_path,
        provider=_StubProvider(),
        secrets=secrets,
    )
    assert "github_search" in cowork_with_github.registry.names()
    # §36: github_search is a registry READ — free; the write sibling still gates.
    assert cowork_with_github.registry.get("github_search").metadata.requires_approval is False
    assert cowork_with_github.registry.get("github_create_issue").metadata.requires_approval is True


# -- connector setup (descriptors / connect / disconnect / list) ---------------
def test_connector_list_descriptors(tmp_path):
    from coworker.connectors import connector_list

    by_name = {c["name"]: c for c in connector_list(SecretStore(tmp_path / "secrets.json"))}
    assert by_name["telegram"]["two_way"] is True and by_name["telegram"]["connected"] is False
    # channels (chat capability) is narrower than two_way: GitHub is two-way via the
    # relay (inbound mentions) but sessions can't subscribe to "GitHub channels".
    assert by_name["telegram"]["channels"] is True
    assert by_name["slack"]["channels"] is True
    assert by_name["github"]["two_way"] is True and by_name["github"]["channels"] is False
    assert by_name["gmail"]["available"] is True and by_name["gmail"]["connected"] is False
    assert by_name["browser"]["available"] is True and by_name["browser"]["connected"] is True
    assert by_name["github"]["available"] is True and by_name["github"]["connected"] is False
    assert any(
        t["name"] == "browser_open_url" and t["requires_approval"]
        for t in by_name["browser"]["tools"]
    )
    # telegram exposes a bot_token field + setup instructions
    keys = {f["key"] for f in by_name["telegram"]["fields"]}
    assert "bot_token" in keys and by_name["telegram"]["instructions"]


def test_connector_list_pre_connect_copy(tmp_path):
    """Every connectable connector ships Access bullets for the pre-connect
    detail page (UX-DECISIONS §38) — an empty Access section would render as
    'this app tells you nothing about what it can do'."""
    from coworker.connectors import connector_list
    from coworker.connectors.catalog_copy import ACCESS
    from coworker.connectors.descriptors import list_descriptors

    for c in connector_list(SecretStore(tmp_path / "secrets.json")):
        assert isinstance(c["about"], str)
        assert c["access"] and all(isinstance(line, str) and line for line in c["access"]), (
            f"{c['name']} has no access copy"
        )
    # Curated (non-fallback) copy is required for every AVAILABLE connector —
    # the fallback line is only a net for experimental/placeholder entries.
    missing = [
        d.name
        for d in list_descriptors()
        if d.available and not d.experimental and d.name not in ACCESS
    ]
    assert not missing, f"connectors missing curated access copy: {missing}"


def test_connector_list_connected_for_required_profiles(tmp_path):
    from coworker.connectors import (
        connect_connector,
        connector_list,
        update_connector_tools,
    )

    secrets = SecretStore(tmp_path / "secrets.json")
    assert connect_connector(secrets, "github", {"token": "ghp_test"}, validate=False)["ok"] is True
    assert (
        connect_connector(
            secrets,
            "jira",
            {
                "base_url": "https://example.atlassian.net",
                "email": "me@example.com",
                "api_token": "tok",
            },
            validate=False,
        )["ok"]
        is True
    )

    by_name = {c["name"]: c for c in connector_list(secrets)}
    assert by_name["github"]["connected"] is True and by_name["github"]["enabled"] is True
    assert by_name["jira"]["connected"] is True and by_name["jira"]["enabled"] is True

    assert update_connector_tools(secrets, "github", {"github_search": False})["ok"] is True
    by_name = {c["name"]: c for c in connector_list(secrets)}
    gh_tools = {t["name"]: t for t in by_name["github"]["tools"]}
    assert gh_tools["github_search"]["enabled"] is False
    assert gh_tools["github_get_issue"]["enabled"] is True


def test_connect_disconnect_no_validate(tmp_path):
    from coworker.connectors import (
        connect_connector,
        connector_list,
        disconnect_connector,
    )

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(
        secrets,
        "telegram",
        {"bot_token": "T0K", "allowed_users": "u1, u2"},
        validate=False,
    )
    assert res["ok"] is True
    profile = secrets.get("telegram:default")
    assert profile["bot_token"] == "T0K" and profile["allowed_users"] == ["u1", "u2"]
    assert profile["enabled"] is True

    listed = {c["name"]: c for c in connector_list(secrets)}["telegram"]
    assert (
        listed["connected"] is True
        and listed["enabled"] is True
        and listed["allowed_users"] == ["u1", "u2"]
    )

    assert disconnect_connector(secrets, "telegram")["ok"] is True
    assert secrets.get("telegram:default") is None


def test_reconnect_does_not_clobber_secret_or_allowlist(tmp_path):
    # Regression: a re-submit carrying the masked placeholder (or a blank allow-list) must not
    # overwrite a stored real token / wipe the live allow-list.
    from coworker.connectors import connect_connector
    from coworker.connectors.descriptors import get_descriptor

    secrets = SecretStore(tmp_path / "secrets.json")
    placeholder = next(
        f.placeholder for f in get_descriptor("telegram").fields if f.key == "bot_token"
    )
    connect_connector(
        secrets,
        "telegram",
        {"bot_token": "REAL-TOKEN-123", "allowed_users": "u1, u2"},
        validate=False,
    )

    # Re-submit with the field's mask + an empty allow-list → both must be preserved.
    connect_connector(
        secrets,
        "telegram",
        {"bot_token": placeholder, "allowed_users": ""},
        validate=False,
    )
    prof = secrets.get("telegram:default")
    assert prof["bot_token"] == "REAL-TOKEN-123"  # not reset to the placeholder
    assert prof["allowed_users"] == ["u1", "u2"]  # not wiped

    # A genuinely new token still updates.
    connect_connector(secrets, "telegram", {"bot_token": "NEW-TOKEN-999"}, validate=False)
    assert secrets.get("telegram:default")["bot_token"] == "NEW-TOKEN-999"
    assert secrets.get("telegram:default")["allowed_users"] == [
        "u1",
        "u2",
    ]  # still preserved


def test_connect_missing_required_field(tmp_path):
    from coworker.connectors import connect_connector

    secrets = SecretStore(tmp_path / "secrets.json")
    res = connect_connector(
        secrets, "slack", {"bot_token": "xoxb"}, validate=False
    )  # app_token missing
    assert res["ok"] is False and "missing" in res["error"]


def test_manual_slack_reconnect_preserves_approval_owners(tmp_path):
    from coworker.connectors import connect_connector

    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put(
        "slack:default",
        {
            "bot_token": "xoxb-old",
            "app_token": "xapp-old",
            "allowed_users": ["U_OWNER"],
            "approval_owner_ids": ["U_OWNER"],
        },
    )
    result = connect_connector(
        secrets,
        "slack",
        {"bot_token": "xoxb-new", "app_token": "xapp-new"},
        validate=False,
    )
    assert result["ok"] is True
    profile = secrets.get("slack:default")
    assert profile["approval_owner_ids"] == ["U_OWNER"]
    assert profile["allowed_users"] == ["U_OWNER"]


def test_connect_validation_runs(tmp_path):
    from coworker.connectors import connect_connector
    from coworker.connectors.descriptors import ValidationResult, get_descriptor

    secrets = SecretStore(tmp_path / "secrets.json")
    desc = get_descriptor("telegram")
    orig = desc.validate
    desc.validate = lambda creds: ValidationResult(True, identity="@mybot")
    try:
        res = connect_connector(secrets, "telegram", {"bot_token": "T"})  # validate=True
    finally:
        desc.validate = orig
    assert res == {"ok": True, "account": "@mybot"}
    assert secrets.get("telegram:default")["account"] == "@mybot"


def test_connectors_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from coworker.connectors.descriptors import ValidationResult, get_descriptor
    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    desc = get_descriptor("telegram")
    monkeypatch.setattr(desc, "validate", lambda creds: ValidationResult(True, identity="@testbot"))

    client = TestClient(create_app(SessionManager(data_dir=tmp_path / "data")))

    listed = client.get("/v1/connectors").json()["connectors"]
    assert any(c["name"] == "telegram" for c in listed)

    r = client.post(
        "/v1/connectors/telegram/connect",
        json={"fields": {"bot_token": "T0K", "allowed_users": "u1"}},
    )
    assert r.json() == {"ok": True, "account": "@testbot"}

    tg = {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}["telegram"]
    assert tg["connected"] is True and tg["account"] == "@testbot"
    # secrets never leak over REST
    assert "T0K" not in client.get("/v1/connectors").text

    assert client.post("/v1/connectors/telegram/disconnect").json()["ok"] is True
    assert {c["name"]: c for c in client.get("/v1/connectors").json()["connectors"]}["telegram"][
        "connected"
    ] is False


# -- inbound: event mappers ----------------------------------------------------
def test_telegram_message_mapper():
    from types import SimpleNamespace

    from coworker.connectors import telegram_message_to_event

    msg = SimpleNamespace(
        text="hello",
        message_id=7,
        chat=SimpleNamespace(id=12345, type="private"),
        from_user=SimpleNamespace(id=99, full_name="Alice"),
        message_thread_id=None,
    )
    ev = telegram_message_to_event(msg)
    assert ev.text == "hello" and ev.source.target == "telegram:12345"
    assert ev.source.user_id == "99" and ev.source.chat_type == "dm"
    # non-text (e.g. a sticker) maps to None
    assert (
        telegram_message_to_event(
            SimpleNamespace(text=None, chat=SimpleNamespace(id=1, type="private"))
        )
        is None
    )


def test_slack_event_mapper_and_loop_guard():
    from coworker.connectors import slack_event_to_event

    ev = slack_event_to_event(
        {
            "text": "ship it",
            "channel": "C9",
            "user": "U1",
            "channel_type": "channel",
            "ts": "1.2",
        },
        "BOT",
    )
    assert (
        ev.text == "ship it" and ev.source.target == "slack:C9" and ev.source.chat_type == "channel"
    )
    # bot echo / edits / empty → dropped (reply-loop guard)
    assert slack_event_to_event({"text": "x", "user": "BOT"}, "BOT") is None
    assert slack_event_to_event({"text": "x", "bot_id": "B1"}, None) is None
    assert slack_event_to_event({"subtype": "message_changed", "text": "x"}, None) is None


def test_make_adapter():
    from coworker.connectors import SlackAdapter, TelegramAdapter, make_adapter

    assert isinstance(make_adapter("telegram", {"bot_token": "T"}), TelegramAdapter)
    assert isinstance(make_adapter("slack", {"bot_token": "x", "app_token": "y"}), SlackAdapter)
    assert make_adapter("slack", {"bot_token": "x"}) is None  # app_token missing
    assert make_adapter("telegram", {}) is None


async def test_slack_resolves_and_caches_display_name():
    from coworker.connectors import SlackAdapter

    calls: list[str] = []

    class _Client:
        async def users_info(self, user):
            calls.append(user)
            return {"user": {"name": "ann", "profile": {"display_name": "Ann"}}}

    class _App:
        client = _Client()

    a = SlackAdapter("b", "x")
    a._app = _App()
    assert await a._display_name("U1") == "Ann"
    assert await a._display_name("U1") == "Ann"  # served from cache
    assert calls == ["U1"]  # only one API round-trip

    class _BadClient:
        async def users_info(self, user):
            raise RuntimeError("nope")

    a._app.client = _BadClient()
    assert await a._display_name("U2") is None  # failure → None (caller falls back to the id)
    assert await a._display_name("") is None  # no id → no call


async def test_slack_resolve_channel_name():
    from coworker.connectors import SlackAdapter

    calls: list[str] = []

    class _Client:
        async def conversations_info(self, channel):
            calls.append(channel)
            return {"channel": {"id": channel, "name": "ocw-test"}}

    class _App:
        client = _Client()

    a = SlackAdapter("b", "x")
    a._app = _App()
    assert await a._channel_name("C1") == "ocw-test"
    assert await a._channel_name("C1") == "ocw-test"  # served from cache
    assert calls == ["C1"]  # only one API round-trip
    # public §2.1 wrapper delegates to the cached resolver (no extra call)
    assert await a.resolve_channel_name("C1") == "ocw-test"
    assert calls == ["C1"]

    class _BadClient:
        async def conversations_info(self, channel):
            raise RuntimeError("nope")

    a._app.client = _BadClient()
    assert await a._channel_name("C2") is None  # failure → None (caller falls back to the id)
    assert await a._channel_name("") is None  # no id → no call


# -- chat-ID auto-capture + connector allow-list -------------------------------
async def test_gateway_records_recent_senders():
    gw = Gateway(settings={"fake": ConnectorSettings("fake", enabled=True, allowed_users={"u1"})})
    fake = FakeAdapter()
    gw.register(fake)
    await fake.inject("hi", user_id="u2", user_name="Bob")  # unauthorized → dropped but captured
    await fake.inject("yo", user_id="u1", user_name="Al")  # authorized
    recent = gw.recent_senders()
    assert [r["user_id"] for r in recent] == ["u1", "u2"]  # most-recent first
    assert recent[1]["user_name"] == "Bob"
    # same sender again de-dupes and moves to front
    await fake.inject("again", user_id="u2")
    assert [r["user_id"] for r in gw.recent_senders("fake")] == ["u2", "u1"]


def test_manager_allow_disallow(tmp_path, monkeypatch):
    from coworker.connectors import connect_connector
    from coworker.server.manager import SessionManager

    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    m = SessionManager(data_dir=tmp_path / "data")
    connect_connector(m.secrets, "telegram", {"bot_token": "T"}, validate=False)

    assert m.allow_user("telegram", "12345")["allowed_users"] == ["12345"]
    assert m.secrets.get("telegram:default")["allowed_users"] == ["12345"]
    assert m.disallow_user("telegram", "12345")["allowed_users"] == []
    assert m.allow_user("slack", "x")["ok"] is False  # slack not connected
