"""FastAPI app — OpenAI-compatible endpoint + WS session API + REST.

The control plane every surface (GUI/IDE/messaging) rides on. The WS carries the engine
event stream and the approval channel; `/v1/chat/completions` is the OpenAI-compatible
proxy so any OpenAI-format client can use the runtime as a backend.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import re
import secrets
import uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Origins allowed to talk to the local sidecar. It binds to 127.0.0.1, but a page in the
# user's own browser can still reach loopback — so without an origin gate, any website they
# visit could read `GET /v1/sessions` (CORS was `*`) and drive a session over the WS (which
# CORS never covers) into shell/file tools. We pin to the desktop webview's own origins
# (`tauri://localhost`, Windows' `http(s)://tauri.localhost`) and localhost dev/browser
# builds. Requests with NO Origin header (curl, native clients, tests, server-to-server) are
# allowed — the gate targets browsers, which always attach an unforgeable Origin.
_ALLOWED_ORIGIN_RE = re.compile(
    r"^(tauri://localhost"
    r"|https?://localhost(:\d+)?"
    r"|https?://127\.0\.0\.1(:\d+)?"
    r"|https?://tauri\.localhost)$"
)


def _origin_allowed(origin: str | None) -> bool:
    """True if a browser Origin may use the API. Missing Origin (non-browser) passes."""
    return origin is None or bool(_ALLOWED_ORIGIN_RE.match(origin))


# Caps on inbound WebSocket traffic. The loopback socket is unauthenticated (any local
# process can reach it), so bound frames, messages, and per-connection request rate before
# building model content or starting a turn.
_WS_MAX_FRAME_BYTES = 16 * 1024 * 1024
_WS_RATE_LIMIT_COUNT = 30
_WS_RATE_LIMIT_WINDOW_SECONDS = 10.0
_MAX_MESSAGE_TEXT_CHARS = 200_000
_MAX_ATTACHMENTS_BYTES = 15_000_000  # leaves JSON overhead below the 16 MiB frame cap


def _json_value_size(value: Any) -> int:
    """Conservative UTF-8 size of parsed JSON without allocating another giant string."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, dict):
        return sum(_json_value_size(k) + _json_value_size(v) for k, v in value.items())
    if isinstance(value, list):
        return sum(_json_value_size(v) for v in value)
    return 8  # numbers, booleans, null, separators


# Brand colors for the connector badge riding the ✓ (UX-DECISIONS §30). The GUI owns the
# real logos; this page must render offline with zero assets, so a colored initial stands in.
_BRAND_COLORS = {
    "slack": "#4A154B",
    "github": "#24292f",
    "hubspot": "#ff7a59",
    "gmail": "#ea4335",
    "google_calendar": "#4285f4",
}


def _browser_page(
    title: str, detail: str, *, ok: bool = True, error: str = "", connector: str = ""
) -> str:
    """The page shown in the user's browser at the end of a loopback flow (sign-in or
    connector callback) — one branded card (UX-DECISIONS §30): OCW mark, ok/fail icon
    (the connector's initial rides the ✓), the friendly detail, and the raw error
    preserved on failures (it's the debugging breadcrumb). Inline CSS, light/dark via
    prefers-color-scheme, no external assets — it must render offline."""
    import html as _html

    badge = ""
    if ok and connector:
        color = _BRAND_COLORS.get(connector, "#3670b2")
        initial = _html.escape((connector[:1] or "?").upper())
        badge = f'<span class="mini" style="background:{color}">{initial}</span>'
    icon = f'<div class="ico ok">✓{badge}</div>' if ok else '<div class="ico bad">✕</div>'
    err = f'<div class="err">{_html.escape(error)}</div>' if error else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_html.escape(title)} — WeruBWorker</title><style>"
        ":root{--paper:#f6f5f2;--panel:#fff;--line:#e4e2dc;--ink:#2c2c2a;--muted:#6f6e68;"
        "--faint:#a3a19a;--accent:#3670b2;--ok:#2e7d4f;--ok-soft:#e3f2e9;--bad:#b3423a;"
        "--bad-soft:#f8e7e5}"
        "@media(prefers-color-scheme:dark){:root{--paper:#191918;--panel:#232322;"
        "--line:#373633;--ink:#e8e6e1;--muted:#9d9b94;--faint:#6b6a64;--accent:#6ba3dd;"
        "--ok:#5cb884;--ok-soft:#20362a;--bad:#d97b74;--bad-soft:#3a2422}}"
        "body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;"
        "justify-content:center;gap:18px;background:var(--paper);color:var(--ink);"
        'font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:24px}'
        ".card{background:var(--panel);border:1px solid var(--line);border-radius:16px;"
        "padding:34px 32px 28px;max-width:320px;width:100%;text-align:center;"
        "box-shadow:0 10px 30px rgba(0,0,0,.06);box-sizing:border-box}"
        ".mark{display:flex;align-items:center;justify-content:center;gap:7px;margin-bottom:22px;"
        "font-size:13px;font-weight:650}"
        ".mark i{width:20px;height:20px;border-radius:6px;background:var(--accent);"
        "display:inline-block;position:relative}"
        ".mark i::after{content:'';position:absolute;inset:5px;border-radius:2px;"
        "background:conic-gradient(from 0deg,#fff 0 25%,transparent 0 50%,#fff 0 75%,transparent 0)}"
        ".ico{width:52px;height:52px;border-radius:50%;margin:0 auto 14px;display:flex;"
        "align-items:center;justify-content:center;font-size:24px;position:relative}"
        ".ico.ok{background:var(--ok-soft);color:var(--ok)}"
        ".ico.bad{background:var(--bad-soft);color:var(--bad)}"
        ".mini{position:absolute;right:-3px;bottom:-3px;width:22px;height:22px;border-radius:7px;"
        "display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;"
        "font-weight:700;border:2px solid var(--panel)}"
        "h1{font-size:17px;font-weight:650;margin:0 0 6px;letter-spacing:-.01em}"
        "p{font-size:12.5px;color:var(--muted);margin:0}"
        ".err{font-size:11.5px;color:var(--bad);background:var(--bad-soft);border-radius:8px;"
        "padding:7px 10px;margin-top:12px;text-align:left;word-break:break-word}"
        ".foot{font-size:10.5px;color:var(--faint)}"
        "</style></head><body>"
        '<div class="card"><div class="mark"><i></i>WeruBWorker</div>'
        f"{icon}<h1>{_html.escape(title)}</h1><p>{_html.escape(detail)}</p>{err}</div>"
        '<div class="foot">Served locally by WeruBWorker on your Mac</div>'
        "</body></html>"
    )


def _connector_title(name: str) -> str:
    """Display name for the loopback page — 'Slack connected', never 'slack connected'."""
    from ..connectors.descriptors import get_descriptor

    d = get_descriptor(name)
    return d.title if d else (name[:1].upper() + name[1:])


_CONNECT_FAILED_DETAIL = (
    "Something went wrong finishing this connection. Close this tab and try again from WeruBWorker."
)

from ..attachments import (
    MAX_ATTACHMENTS as _MAX_ATTACHMENTS,
)
from ..attachments import (
    MAX_IMAGE_CHARS,
    MAX_PDF_CHARS,
    MAX_TEXT_CHARS,
    build_user_content,
)
from ..engine import ApprovalOutcome
from ..inbox import VIS_INBOX, VIS_INLINE, args_preview
from ..permissions import Mode
from ..providers import AssistantTurn
from .manager import SessionManager


def create_app(manager: SessionManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            live = await manager.start_gateway()  # start messaging listeners (if configured)
            if live:
                print(f"[coworker] messaging gateway live: {', '.join(live)}")
        except Exception:  # never let a bad connector stop the server
            import traceback

            traceback.print_exc()

        # Background task: auto-lock vault after 30 min idle (SEC-12)
        async def _vault_idle_checker() -> None:
            while True:
                await asyncio.sleep(60)  # check every minute
                try:
                    manager.vault.check_idle()
                except Exception:
                    pass

        vault_task = asyncio.create_task(_vault_idle_checker())
        yield
        vault_task.cancel()
        await manager.aclose()  # stop gateway + close MCP connections on shutdown

    app = FastAPI(title="coworker", version="0.0.0", lifespan=lifespan)
    api_token = os.environ.get("COWORKER_API_TOKEN", "")
    tokenless_paths = {
        "/v1/health",
        "/auth/callback",
        "/mcp/oauth/callback",
        "/oauth/callback",
        "/v1/auth/status",
        "/v1/auth/setup",
        "/v1/auth/login",
        "/v1/auth/logout",
        "/v1/auth/change-password",
    }

    def _request_authenticated(request: Request) -> bool:
        provided = request.headers.get("x-werubworker-token", "") or request.headers.get(
            "x-openworker-token", ""
        )
        return bool(api_token and provided and secrets.compare_digest(provided, api_token))

    def _websocket_authenticated(ws: WebSocket) -> bool:
        if not api_token:
            return True
        protocols = {
            part.strip()
            for part in ws.headers.get("sec-websocket-protocol", "").split(",")
            if part.strip()
        }
        return any(secrets.compare_digest(part, api_token) for part in protocols)

    @app.middleware("http")
    async def require_sidecar_token(request: Request, call_next):
        # Preflights carry the requested header name, not its value. CORS checks the
        # Origin; the actual state-changing request still must authenticate.
        if (
            not api_token
            or request.method == "OPTIONS"
            or request.url.path in tokenless_paths
            or _request_authenticated(request)
        ):
            return await call_next(request)
        return JSONResponse(
            {"error": "missing or invalid OpenWorker sidecar token"},
            status_code=401,
        )

    app.add_middleware(
        CORSMiddleware,
        # Pinned to the desktop webview + localhost (see _ALLOWED_ORIGIN_RE): stops a random
        # website the user visits from reading local API responses cross-origin.
        allow_origin_regex=_ALLOWED_ORIGIN_RE.pattern,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Auth middleware — runs AFTER the sidecar token check (which is registered first and
    # therefore wraps this one in FastAPI's middleware stack). Auth endpoints themselves are
    # in tokenless_paths so they pass through both layers.
    _auth_exempt_paths = tokenless_paths | {"/v1/health"}

    @app.middleware("http")
    async def require_local_auth(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in _auth_exempt_paths:
            return await call_next(request)
        auth_token = request.headers.get("x-werub-auth", "")
        if not manager.auth.verify(auth_token or None):
            return JSONResponse(
                {"error": "authentication required", "auth_locked": True},
                status_code=403,
            )
        return await call_next(request)

    app.state.manager = manager

    # -- IP whitelist middleware -----------------------------------------------
    from ..config import load_config as _load_config

    _cfg = _load_config()
    _allowed_hosts: list[str] = _cfg.allowed_hosts

    @app.middleware("http")
    async def ip_whitelist(request: Request, call_next):
        if _allowed_hosts:
            client_host = request.client.host if request.client else None
            if client_host not in _allowed_hosts:
                return JSONResponse(
                    {"error": "host not allowed"},
                    status_code=403,
                )
        return await call_next(request)

    # -- local master password auth endpoints ---------------------------------

    @app.get("/v1/auth/status")
    def auth_status() -> dict[str, Any]:
        return manager.auth.status()

    @app.post("/v1/auth/setup")
    def auth_setup(body: dict) -> dict[str, Any]:
        try:
            token = manager.auth.setup(body.get("password", ""))
            return {"ok": True, "token": token}
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/v1/auth/login")
    def auth_login(body: dict) -> dict[str, Any]:
        try:
            token = manager.auth.login(body.get("password", ""))
            return {"ok": True, "token": token}
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.post("/v1/auth/logout")
    def auth_logout() -> dict[str, Any]:
        manager.auth.logout()
        return {"ok": True}

    @app.post("/v1/auth/change-password")
    def auth_change_password(body: dict) -> dict[str, Any]:
        try:
            token = manager.auth.change_password(
                body.get("old_password", ""),
                body.get("new_password", ""),
            )
            return {"ok": True, "token": token}
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    @app.get("/v1/health")
    def health(request: Request) -> dict[str, Any]:
        if api_token and not _request_authenticated(request):
            return {"status": "ok"}
        return {
            "status": "ok",
            "default_workspace": manager.default_workspace,
            "model": manager.model,
        }

    @app.get("/v1/agents")
    def agents() -> dict[str, Any]:
        return {"agents": manager.list_agents()}

    @app.get("/v1/personas")
    def personas() -> dict[str, Any]:
        return {"personas": manager.personas.list_all()}

    @app.get("/v1/inbox")
    def inbox(session_id: str = "", state: str = "") -> dict[str, Any]:
        from dataclasses import asdict

        # The cross-session Inbox list shows only Unattended (inbox-visibility) items; a per-session
        # query returns inline ones too, so the answer-in-context card sees parked attended prompts.
        items = manager.inbox.list(
            session_id=session_id or None,
            state=state or None,
            visibility=None if session_id else VIS_INBOX,
        )
        # Enrich with the originating session's context so the Inbox is self-contained — the
        # "go to session" chip needs title/agent/workspace without depending on a (possibly stale)
        # client-side session list, and can link straight to it.
        out: list[dict[str, Any]] = []
        for i in items:
            d = asdict(i)
            rec = manager.session_store.load(i.session_id)
            if (
                rec is None
                and not session_id
                and i.state == "pending"
                and i.session_id not in manager._engines
            ):
                # Lazy cleanup for legacy orphans (sessions deleted before delete_session
                # started closing their items): an orphaned prompt can never be answered.
                # A LIVE engine without a record yet (brand-new session, first turn still
                # running) is NOT an orphan — hence the engine guard.
                manager.inbox.resolve_session(i.session_id)
                continue
            d["session_title"] = (rec.title if rec else None) or i.session_id
            d["session_agent"] = rec.agent if rec else None
            d["session_workspace"] = rec.workspace if rec else None
            d["session_exists"] = rec is not None
            out.append(d)
        return {"items": out}

    @app.post("/v1/inbox/{item_id}/resolve")
    async def resolve_inbox_item(item_id: str, body: dict) -> dict[str, Any]:
        # Idempotent + first-responder-wins: ok=False means it was already resolved elsewhere.
        # Routes through resolve_inbox so a restart-orphaned prompt durably resumes its turn.
        ok = await manager.resolve_inbox(item_id, str(body.get("resolution", "deny")))
        return {"ok": ok}

    @app.get("/v1/subscriptions")
    def subscriptions() -> dict[str, Any]:
        # Global view-only list: each (session → channel) subscription, enriched with the session's
        # title/agent and the channel its Inbox routes OUT to (so an inbound/outbound collision on
        # the same channel is visible).
        out: list[dict[str, Any]] = []
        for sub in manager.subscriptions.all():
            rec = manager.session_store.load(sub.session_id)
            agent = rec.agent if rec else ""
            routing = manager._routing_targets(sub.session_id, agent or "cowork")
            out.append(
                {
                    "session_id": sub.session_id,
                    "session_title": (rec.title if rec else None) or sub.session_id,
                    "agent": agent,
                    "channel": sub.channel,
                    # Display name from the channel buffer ("#ocw-test"), when any inbound
                    # message has carried one — the address stays the identifier.
                    "channel_name": manager.channel_buffer.name_for(sub.channel),
                    "routing_target": routing[0] if routing else None,
                    "collision": bool(routing and sub.channel in routing),
                }
            )
        return {"subscriptions": out}

    @app.get("/v1/channels/recent")
    def recent_channels() -> dict[str, Any]:
        # The picker's "recently-seen" source: channels the bot has received messages from.
        return {"channels": manager.channel_buffer.channels()}

    @app.get("/v1/unrouted")
    def unrouted() -> dict[str, Any]:
        # Dead-letter view: inbound messages with no destination + background-turn failures.
        return {"items": manager.unrouted.list()}

    @app.post("/v1/subscriptions")
    def subscribe(body: dict) -> dict[str, Any]:
        from ..subscriptions import resolve_channel

        session_id = str(body.get("session_id", "")).strip()
        raw = str(body.get("channel", ""))
        addr = resolve_channel(raw)
        if not session_id or not addr or ":" not in addr:
            if raw.strip().startswith("#"):
                # A bare #name can't be looked up locally — storing it literally would create a
                # subscription that never matches real traffic (resolve_channel returns "").
                return {
                    "ok": False,
                    "error": "Channel names can't be looked up — paste the channel ID "
                    "(channel name ▸ About) or the channel's Copy-link URL.",
                }
            return {"ok": False, "error": "need a session_id and a channel"}
        manager.subscriptions.subscribe(session_id, addr)
        return {"ok": True, "channel": addr}

    @app.post("/v1/subscriptions/remove")
    def unsubscribe(body: dict) -> dict[str, Any]:
        from ..subscriptions import resolve_channel

        session_id = str(body.get("session_id", "")).strip()
        addr = resolve_channel(str(body.get("channel", "")))
        removed = manager.subscriptions.unsubscribe(session_id, addr)
        return {"ok": True, "removed": removed}

    @app.get("/v1/inbox/reconcile")
    def reconcile_inbox(session_id: str) -> dict[str, Any]:
        # Called when a session resumes attended control (surface pending + recap inline).
        return manager.inbox.reconcile_on_resume(session_id)

    @app.get("/v1/inbox/routing")
    def inbox_routing() -> dict[str, Any]:
        return {"bindings": manager.inbox_routing.bindings()}

    @app.post("/v1/inbox/routing/binding")
    def set_inbox_binding(body: dict) -> dict[str, Any]:
        name = str(body.get("name", "")).strip()
        if not name:
            return {"ok": False, "error": "binding needs a `name`"}
        return manager.set_inbox_binding(
            name,
            channel=body.get("channel") or None,
            target=str(body.get("target", "")),
        )

    @app.get("/v1/sessions/{session_id}/unattended")
    def get_unattended(session_id: str) -> dict[str, Any]:
        return {"unattended": manager.unattended.is_unattended(session_id)}

    @app.post("/v1/sessions/{session_id}/unattended")
    def set_unattended(session_id: str, body: dict) -> dict[str, Any]:
        # The GUI gates the on-transition behind a one-tap confirm.
        on = bool(body.get("unattended"))
        manager.unattended.set(session_id, on)
        return {"ok": True, "session_id": session_id, "unattended": on}

    @app.get("/v1/sessions/{session_id}/skills")
    def session_skills(session_id: str, workspace: str = "") -> dict[str, Any]:
        # The rail's Skills group + the composer popup both read this (SKILLS-SPEC §4.1).
        return manager.session_skills_view(session_id, workspace or None)

    @app.post("/v1/sessions/{session_id}/skills")
    def set_session_skill(session_id: str, body: dict) -> dict[str, Any]:
        # A session mute. `clear` drops the override (inherit again); otherwise explicit
        # on/off. Nothing on disk changes — Settings owns permanent state.
        body = body or {}
        skill = str(body.get("skill", "")).strip()
        if not skill:
            return {"ok": False, "error": "skill required"}
        if body.get("clear"):
            manager.session_skills.clear(session_id, skill)
        else:
            manager.session_skills.set(session_id, skill, bool(body.get("enabled", False)))
        return manager.session_skills_view(session_id, str(body.get("workspace", "")) or None)

    @app.get("/v1/sessions/{session_id}/connections")
    def session_connections(session_id: str, persona: str = "") -> dict[str, Any]:
        # `persona` is the GUI's hint for brand-new sessions (no record yet) — without it the
        # view resolves to the default persona and shows the wrong defaults/recommends.
        # §6: the Sources drawer payload — connected connectors w/ state + recommended + ⚠ count.
        return manager.session_connections_view(session_id, persona or None)

    @app.post("/v1/sessions/{session_id}/connections")
    def set_session_connection(session_id: str, body: dict) -> dict[str, Any]:
        # §6: a session override. `clear` drops the override (inherit the persona default again);
        # otherwise set an explicit on/off. Return the refreshed view so the drawer can re-render.
        body = body or {}
        connector = str(body.get("connector", "")).strip()
        if not connector:
            return {"ok": False, "error": "connector required"}
        if body.get("clear"):
            manager.session_connections.clear(session_id, connector)
        else:
            manager.session_connections.set(session_id, connector, bool(body.get("enabled", False)))
        persona = str(body.get("persona", "")) or None
        return {
            "ok": True,
            "connections": manager.session_connections_view(session_id, persona),
        }

    @app.post("/v1/personas/install")
    def install_persona(body: dict) -> dict[str, Any]:
        # Returns a consent summary per persona; they land disabled pending the user's approval
        # (then POST /v1/personas/{id} {enabled:true, surfaced:true}).
        reg = manager.personas
        try:
            if body.get("git_url"):
                summaries = reg.install_from_git(str(body["git_url"]))
            elif body.get("dir"):
                summaries = reg.install_from_dir(str(body["dir"]))
            elif body.get("gallery_slug"):
                return {
                    "ok": False,
                    "error": "Gallery install is not available — install personas from a folder or Git URL",
                }
            else:
                return {
                    "ok": False,
                    "error": "provide a `dir`, `git_url`, or `gallery_slug`",
                }
        except Exception as e:  # surface manifest/clone errors to the caller
            return {"ok": False, "error": str(e)}
        return {"ok": True, "consent": summaries, "personas": reg.list_all()}

    @app.get("/v1/cloud/gallery/{slug}")
    def cloud_gallery_detail(slug: str) -> dict[str, Any]:
        return {"ok": False, "error": "Gallery not available"}

    @app.get("/v1/cloud/gallery")
    def cloud_gallery() -> dict[str, Any]:
        return {"ok": False, "error": "Gallery not available", "personas": []}

    @app.post("/v1/personas/{persona_id}")
    def update_persona(persona_id: str, body: dict) -> dict[str, Any]:
        reg = manager.personas
        archived = 0
        try:
            if "enabled" in body:
                # Disable archives the persona's sessions atomically (server-side, one
                # request) so any client gets the same semantic. See set_persona_enabled.
                archived = manager.set_persona_enabled(persona_id, bool(body["enabled"]))[
                    "archived_sessions"
                ]
            if "surfaced" in body:
                reg.set_surfaced(persona_id, bool(body["surfaced"]))
            if body.get("default"):
                reg.set_default(persona_id)
        except KeyError:
            return {"ok": False, "error": f"unknown persona: {persona_id}"}
        return {"ok": True, "personas": reg.list_all(), "archived_sessions": archived}

    @app.delete("/v1/personas/{persona_id}")
    def persona_delete(persona_id: str) -> dict[str, Any]:
        # Uninstall a non-builtin persona (snapshot dir + lifecycle state). Local
        # operation — works signed out, regardless of where the persona came from.
        try:
            manager.personas.uninstall(persona_id)
        except KeyError:
            return {"ok": False, "error": f"unknown persona: {persona_id}"}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "personas": manager.personas.list_all()}

    @app.get("/v1/personas/{persona_id}")
    def persona_detail(persona_id: str) -> dict[str, Any]:
        # §5 detail page: identity + capabilities + recommends(+connected) + default connections.
        detail = manager.persona_detail(persona_id)
        if detail is None:
            return {"ok": False, "error": f"unknown persona: {persona_id}"}
        return detail

    @app.post("/v1/personas/{persona_id}/enable")
    def persona_enable(persona_id: str, body: dict) -> dict[str, Any]:
        # Dedicated §5/§8 route; delegates to the same manager toggle as POST /v1/personas/{id}
        # (so disable archives the persona's sessions here too).
        try:
            manager.set_persona_enabled(persona_id, bool((body or {}).get("enabled", True)))
        except KeyError:
            return {"ok": False, "error": f"unknown persona: {persona_id}"}
        return {"ok": True, "personas": manager.personas.list_all()}

    @app.post("/v1/personas/{persona_id}/connections")
    def persona_set_connection(persona_id: str, body: dict) -> dict[str, Any]:
        # §5: flip a persona-default connector on/off; re-reads so the client can refresh.
        body = body or {}
        connector = str(body.get("connector", "")).strip()
        if not connector:
            return {"ok": False, "error": "connector required"}
        return manager.set_persona_connection(
            persona_id, connector, bool(body.get("enabled", False))
        )

    @app.get("/v1/skills")
    def skills(workspace: str = "") -> dict[str, Any]:
        return {"skills": manager.list_skills(workspace or None)}

    @app.post("/v1/skills")
    def create_skill(body: dict) -> dict[str, Any]:
        return manager.create_skill(body or {})

    @app.patch("/v1/skills/{name}")
    def update_skill(name: str, body: dict) -> dict[str, Any]:
        return manager.update_skill(name, body or {})

    @app.delete("/v1/skills/{name}")
    def delete_skill(name: str, workspace: str = "") -> dict[str, Any]:
        return manager.delete_skill(name, workspace or None)

    @app.post("/v1/skills/{name}/move")
    def move_skill(name: str, body: dict) -> dict[str, Any]:
        return manager.move_skill(name, body or {})

    @app.post("/v1/skills/{name}/reveal")
    def reveal_skill(name: str, body: dict) -> dict[str, Any]:
        # §6 "Show folder": open the skill's folder in the OS file manager (local machine).
        return manager.reveal_skill(name, str((body or {}).get("workspace", "")) or None)

    @app.post("/v1/skills/upload")
    def stage_skill_upload(body: dict) -> dict[str, Any]:
        # Stage → preview; nothing is installed until /upload/confirm (SKILLS-SPEC §4.2).
        data_b64 = str((body or {}).get("data_b64", ""))
        if not data_b64:
            return {"ok": False, "error": "No archive supplied."}
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (ValueError, binascii.Error):
            return {"ok": False, "error": "Invalid archive encoding."}
        return manager.stage_skill_upload(data, str((body or {}).get("filename", "")))

    @app.post("/v1/skills/upload/confirm")
    def confirm_skill_upload(body: dict) -> dict[str, Any]:
        return manager.confirm_skill_upload(body or {})

    @app.get("/v1/workspaces/recent")
    def recent_workspaces() -> dict[str, Any]:
        return {"workspaces": manager.recent_workspaces()}

    @app.post("/v1/workspaces/open")
    def open_workspace(body: dict) -> dict[str, Any]:
        return manager.open_workspace(body.get("path", ""), create=bool(body.get("create")))

    @app.get("/v1/workspaces/trusted")
    def trusted_workspaces() -> dict[str, Any]:
        return {"workspaces": manager.trusted_workspaces()}

    @app.post("/v1/workspaces/trust")
    def set_workspace_trust(body: dict) -> dict[str, Any]:
        return manager.set_workspace_trust(
            str((body or {}).get("path", "")),
            trusted=bool((body or {}).get("trusted", False)),
        )

    @app.post("/v1/workspaces/pick")
    async def pick_workspace() -> dict[str, Any]:
        # Native folder picker opened by the LOCAL sidecar (browser GUIs can't get absolute
        # paths from web file dialogs). Off the event loop: blocks until pick/cancel.
        return await asyncio.to_thread(manager.pick_native_folder)

    @app.get("/v1/sessions")
    def sessions(workspace: str | None = None) -> dict[str, Any]:
        return {"sessions": manager.list_sessions(workspace)}

    @app.get("/v1/sessions/{session_id}/messages")
    def session_messages(session_id: str) -> dict[str, Any]:
        return {"messages": manager.session_messages(session_id)}

    @app.patch("/v1/sessions/{session_id}")
    def session_patch(session_id: str, body: dict) -> dict[str, Any]:
        body = body or {}
        if "pinned" in body or "archived" in body:
            return manager.set_session_flags(
                session_id,
                pinned=bool(body["pinned"]) if "pinned" in body else None,
                archived=bool(body["archived"]) if "archived" in body else None,
            )
        return manager.rename_session(session_id, str(body.get("title", "")))

    @app.delete("/v1/sessions/{session_id}")
    def session_delete(session_id: str) -> dict[str, Any]:
        return manager.delete_session(session_id)

    @app.get("/v1/sessions/{session_id}/roots")
    def session_roots(session_id: str) -> dict[str, Any]:
        return {"roots": manager.get_roots(session_id)}

    @app.post("/v1/sessions/{session_id}/roots")
    def session_add_root(session_id: str, body: dict) -> dict[str, Any]:
        body = body or {}
        return manager.add_root(
            session_id, str(body.get("path", "")), bool(body.get("writable", False))
        )

    @app.delete("/v1/sessions/{session_id}/roots")
    def session_remove_root(session_id: str, path: str) -> dict[str, Any]:
        return manager.remove_root(session_id, path)

    @app.get("/v1/sessions/{session_id}/artifacts")
    def session_artifacts(session_id: str) -> dict[str, Any]:
        return {"artifacts": manager.list_artifacts(session_id)}

    @app.get("/v1/sessions/{session_id}/artifacts/read")
    def session_artifact_read(session_id: str, path: str) -> dict[str, Any]:
        return manager.read_artifact(session_id, path)

    @app.post("/v1/sessions/{session_id}/artifacts/reveal")
    def session_artifact_reveal(session_id: str, body: dict) -> dict[str, Any]:
        body = body or {}
        return manager.reveal_artifact(
            session_id, str(body.get("path", "")), str(body.get("mode", "reveal"))
        )

    @app.get("/v1/memory")
    def memory() -> dict[str, Any]:
        return {"memory": manager.list_memory()}

    @app.post("/v1/memory")
    def add_memory(body: dict) -> dict[str, Any]:
        return manager.add_memory(body.get("content", ""), body.get("scope", "workspace"))

    @app.post("/v1/chat/completions")
    def chat_completions(body: dict) -> dict[str, Any]:
        model = body.get("model", manager.model)
        turn = manager.provider_complete(model, body.get("messages", []), body.get("tools"))
        return _openai_response(model, turn)

    # -- MCP servers ------------------------------------------------------------
    @app.get("/v1/mcp")
    def mcp_list() -> dict[str, Any]:
        return {"servers": manager.list_mcp()}

    @app.post("/v1/mcp")
    def mcp_add(body: dict) -> dict[str, Any]:
        name = body.get("name")
        config = body.get("config")
        if not name or not isinstance(config, dict):
            return {"ok": False, "error": "name and config required"}
        return manager.add_mcp(name, config)

    @app.patch("/v1/mcp/{name}")
    def mcp_patch(name: str, body: dict) -> dict[str, Any]:
        return manager.patch_mcp(name, body or {})

    @app.delete("/v1/mcp/{name}")
    def mcp_delete(name: str) -> dict[str, Any]:
        return manager.delete_mcp(name)

    @app.get("/v1/mcp/{name}/tools")
    async def mcp_tools(name: str) -> dict[str, Any]:
        return await manager.mcp_tools(name)

    @app.post("/v1/mcp/{name}/connect")
    async def mcp_connect(name: str) -> dict[str, Any]:
        # Connect now. For `auth: oauth` servers the first connect opens the system
        # browser and waits on the loopback callback — that can take minutes, so it
        # runs as a background task; the GUI polls /v1/mcp for the status flip
        # (authorizing → connected | needs_auth + last_error).
        asyncio.create_task(manager.connect_mcp(name))
        return {"ok": True, "started": True}

    @app.post("/v1/mcp/{name}/signout")
    async def mcp_signout(name: str) -> dict[str, Any]:
        return await manager.signout_mcp(name)

    @app.get("/mcp/oauth/callback")
    async def mcp_oauth_callback(code: str = "", state: str = "", error: str = "") -> Any:
        # Loopback landing for the MCP OAuth browser flow (mcp/oauth.py). Browser-facing:
        # returns the same styled page as the managed-connector callbacks.
        from fastapi.responses import HTMLResponse

        from ..mcp import oauth as mcp_oauth

        if error:
            return HTMLResponse(
                _browser_page(
                    "Sign-in failed",
                    "The service reported an error. Return to OpenWorker and try again.",
                    ok=False,
                    error=error,
                ),
                status_code=400,
            )
        if not code or not mcp_oauth.deliver_callback(code, state or None):
            return HTMLResponse(
                _browser_page(
                    "Nothing waiting for this sign-in",
                    "The sign-in may have timed out. Return to OpenWorker and start it again.",
                    ok=False,
                ),
                status_code=400,
            )
        return HTMLResponse(
            _browser_page(
                "Connected",
                "Sign-in complete. You can close this tab and return to OpenWorker.",
                ok=True,
            )
        )

    @app.post("/v1/mcp/reload")
    async def mcp_reload() -> dict[str, Any]:
        return await manager.reload_mcp()

    # -- connectors (Slack / Telegram / …) --------------------------------------
    @app.get("/v1/connectors")
    def connectors_list() -> dict[str, Any]:
        return {"connectors": manager.list_connectors()}

    async def _refresh_listeners_if_two_way(name: str) -> None:
        # New/removed creds only take effect when the platform socket reconnects (Socket Mode
        # authenticates at connect time) — hot-reload the listeners in-process so pasting
        # tokens works immediately, no sidecar restart (§19).
        from ..connectors.config import PLATFORMS

        if name in PLATFORMS:
            try:
                await manager.refresh_gateway()
            except Exception:
                pass  # a listener that fails to come up must not fail the save

    @app.post("/v1/connectors/{name}/connect")
    async def connector_connect(name: str, body: dict) -> dict[str, Any]:
        fields = body.get("fields") if isinstance(body, dict) else None
        # experimental connectors require the caller to explicitly acknowledge the risk notice
        acknowledged = bool(isinstance(body, dict) and body.get("acknowledge_risk"))
        # token validation does a blocking HTTP call → keep it off the event loop
        result = await asyncio.to_thread(
            lambda: manager.connect_connector(name, fields or {}, acknowledged=acknowledged)
        )
        if result.get("ok"):
            await _refresh_listeners_if_two_way(name)
        return result

    @app.post("/v1/connectors/{name}/mcp-connect")
    async def connector_mcp_connect(name: str) -> dict[str, Any]:
        # One-click connect for an MCP-backed connector: the browser OAuth flow can
        # take minutes, so it runs in the background; the GUI polls /v1/connectors
        # until the card flips to connected (mode "mcp").
        from ..connectors.descriptors import get_descriptor

        d = get_descriptor(name)
        if d is None or not d.mcp_url:
            return {"ok": False, "error": f"{name} has no MCP connect path"}
        asyncio.create_task(manager.mcp_connect_connector(name))
        return {"ok": True, "started": True}

    @app.post("/v1/connectors/{name}/disconnect")
    async def connector_disconnect(name: str) -> dict[str, Any]:
        # Managed profiles: best-effort flip of the cloud metadata record first
        # (network call → off the loop). Local deletion always proceeds.
        from .. import cloud
        from ..config import load_config

        await asyncio.to_thread(
            lambda: cloud.cloud_disconnect(manager.secrets, load_config(), name)
        )
        result = manager.disconnect_connector(name)
        await _refresh_listeners_if_two_way(name)
        return result

    @app.post("/v1/connectors/slack/workspaces/{team_id}/disconnect")
    async def slack_workspace_disconnect(team_id: str) -> dict[str, Any]:
        """Stop relaying one workspace (managed relay). Cloud routing row deleted
        best-effort, local per-team token removed, gateway hot-reloaded."""
        return await manager.disconnect_slack_workspace(team_id)

    @app.get("/v1/connectors/slack/status")
    async def slack_status() -> dict[str, Any]:
        """Slack health, three layers: relay socket / cloud sign-in / per-team tokens."""
        return manager.slack_status()

    @app.post("/v1/connectors/github/installations/{installation_id}/disconnect")
    async def github_installation_disconnect(installation_id: str) -> dict[str, Any]:
        """Stop relaying one GitHub App installation (managed relay). Cloud
        routing rows deleted best-effort, local profile removed, gateway
        hot-reloaded."""
        return await manager.disconnect_github_installation(installation_id)

    @app.get("/v1/connectors/github/status")
    async def github_status() -> dict[str, Any]:
        """GitHub health: relay socket / cloud sign-in / per-installation tokens."""
        return manager.github_status()

    @app.post("/v1/connectors/gmail/accounts/{email}/disconnect")
    async def gmail_account_disconnect(email: str) -> dict[str, Any]:
        """Drop ONE mailbox (cloud metadata best-effort first, like a full
        disconnect); the default pointer moves to the next account."""
        from .. import cloud
        from ..config import load_config
        from ..connectors import gmail_accounts

        profile_key = gmail_accounts.PREFIX + email.strip().lower()
        await asyncio.to_thread(
            lambda: cloud.cloud_disconnect(
                manager.secrets, load_config(), "gmail", profile_key=profile_key
            )
        )
        return gmail_accounts.disconnect_account(manager.secrets, email)

    @app.post("/v1/connectors/gmail/accounts/{email}/default")
    def gmail_account_default(email: str) -> dict[str, Any]:
        from ..connectors import gmail_accounts

        return gmail_accounts.set_default(manager.secrets, email)

    @app.patch("/v1/connectors/gmail/filters")
    def gmail_filters(body: dict) -> dict[str, Any]:
        """Replace the "Never show agents" lists. Enforced in the local tool
        layer; agents see silent omissions, the user sees counts + audit."""
        from ..connectors import gmail_accounts

        senders = body.get("senders") if isinstance(body, dict) else None
        labels = body.get("labels") if isinstance(body, dict) else None
        if senders is not None and not isinstance(senders, list):
            return {"ok": False, "error": "senders must be a list"}
        if labels is not None and not isinstance(labels, list):
            return {"ok": False, "error": "labels must be a list"}
        return gmail_accounts.set_filters(manager.secrets, senders, labels)

    @app.post("/v1/connectors/google_calendar/accounts/{email}/disconnect")
    async def gcal_account_disconnect(email: str) -> dict[str, Any]:
        """Drop ONE Google Calendar account (cloud metadata best-effort first);
        the default pointer moves to the next account."""
        from .. import cloud
        from ..config import load_config
        from ..connectors import gcal_accounts

        profile_key = gcal_accounts.PREFIX + email.strip().lower()
        await asyncio.to_thread(
            lambda: cloud.cloud_disconnect(
                manager.secrets,
                load_config(),
                "google_calendar",
                profile_key=profile_key,
            )
        )
        return gcal_accounts.disconnect_account(manager.secrets, email)

    @app.post("/v1/connectors/google_calendar/accounts/{email}/default")
    def gcal_account_default(email: str) -> dict[str, Any]:
        from ..connectors import gcal_accounts

        return gcal_accounts.set_default(manager.secrets, email)

    @app.post("/v1/connectors/hubspot/portals/{hub_id}/disconnect")
    async def hubspot_portal_disconnect(hub_id: str) -> dict[str, Any]:
        from .. import cloud
        from ..config import load_config
        from ..connectors import hubspot_portals

        profile_key = hubspot_portals.PREFIX + hub_id.strip()
        await asyncio.to_thread(
            lambda: cloud.cloud_disconnect(
                manager.secrets, load_config(), "hubspot", profile_key=profile_key
            )
        )
        return hubspot_portals.disconnect_portal(manager.secrets, hub_id)

    @app.post("/v1/connectors/hubspot/portals/{hub_id}/default")
    def hubspot_portal_default(hub_id: str) -> dict[str, Any]:
        from ..connectors import hubspot_portals

        return hubspot_portals.set_default(manager.secrets, hub_id)

    @app.post("/v1/connectors/{name}/accounts/{account_id}/disconnect")
    async def account_disconnect(name: str, account_id: str) -> dict[str, Any]:
        """Generic per-account disconnect for account-patterned connectors
        (batch 2+). Gmail/Calendar keep their specific email routes."""
        from .. import cloud
        from ..config import load_config
        from ..connectors import accounts

        if not accounts.is_account_connector(name):
            return {"ok": False, "error": "not a multi-account connector"}
        _id, profile_key, profile = accounts.resolve(manager.secrets, name, account_id)
        if profile and profile.get("managed"):
            await asyncio.to_thread(
                lambda: cloud.cloud_disconnect(
                    manager.secrets, load_config(), name, profile_key=profile_key
                )
            )
        return accounts.disconnect_account(manager.secrets, name, account_id)

    @app.post("/v1/connectors/{name}/accounts/{account_id}/default")
    def account_default(name: str, account_id: str) -> dict[str, Any]:
        from ..connectors import accounts

        if not accounts.is_account_connector(name):
            return {"ok": False, "error": "not a multi-account connector"}
        return accounts.set_default(manager.secrets, name, account_id)

    @app.patch("/v1/connectors/hubspot/hidden-fields")
    def hubspot_hidden_fields(body: dict) -> dict[str, Any]:
        """Replace the hidden-fields denylist (property names stripped from every
        record agents read — model-facing policy, not a human ACL)."""
        from ..connectors import hubspot_portals

        fields = body.get("hidden_fields") if isinstance(body, dict) else None
        if not isinstance(fields, list):
            return {"ok": False, "error": "hidden_fields must be a list"}
        return hubspot_portals.set_hidden_fields(manager.secrets, fields)

    @app.post("/v1/connectors/{name}/unauthorized/{item_id}")
    async def connector_unauthorized_resolve(name: str, item_id: str, body: dict) -> dict[str, Any]:
        # Resolve a parked unauthorized message: dismiss / allow / allow_deliver (§19).
        action = str((body or {}).get("action", "")).strip()
        return await manager.resolve_unauthorized(name, item_id, action)

    # -- SSH server management --------------------------------------------------

    @app.get("/v1/ssh/servers")
    def ssh_servers_list() -> dict[str, Any]:
        from ..connectors.ssh import list_servers

        return {"ok": True, "servers": list_servers(manager.secrets)}

    @app.post("/v1/ssh/servers")
    def ssh_servers_add(body: dict) -> dict[str, Any]:
        from ..connectors.ssh import add_server

        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid body"}
        # SEC-13: Validate input fields
        server_id = str(body.get("server_id", "")).strip()
        host = str(body.get("host", "")).strip()
        if not server_id:
            return {"ok": False, "error": "server_id is required"}
        if not host:
            return {"ok": False, "error": "host is required"}
        if " " in host or "\t" in host or len(host) > 253:
            return {"ok": False, "error": "invalid host format"}
        try:
            port = int(body.get("port", 22))
        except (ValueError, TypeError):
            return {"ok": False, "error": "port must be a number"}
        if not (1 <= port <= 65535):
            return {"ok": False, "error": "port must be between 1 and 65535"}
        return add_server(
            manager.secrets,
            server_id=server_id,
            host=host,
            port=port,
            username=str(body.get("username", "deploy")).strip(),
            key_path=str(body.get("key_path", "")).strip(),
            label=str(body.get("label", "")).strip(),
            tags=body.get("tags") if isinstance(body.get("tags"), list) else [],
            vault=manager.vault,
        )

    @app.put("/v1/ssh/servers/{server_id}")
    def ssh_servers_update(server_id: str, body: dict) -> dict[str, Any]:
        """Update an existing SSH server profile."""
        from ..connectors.ssh import add_server, remove_server

        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid body"}
        # SEC-13: Validate input fields
        host = str(body.get("host", "")).strip()
        if not host:
            return {"ok": False, "error": "host is required"}
        if " " in host or "\t" in host or len(host) > 253:
            return {"ok": False, "error": "invalid host format"}
        try:
            port = int(body.get("port", 22))
        except (ValueError, TypeError):
            return {"ok": False, "error": "port must be a number"}
        if not (1 <= port <= 65535):
            return {"ok": False, "error": "port must be between 1 and 65535"}
        # Remove then re-add with new values
        rm = remove_server(manager.secrets, server_id)
        if not rm.get("ok"):
            return rm
        return add_server(
            manager.secrets,
            server_id=server_id,
            host=host,
            port=port,
            username=str(body.get("username", "deploy")).strip(),
            key_path=str(body.get("key_path", "")).strip(),
            label=str(body.get("label", "")).strip(),
            tags=body.get("tags") if isinstance(body.get("tags"), list) else [],
            vault=manager.vault,
        )

    @app.delete("/v1/ssh/servers/{server_id}")
    def ssh_servers_remove(server_id: str) -> dict[str, Any]:
        from ..connectors.ssh import remove_server
        from ..security.rate_limiter import get_limiter

        limiter = get_limiter("destructive", 10, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        return remove_server(manager.secrets, server_id)

    @app.post("/v1/ssh/servers/{server_id}/test")
    async def ssh_servers_test(server_id: str) -> dict[str, Any]:
        from ..connectors.ssh import get_server
        from ..connectors.ssh.client import SSHClient

        server = get_server(manager.secrets, server_id, vault=manager.vault)
        if server is None:
            return {"ok": False, "error": f"server '{server_id}' not found"}
        result = await asyncio.to_thread(lambda: SSHClient(server).test_connection())
        return result

    @app.get("/v1/ssh/servers/{server_id}/fingerprint")
    async def ssh_server_fingerprint(server_id: str) -> dict[str, Any]:
        from ..connectors.ssh import get_server
        from ..connectors.ssh.client import SSHClient

        server = get_server(manager.secrets, server_id, vault=manager.vault)
        if server is None:
            return {"ok": False, "error": f"server '{server_id}' not found"}
        result = await asyncio.to_thread(lambda: SSHClient(server).get_fingerprint())
        return result

    @app.post("/v1/vault/change-master")
    def vault_change_master(body: dict) -> dict[str, Any]:
        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid body"}
        old_password = str(body.get("old_password", ""))
        new_password = str(body.get("new_password", ""))
        if not old_password or not new_password:
            return {"ok": False, "error": "old_password and new_password are required"}
        return manager.vault.change_master(old_password, new_password)

    # -- Ops dashboard status ---------------------------------------------------

    # Alert thresholds (module-level mutable config)
    _alert_thresholds: dict[str, float] = {"cpu": 90, "memory": 85, "disk": 90}

    # Metrics store for history (Step 7)
    from ..tools.server_monitor import MetricsStore as _MetricsStore

    _metrics_store = _MetricsStore(manager._data_base)

    # v2.0: Monitoring subsystem — TimeSeriesStore for long-term metrics
    from ..monitoring.timeseries import TimeSeriesStore as _TSStore

    _ts_store = _TSStore(manager._data_base)

    @app.get("/v1/ops/alerts/config")
    def ops_alerts_config_get() -> dict[str, Any]:
        """Return current alert threshold config."""
        return {"ok": True, "thresholds": dict(_alert_thresholds)}

    @app.post("/v1/ops/alerts/config")
    def ops_alerts_config_set(body: dict) -> dict[str, Any]:
        """Update alert thresholds."""
        for key in ("cpu", "memory", "disk"):
            if key in body:
                try:
                    _alert_thresholds[key] = float(body[key])
                except (TypeError, ValueError):
                    pass
        return {"ok": True, "thresholds": dict(_alert_thresholds)}

    @app.get("/v1/ops/local-status")
    async def ops_local_status() -> dict[str, Any]:
        """Quick local server status for the OpsView dashboard.
        Also checks thresholds and broadcasts alerts, and records metrics."""
        from ..tools.server_monitor import _check_thresholds, _server_status

        status = _server_status()

        # Record metrics to history store
        cpu = status.get("cpu_percent", 0)
        mem = status.get("memory", {}).get("percent", 0) if isinstance(status.get("memory"), dict) else 0
        disk = status.get("disk_root", {}).get("percent", 0) if isinstance(status.get("disk_root"), dict) else 0
        try:
            _metrics_store.record("local", cpu, mem, disk)
            _ts_store.record("__local__", cpu=cpu, memory=mem, disk=disk)
        except Exception:
            pass  # never fail the status endpoint for metrics

        # Check thresholds and broadcast alerts
        alerts = _check_thresholds(status, _alert_thresholds)
        if alerts:
            try:
                await manager.broadcast_event({
                    "type": "server_alert",
                    "alerts": alerts,
                })
            except Exception:
                pass
            status["alerts"] = alerts

        return status

    @app.get("/v1/ops/metrics")
    def ops_metrics(range: str = "1h") -> dict[str, Any]:
        """Return metrics history. range: 1h/6h/24h/7d."""
        range_map = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 86400}
        seconds = range_map.get(range, 3600)
        history = _metrics_store.get_history("local", seconds)
        return {"ok": True, "metrics": history, "range": range, "range_seconds": seconds}

    @app.get("/v1/ops/processes")
    def ops_processes(filter: str = "") -> dict[str, Any]:
        """List running processes, optionally filtered by name."""
        from ..tools.server_monitor import _process_list

        return _process_list(filter=filter or "")

    @app.get("/v1/ops/ports")
    def ops_ports(ports: str = "80,443,8080,8765,5432,3306") -> dict[str, Any]:
        """Check if common ports are open on localhost."""
        from ..tools.server_monitor import _check_ports

        return _check_ports(host="localhost", ports=ports)

    @app.get("/v1/ops/services")
    def ops_service_status(service: str = "") -> dict[str, Any]:
        """Check system service status (systemctl/launchctl)."""
        from ..tools.server_monitor import _service_status

        if not service.strip():
            return {"ok": False, "error": "service name required"}
        return _service_status(service=service.strip())

    # -- Process kill + network stats (S10, S11) --------------------------------

    @app.post("/v1/ops/processes/{pid}/kill")
    def ops_kill_process(pid: int, body: dict) -> dict[str, Any]:
        """Kill a process by PID. Rate-limited."""
        from ..security.rate_limiter import get_limiter
        from ..tools.server_monitor import _kill_process

        limiter = get_limiter("kill_process", 5, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        signal_name = str((body or {}).get("signal", "TERM")).strip()
        return _kill_process(pid, signal_name)

    @app.get("/v1/ops/network")
    def ops_network() -> dict[str, Any]:
        """Get network interface statistics."""
        from ..tools.server_monitor import _network_stats

        return _network_stats()

    # -- Audit log dashboard (SEC-19) -------------------------------------------

    @app.get("/v1/audit/log")
    def ops_audit_log(days: int = 7) -> dict[str, Any]:
        """Read recent vault audit log entries."""
        from ..wiki.vault import read_audit_entries

        days = max(1, min(days, 90))
        entries = read_audit_entries(days=days)
        return {"ok": True, "entries": entries, "days": days}

    # -- Health check schedule (S12) --------------------------------------------

    # v2.0: Use persistent HealthCheckManager instead of in-memory HealthChecker
    from ..monitoring.healthcheck import HealthCheckManager as _HCManager, HealthCheckRule as _HCRule

    _hc_manager = _HCManager(manager._data_base)

    # Legacy in-memory checker kept for backward compat
    from ..tools.server_monitor import HealthChecker as _HealthChecker

    _health_checker = _HealthChecker()

    @app.get("/v1/ops/healthcheck")
    def ops_healthcheck_list() -> dict[str, Any]:
        """List configured health checks (persistent + legacy)."""
        persistent = _hc_manager.list_checks(enabled_only=False)
        legacy = list(_health_checker.checks)
        return {"ok": True, "checks": persistent, "legacy_checks": legacy,
                "enabled": _health_checker.enabled}

    @app.post("/v1/ops/healthcheck")
    def ops_healthcheck_add(body: dict) -> dict[str, Any]:
        """Add a health check (saved to persistent store)."""
        body = body or {}
        check_type = str(body.get("type", "")).strip()
        target = str(body.get("target", "")).strip()
        name = str(body.get("name", "")).strip() or f"{check_type}:{target}"
        if not check_type or not target:
            return {"ok": False, "error": "type and target required"}
        # Map legacy types to new types
        type_map = {"port": "tcp", "https": "http"}
        hc_type = type_map.get(check_type, check_type)
        rule = _HCRule(
            id="", name=name, type=hc_type, target=target,
            timeout_seconds=int(body.get("timeout_sec", 5)),
        )
        import os
        rule.id = f"hc-{os.urandom(4).hex()}"
        result = _hc_manager.add_check(rule)
        checks = _hc_manager.list_checks(enabled_only=False)
        return {**result, "checks": checks}

    @app.delete("/v1/ops/healthcheck/{index}")
    def ops_healthcheck_remove(index: int | str) -> dict[str, Any]:
        """Remove a health check by ID or legacy index."""
        check_id = str(index)
        result = _hc_manager.remove_check(check_id)
        if not result.get("ok"):
            # Fallback to legacy index
            try:
                result = _health_checker.remove_check(int(index))
            except (ValueError, IndexError):
                pass
        checks = _hc_manager.list_checks(enabled_only=False)
        return {**result, "checks": checks}

    @app.post("/v1/ops/healthcheck/run")
    async def ops_healthcheck_run() -> dict[str, Any]:
        """Run all persistent health checks now."""
        results = await _hc_manager.run_checks()
        return {"ok": True, "results": [r if isinstance(r, dict) else r.to_dict() for r in results]}

    @app.get("/v1/ops/healthcheck/history")
    def ops_healthcheck_history(key: str = "", check_id: str = "") -> dict[str, Any]:
        """Get health check history (persistent or legacy)."""
        cid = check_id or key
        if cid:
            history = _hc_manager.get_history(cid, hours=24)
            uptime = _hc_manager.uptime_percentage(cid, days=7)
            return {"ok": True, "check_id": cid, "history": history, "uptime_pct": uptime}
        return {"ok": True, "history": _health_checker.get_history(key)}

    # -- Docker REST endpoints --------------------------------------------------

    @app.get("/v1/docker/containers")
    def docker_containers_list(all: bool = False) -> dict[str, Any]:
        """List Docker containers (JSON format)."""
        from ..tools.docker_mgmt import _list_containers

        return _list_containers(all=all)

    @app.post("/v1/docker/containers/{container_id}/{action}")
    def docker_container_action(container_id: str, action: str) -> dict[str, Any]:
        """Start/stop/restart a Docker container."""
        from ..tools.docker_mgmt import _container_action

        return _container_action(container_id, action)

    @app.get("/v1/docker/containers/{container_id}/logs")
    def docker_container_logs(container_id: str, tail: int = 100) -> dict[str, Any]:
        """Get Docker container logs."""
        from ..tools.docker_mgmt import _container_logs

        return _container_logs(container_id, tail=tail)

    # -- Database config management ---------------------------------------------

    @app.get("/v1/databases")
    def databases_list() -> dict[str, Any]:
        from ..tools.db_mgmt import _list_databases

        return {"ok": True, "databases": _list_databases(manager)}

    @app.post("/v1/databases")
    def databases_add(body: dict) -> dict[str, Any]:
        from ..tools.db_mgmt import _add_database

        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid body"}
        # SEC-13: Validate input fields
        name = str(body.get("name", "")).strip()
        db_type = str(body.get("type", "")).strip()
        if not name:
            return {"ok": False, "error": "name is required"}
        if not db_type:
            return {"ok": False, "error": "type is required"}
        host = str(body.get("host", "")).strip()
        if host and (" " in host or "\t" in host or len(host) > 253):
            return {"ok": False, "error": "invalid host format"}
        try:
            port = int(body.get("port", 0))
        except (ValueError, TypeError):
            return {"ok": False, "error": "port must be a number"}
        if port and not (1 <= port <= 65535):
            return {"ok": False, "error": "port must be between 1 and 65535"}
        return _add_database(
            manager,
            name=name,
            db_type=db_type,
            host=host,
            port=port,
            db_name=str(body.get("database", "")).strip(),
            user=str(body.get("user", "")).strip(),
            password=str(body.get("password", "")).strip(),
            path=str(body.get("path", "")).strip(),
        )

    @app.post("/v1/databases/scan")
    async def databases_scan(body: dict | None = None) -> dict[str, Any]:
        """Scan local and network for running database services.

        body.subnet: optional subnet to scan (e.g. "192.168.1"), defaults to auto-detect.
        body.range: optional host range (e.g. "1-254"), defaults to common hosts.
        body.full: if true, scan full subnet 1-254 (slower, ~30s).
        """
        import asyncio
        import socket

        body = body or {}
        full_scan = bool(body.get("full", False))
        custom_subnet = str(body.get("subnet", "")).strip()
        custom_range = str(body.get("range", "")).strip()

        # DB port definitions
        DB_PORTS = [
            (5432, "postgresql", "PostgreSQL"),
            (3306, "mysql", "MySQL"),
            (27017, "mongodb", "MongoDB"),
            (6379, "redis", "Redis"),
            (1433, "mssql", "SQL Server"),
            (9200, "elasticsearch", "Elasticsearch"),
            (5433, "postgresql", "PostgreSQL (alt)"),
            (3307, "mysql", "MySQL (alt)"),
            (26257, "cockroachdb", "CockroachDB"),
            (8123, "clickhouse", "ClickHouse"),
        ]

        # --- Detect local network interfaces ---
        network_info = []
        subnets: set[str] = set()
        my_ip = ""
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family.name == "AF_INET" and not a.address.startswith("127."):
                        base = ".".join(a.address.split(".")[:3])
                        subnets.add(base)
                        my_ip = my_ip or a.address
                        network_info.append({
                            "interface": iface,
                            "ip": a.address,
                            "netmask": a.netmask,
                            "subnet": f"{base}.0/24",
                        })
        except ImportError:
            pass

        if custom_subnet:
            subnets = {custom_subnet.rstrip(".")}

        # --- Build scan targets ---
        targets: list[tuple[str, int, str, str]] = []

        # 1. Localhost
        for port, db_type, label in DB_PORTS:
            targets.append(("127.0.0.1", port, db_type, label))

        # 2. Network scan
        if custom_range:
            # Parse range like "1-254" or "10-50"
            parts = custom_range.split("-")
            start = int(parts[0]) if parts else 1
            end = int(parts[1]) if len(parts) > 1 else start
            host_range = range(start, min(end + 1, 255))
        elif full_scan:
            host_range = range(1, 255)
        else:
            # Quick scan: common hosts (gateway, servers, x0, x00)
            host_range = [1, 2, 3, 5, 10, 20, 50, 100, 150, 200, 250, 254]

        for base in subnets:
            for suffix in host_range:
                ip = f"{base}.{suffix}"
                if ip == my_ip:
                    continue  # skip self
                for port, db_type, label in DB_PORTS[:4]:  # top 4 DB types for network
                    targets.append((ip, port, db_type, f"{label} ({ip})"))

        # --- Scan for SQLite files ---
        import glob
        sqlite_files = []
        for pattern in [
            str(Path.home() / "*.db"),
            str(Path.home() / "*.sqlite"),
            str(Path.home() / "*.sqlite3"),
            "/tmp/*.db",
        ]:
            sqlite_files.extend(glob.glob(pattern, recursive=False)[:5])

        # --- Concurrent port scan ---
        sem = asyncio.Semaphore(100)  # limit concurrent connections

        async def check_port(host, port, db_type, label):
            async with sem:
                try:
                    loop = asyncio.get_event_loop()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5 if host != "127.0.0.1" else 1)
                    result = await loop.run_in_executor(
                        None, lambda: sock.connect_ex((host, port))
                    )
                    sock.close()
                    if result == 0:
                        return {
                            "host": host, "port": port, "type": db_type,
                            "label": label, "status": "open",
                        }
                except Exception:
                    pass
                return None

        tasks = [check_port(h, p, t, l) for h, p, t, l in targets]
        results = await asyncio.gather(*tasks)
        found = [r for r in results if r is not None]

        # Add SQLite files
        for f in sqlite_files[:10]:
            found.append({
                "host": "", "port": 0, "type": "sqlite",
                "label": f"SQLite ({Path(f).name})", "path": f, "status": "file",
            })

        return {
            "ok": True,
            "found": found,
            "scanned": len(targets),
            "network": network_info,
            "subnets": sorted(subnets),
            "my_ip": my_ip,
            "scan_mode": "full" if full_scan else "custom" if custom_range else "quick",
        }

    @app.post("/v1/databases/test")
    async def databases_test(body: dict) -> dict[str, Any]:
        """Test database connection without registering."""
        from ..tools.db_mgmt import _execute_query
        db_type = str(body.get("type", "")).strip().lower()
        if not db_type:
            return {"ok": False, "error": "type is required"}

        cfg = {
            "type": db_type,
            "host": str(body.get("host", "")).strip(),
            "port": int(body.get("port", 0) or 0),
            "name": str(body.get("database", "")).strip(),
            "user": str(body.get("user", "")).strip(),
            "password": str(body.get("password", "")).strip(),
            "path": str(body.get("path", "")).strip(),
        }
        import time
        start = time.time()
        try:
            if db_type == "sqlite":
                result = _execute_query(cfg, "SELECT sqlite_version();")
            elif db_type == "postgresql":
                result = _execute_query(cfg, "SELECT version();")
            elif db_type == "mysql":
                result = _execute_query(cfg, "SELECT version();")
            else:
                result = {"ok": False, "error": f"unsupported type: {db_type}"}
            latency = round((time.time() - start) * 1000)
            if result.get("ok"):
                version = ""
                rows = result.get("rows", [])
                if rows and isinstance(rows[0], dict):
                    version = str(list(rows[0].values())[0])
                elif result.get("output"):
                    version = result["output"][:100]
                return {"ok": True, "latency_ms": latency, "version": version}
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.delete("/v1/databases/{name}")
    def databases_remove(name: str) -> dict[str, Any]:
        from ..security.rate_limiter import get_limiter
        from ..tools.db_mgmt import _remove_database

        limiter = get_limiter("destructive", 10, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        return _remove_database(manager, name)

    @app.post("/v1/databases/{name}/query")
    def databases_query(name: str, body: dict) -> dict:
        from ..security.rate_limiter import get_limiter
        from ..tools.db_mgmt import _execute_query, _resolve_config

        limiter = get_limiter("query", 30, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        query = str(body.get("query", "")).strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        offset = int(body.get("offset", 0))
        limit = int(body.get("limit", 100))
        return _execute_query(cfg, query, offset=offset, limit=limit)

    @app.get("/v1/databases/{name}/tables")
    def databases_tables(name: str) -> dict:
        from ..tools.db_mgmt import _get_tables, _resolve_config

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        return _get_tables(cfg)

    @app.get("/v1/databases/{name}/tables/{table}/columns")
    def databases_table_columns(name: str, table: str) -> dict:
        from ..tools.db_mgmt import _get_columns, _resolve_config, _validate_table_name

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        err = _validate_table_name(table)
        if err:
            return {"ok": False, "error": err}
        return _get_columns(cfg, table)

    @app.get("/v1/databases/{name}/tables/{table}/indexes")
    def databases_table_indexes(name: str, table: str) -> dict:
        from ..tools.db_mgmt import _get_indexes, _resolve_config, _validate_table_name

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        err = _validate_table_name(table)
        if err:
            return {"ok": False, "error": err}
        return _get_indexes(cfg, table)

    @app.get("/v1/databases/{name}/tables/{table}/fkeys")
    def databases_table_fkeys(name: str, table: str) -> dict:
        from ..tools.db_mgmt import _get_foreign_keys, _resolve_config, _validate_table_name

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        err = _validate_table_name(table)
        if err:
            return {"ok": False, "error": err}
        return _get_foreign_keys(cfg, table)

    @app.get("/v1/databases/{name}/migrations")
    def databases_migrations(name: str) -> dict:
        from ..tools.db_mgmt import _list_migrations, _resolve_config

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        return _list_migrations(cfg)

    @app.get("/v1/databases/{name}/status")
    def databases_status(name: str) -> dict:
        from ..tools.db_mgmt import _get_db_status, _resolve_config

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        return _get_db_status(cfg)

    @app.get("/v1/databases/{name}/erd")
    def databases_erd(name: str) -> dict:
        from ..tools.db_mgmt import _generate_erd_mermaid, _resolve_config

        cfg = _resolve_config(manager, name)
        if not cfg:
            return {"ok": False, "error": f"database '{name}' not found"}
        return _generate_erd_mermaid(cfg)

    # -- Config export/import ---------------------------------------------------

    @app.post("/v1/config/export")
    def config_export(body: dict) -> dict:
        """Export all configuration (optionally excluding credentials)."""
        include_creds = bool((body or {}).get("include_credentials", False))
        config: dict[str, Any] = {"ssh_servers": [], "databases": [], "cloud_providers": []}
        # SSH
        from ..connectors.ssh import list_servers
        config["ssh_servers"] = list_servers(manager.secrets)
        # Databases
        from ..tools.db_mgmt import _list_databases
        config["databases"] = _list_databases(manager)
        # Cloud
        from ..connectors.cloud import list_providers
        config["cloud_providers"] = list_providers(manager.secrets)
        if not include_creds:
            for db in config["databases"]:
                db.pop("password", None)
        return {"ok": True, "config": config}

    @app.post("/v1/config/import")
    def config_import(body: dict) -> dict:
        """Import configuration from exported JSON."""
        config = (body or {}).get("config", {})
        imported: dict[str, int] = {"ssh": 0, "databases": 0, "cloud": 0}
        # SSH
        from ..connectors.ssh import add_server
        for s in config.get("ssh_servers", []):
            r = add_server(
                manager.secrets,
                server_id=s.get("server_id", ""),
                host=s.get("host", ""),
                port=s.get("port", 22),
                username=s.get("username", "deploy"),
            )
            if r.get("ok"):
                imported["ssh"] += 1
        # Databases
        from ..tools.db_mgmt import _add_database
        for d in config.get("databases", []):
            r = _add_database(
                manager,
                name=d.get("name", ""),
                db_type=d.get("type", ""),
                host=d.get("host", ""),
                port=d.get("port", 0),
                db_name=d.get("database", ""),
                user=d.get("user", ""),
                password=d.get("password", ""),
            )
            if r.get("ok"):
                imported["databases"] += 1
        return {"ok": True, "imported": imported}

    # -- Cloud provider management ----------------------------------------------

    @app.get("/v1/cloud/providers")
    def cloud_providers_list() -> dict[str, Any]:
        from ..connectors.cloud import list_providers

        return {"ok": True, "providers": list_providers(manager.secrets)}

    @app.post("/v1/cloud/providers")
    def cloud_providers_add(body: dict) -> dict[str, Any]:
        from ..connectors.cloud import add_provider

        if not isinstance(body, dict):
            return {"ok": False, "error": "invalid body"}
        return add_provider(
            manager.secrets,
            name=str(body.get("name", "")).strip(),
            provider=str(body.get("provider", "")).strip(),
            api_key=str(body.get("api_key", "")).strip(),
            api_secret=str(body.get("api_secret", "")).strip(),
            region=str(body.get("region", "")).strip(),
        )

    @app.delete("/v1/cloud/providers/{name}")
    def cloud_providers_remove(name: str) -> dict[str, Any]:
        from ..connectors.cloud import remove_provider

        return remove_provider(manager.secrets, name)

    @app.post("/v1/cloud/providers/{name}/test")
    async def cloud_providers_test(name: str) -> dict[str, Any]:
        from ..connectors.cloud import test_provider

        return await test_provider(manager.secrets, name)

    # -- Dev dashboard (GitHub + Gitea/Forgejo) --------------------------------

    def _get_scm_connector():
        """Get the configured SCM connector (GitHub or Gitea)."""
        from ..connectors.gitea import get_gitea_connector
        from ..connectors.github import get_github_connector
        # Gitea takes priority if configured (self-hosted)
        gt = get_gitea_connector(manager.secrets)
        if gt is not None:
            return gt, "gitea"
        gh = get_github_connector(manager.secrets)
        if gh is not None:
            return gh, "github"
        return None, None

    @app.get("/v1/dev/config")
    def dev_config() -> dict[str, Any]:
        """Check if SCM (GitHub/Gitea) is configured."""
        conn, provider = _get_scm_connector()
        if conn is None:
            return {"ok": True, "configured": False}
        return {"ok": True, "configured": True, "provider": provider,
                "owner": conn.owner, "repo": conn.repo,
                "base_url": getattr(conn, "base_url", "")}

    @app.post("/v1/dev/config")
    def dev_config_save(body: dict) -> dict[str, Any]:
        """Save SCM config. Set provider=gitea for Gitea/Forgejo instances."""
        provider = str(body.get("provider", "github")).strip().lower()
        if provider == "gitea":
            from ..connectors.gitea import save_gitea_config
            return save_gitea_config(
                manager.secrets,
                base_url=str(body.get("base_url", "")).strip(),
                token=str(body.get("token", "")).strip(),
                owner=str(body.get("owner", "")).strip(),
                repo=str(body.get("repo", "")).strip(),
            )
        else:
            from ..connectors.github import save_github_config
            return save_github_config(
                manager.secrets,
                token=str(body.get("token", "")).strip(),
                owner=str(body.get("owner", "")).strip(),
                repo=str(body.get("repo", "")).strip(),
            )

    @app.get("/v1/dev/repo")
    async def dev_repo() -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.get_repo()

    @app.get("/v1/dev/pulls")
    async def dev_pulls(state: str = "open") -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_pulls(state=state)

    @app.get("/v1/dev/actions/runs")
    async def dev_actions_runs() -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_runs()

    @app.get("/v1/dev/issues")
    async def dev_issues(state: str = "open") -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_issues(state=state)

    @app.get("/v1/dev/pulls/{number}")
    async def dev_pull_detail(number: int) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.get_pull(number)

    @app.get("/v1/dev/actions/runs/{run_id}/jobs")
    async def dev_run_jobs(run_id: int) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.get_run_logs(run_id)

    @app.post("/v1/dev/issues")
    async def dev_create_issue(body: dict) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        labels_raw = body.get("labels")
        labels = [l.strip() for l in labels_raw if l.strip()] if isinstance(labels_raw, list) else None
        return await conn.create_issue(
            title=str(body.get("title", "")).strip(),
            body=str(body.get("body", "")).strip(),
            labels=labels,
        )

    @app.get("/v1/dev/reviews")
    async def dev_reviews() -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_review_requests()

    @app.get("/v1/dev/releases")
    async def dev_releases() -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_releases()

    @app.post("/v1/dev/releases")
    async def dev_create_release(body: dict) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.create_release(
            tag=str(body.get("tag", "")).strip(),
            name=str(body.get("name", "")).strip(),
            body=str(body.get("body", "")).strip(),
            draft=bool(body.get("draft", False)),
        )

    @app.get("/v1/dev/commits")
    async def dev_commits(sha: str = "") -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        return await conn.list_commits(sha=sha)

    @app.post("/v1/dev/pulls/{number}/merge")
    async def dev_merge_pull(number: int, body: dict) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        method = str(body.get("method", "squash")).strip()
        if method not in ("squash", "merge", "rebase"):
            return {"ok": False, "error": "Invalid merge method"}
        return await conn.merge_pull(number, method=method)

    @app.post("/v1/dev/pulls/{number}/review")
    async def dev_pr_review(number: int) -> dict[str, Any]:
        conn, _ = _get_scm_connector()
        if conn is None:
            return {"ok": False, "error": "SCM not configured"}
        pr = await conn.get_pull(number)
        if not pr.get("ok"):
            return pr
        return {"ok": True, "pr": pr, "review_prompt": f"Review PR #{number}: {pr.get('title', '')}\n+{pr.get('additions', 0)} -{pr.get('deletions', 0)} in {pr.get('changed_files', 0)} files"}

    @app.post("/v1/dev/webhook")
    async def dev_webhook(request: Request) -> dict[str, Any]:
        """Receive GitHub webhook events."""
        body = await request.json()
        event_type = request.headers.get("X-GitHub-Event", "")
        if event_type in ("pull_request", "issues", "push", "workflow_run"):
            await manager.broadcast_event({"type": "github_event", "event": event_type, "action": body.get("action", "")})
        return {"ok": True, "event": event_type}

    # -- OpenWorker Cloud: sign-in + managed one-click connect ---------------
    # All optional: the app is fully functional signed out (manual token paste
    # stays available for every connector, before and after sign-in).

    @app.get("/v1/cloud/status")
    def cloud_status() -> dict[str, Any]:
        return {"signed_in": False, "account": "", "user_id": "", "telemetry_enabled": False}

    @app.post("/v1/cloud/telemetry")
    def cloud_telemetry(body: dict) -> dict[str, Any]:
        return {"ok": True, "telemetry_enabled": False}

    @app.post("/v1/cloud/login")
    def cloud_login() -> dict[str, Any]:
        return {"error": "Cloud not configured"}

    @app.post("/v1/cloud/logout")
    def cloud_logout() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/auth/callback")
    async def cloud_auth_callback(code: str = "", state: str = "", error: str = ""):
        from fastapi.responses import HTMLResponse

        return HTMLResponse(
            _browser_page(
                "Cloud not configured",
                "Cloud sign-in is not available.",
                ok=False,
                error="Cloud endpoints are disabled",
            ),
            status_code=400,
        )

    @app.post("/v1/connectors/{name}/connect-managed")
    async def connector_connect_managed(name: str, body: Optional[dict] = None) -> dict[str, Any]:
        return {"ok": False, "error": "Cloud not configured"}

    @app.post("/oauth/callback")
    async def managed_oauth_callback(request: Request) -> Any:
        from fastapi.responses import HTMLResponse

        from .. import cloud
        from ..connectors.setup import (
            managed_connect_connector,
            managed_connect_slack_install,
        )

        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
        connector = data.get("connector", "")
        if not cloud.consume_managed_state(data.get("app_state", "")):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error="unknown or expired connection attempt",
                ),
                status_code=400,
            )
        if data.get("error"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error=data["error"],
                ),
                status_code=400,
            )
        # Managed GitHub deliberately carries NO token fields — the loopback POST
        # is routing metadata only (installation tokens are minted on demand,
        # github-relay-spec §4) — so its branch precedes the access_token check.
        if connector == "github" and data.get("installation_id"):
            from ..connectors.github_installs import managed_connect_install

            result = managed_connect_install(manager.secrets, data)
            if result.get("ok"):
                await manager.refresh_gateway()  # hot-add, like a workspace
            if not result.get("ok"):
                return HTMLResponse(
                    _browser_page(
                        "Connection failed",
                        _CONNECT_FAILED_DETAIL,
                        ok=False,
                        error=result.get("error", ""),
                    ),
                    status_code=400,
                )
            return HTMLResponse(
                _browser_page(
                    "GitHub connected",
                    "You can close this tab and return to OpenWorker.",
                    connector="github",
                )
            )
        if not connector or not data.get("access_token"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error="missing fields",
                ),
                status_code=400,
            )
        # Managed Slack is multi-workspace + relay: store the per-team bot token
        # and flip to relay mode, rather than the single-token connector path.
        if connector == "slack" and data.get("team_id"):
            result = managed_connect_slack_install(manager.secrets, data)
            if result.get("ok"):
                # Hot-add: rebuild the gateway so the new workspace's token loads
                # (and the relay socket opens on a first-ever install) right away.
                await manager.refresh_gateway()
        elif connector == "gmail":
            # Multi-account: each sign-in lands in its own gmail:account:<email>
            # profile; the first becomes the default mailbox.
            from ..connectors import gmail_accounts

            result = gmail_accounts.managed_connect_account(
                manager.secrets, cloud.managed_profile_from_callback(data)
            )
        elif connector == "google_calendar":
            # Multi-account, same shape as gmail: google_calendar:account:<email>.
            from ..connectors import gcal_accounts

            result = gcal_accounts.managed_connect_account(
                manager.secrets, cloud.managed_profile_from_callback(data)
            )
        elif connector == "hubspot" and data.get("hub_id"):
            # Multi-portal: keyed by hub_id (broker sends it like Slack's team_id).
            from ..connectors import hubspot_portals

            profile = cloud.managed_profile_from_callback(data)
            profile["hub_id"] = data.get("hub_id", "")
            if data.get("sandbox"):
                profile["sandbox"] = True
            result = hubspot_portals.managed_connect_portal(manager.secrets, profile)
        else:
            result = managed_connect_connector(
                manager.secrets, connector, cloud.managed_profile_from_callback(data)
            )
        if not result.get("ok"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error=result.get("error", ""),
                ),
                status_code=400,
            )
        return HTMLResponse(
            _browser_page(
                f"{_connector_title(connector)} connected",
                "You can close this tab and return to OpenWorker.",
                connector=connector,
            )
        )

    @app.patch("/v1/connectors/{name}/tools")
    def connector_tools_patch(name: str, body: dict) -> dict[str, Any]:
        enabled = (body or {}).get("enabled")
        if not isinstance(enabled, dict):
            return {"ok": False, "error": "enabled map required"}
        return manager.update_connector_tools(name, enabled)

    @app.post("/v1/connectors/{name}/allow")
    def connector_allow(name: str, body: dict) -> dict[str, Any]:
        # `team_id` scopes the edit to one workspace (managed relay); absent → flat list.
        # `name` (optional) seeds the people directory so a directory-picked user's
        # chip shows their display name before they've ever sent a message.
        return manager.allow_user(
            name,
            str(body.get("user_id", "")),
            str(body.get("team_id", "")) or None,
            display_name=str(body.get("name", "")),
        )

    @app.get("/v1/connectors/slack/workspaces/{team_id}/directory")
    async def slack_directory(team_id: str, q: str = "", limit: int = 25) -> dict[str, Any]:
        """Workspace member roster for the people picker (team_id "default" =
        the manual Socket-Mode workspace). Cached locally; never leaves this machine."""
        from ..connectors import slack_directory as roster

        return await asyncio.to_thread(
            lambda: roster.list_members(manager.secrets, team_id, q, limit)
        )

    @app.get("/v1/connectors/slack/workspaces/{team_id}/channels")
    async def slack_channels(team_id: str, q: str = "", limit: int = 25) -> dict[str, Any]:
        """Channel roster for the channel typeahead: all public channels, private
        ones only where the bot is a member (Slack API constraint)."""
        from ..connectors import slack_directory as roster

        return await asyncio.to_thread(
            lambda: roster.list_channels(manager.secrets, team_id, q, limit)
        )

    @app.post("/v1/connectors/{name}/disallow")
    def connector_disallow(name: str, body: dict) -> dict[str, Any]:
        return manager.disallow_user(
            name, str(body.get("user_id", "")), str(body.get("team_id", "")) or None
        )

    @app.post("/v1/connectors/slack/approval-owners/add")
    def slack_approval_owner_add(body: dict) -> dict[str, Any]:
        return manager.set_slack_approval_owner(
            str(body.get("user_id", "")),
            add=True,
            display_name=str(body.get("name", "")),
        )

    @app.post("/v1/connectors/slack/approval-owners/remove")
    def slack_approval_owner_remove(body: dict) -> dict[str, Any]:
        return manager.set_slack_approval_owner(str(body.get("user_id", "")), add=False)

    # -- audit / browser observability ------------------------------------------
    @app.get("/v1/audit")
    def audit_list(
        limit: int = 100,
        session_id: str | None = None,
        connector: str | None = None,
        tool: str | None = None,
    ) -> dict[str, Any]:
        return {
            "events": manager.list_audit(
                limit=limit, session_id=session_id, connector=connector, tool=tool
            )
        }

    @app.get("/v1/browser/state")
    def browser_state_get() -> dict[str, Any]:
        return manager.browser_state()

    @app.post("/v1/browser/screenshot")
    def browser_screenshot_post() -> dict[str, Any]:
        return manager.browser_screenshot()

    @app.post("/v1/browser/close")
    def browser_close_post() -> dict[str, Any]:
        return manager.browser_close()

    # -- web search -------------------------------------------------------------
    @app.get("/v1/web-search")
    def web_search_get() -> dict[str, Any]:
        return manager.get_web_search()

    @app.post("/v1/web-search")
    def web_search_set(body: dict) -> dict[str, Any]:
        provider = (body or {}).get("provider", "")
        if not provider:
            return {"ok": False, "error": "provider required"}
        return manager.set_web_search(provider, (body or {}).get("api_key"))

    # -- model providers (OpenAI, Ollama, …) ------------------------------------
    @app.get("/v1/providers")
    def providers_get() -> list[dict[str, Any]]:
        return manager.get_providers()

    @app.post("/v1/providers")
    def providers_set(body: dict) -> dict[str, Any]:
        name = (body or {}).get("name", "")
        if not name:
            return {"ok": False, "error": "name required"}
        return manager.set_provider(name, (body or {}).get("fields"))

    @app.delete("/v1/providers/{name}")
    def providers_remove(name: str) -> dict[str, Any]:
        return manager.remove_provider(name)

    @app.post("/v1/providers/verify")
    async def providers_verify(body: dict) -> dict[str, Any]:
        # Live read-only credential check (sync httpx) — run off the event loop.
        name = (body or {}).get("name", "") or "openai"
        return await asyncio.to_thread(manager.verify_provider, name, (body or {}).get("fields"))

    # -- settings (model API key) -----------------------------------------------
    @app.get("/v1/settings")
    def settings_get() -> dict[str, Any]:
        return manager.get_settings()

    @app.post("/v1/settings/model-key")
    def settings_set_model_key(body: dict) -> dict[str, Any]:
        return manager.set_model_key((body or {}).get("api_key", ""))

    @app.post("/v1/settings/default-model")
    def settings_set_default_model(body: dict) -> dict[str, Any]:
        return manager.set_default_model((body or {}).get("model", ""))

    @app.post("/v1/settings/models/add")
    def settings_models_add(body: dict) -> dict[str, Any]:
        return manager.add_model((body or {}).get("model", ""))

    @app.post("/v1/settings/models/remove")
    def settings_models_remove(body: dict) -> dict[str, Any]:
        return manager.remove_model((body or {}).get("model", ""))

    @app.post("/v1/settings/onboarded")
    def settings_set_onboarded(body: dict) -> dict[str, Any]:
        return manager.set_onboarded(bool((body or {}).get("value", True)))

    @app.post("/v1/settings/experimental-connectors")
    def settings_set_experimental(body: dict) -> dict[str, Any]:
        return manager.set_experimental_connectors(bool((body or {}).get("value")))

    @app.post("/v1/settings/surfaces")
    def settings_set_surfaces(body: dict) -> dict[str, Any]:
        b = body or {}
        return manager.set_surfaces(chat=b.get("chat"), code=b.get("code"))

    @app.post("/v1/settings/scratch-base")
    def settings_set_scratch_base(body: dict) -> dict[str, Any]:
        return manager.set_scratch_base(str((body or {}).get("path", "")))

    @app.post("/v1/settings/nav-layout")
    def settings_set_nav_layout(body: dict) -> dict[str, Any]:
        return manager.set_nav_layout(str((body or {}).get("nav_layout", "")))

    @app.post("/v1/settings/sessions-peek")
    def settings_set_sessions_peek(body: dict) -> dict[str, Any]:
        # Sidebar: sessions shown per group before "Show more" (owner ask, 2026-07-03).
        return manager.set_sessions_peek((body or {}).get("sessions_peek", 5))

    @app.post("/v1/settings/context-bar")
    def settings_set_context_bar(body: dict) -> dict[str, Any]:
        # Composer: show the context-window fill bar, or just the popover (owner ask).
        return manager.set_context_bar((body or {}).get("context_bar", True))

    @app.post("/v1/settings/pdf")
    def settings_set_pdf(body: dict) -> dict[str, Any]:
        # Token savings (owner ask, 2026-07-17): fallback mode for models without native
        # PDF support + attach-time page/size thresholds.
        b = body or {}
        return manager.set_pdf_settings(
            fallback=b.get("pdf_fallback"),
            max_pages=b.get("pdf_max_pages"),
            max_mb=b.get("pdf_max_mb"),
        )

    @app.post("/v1/settings/compaction")
    def settings_set_compaction(body: dict) -> dict[str, Any]:
        # Auto-compaction overrides (OPE-27): threshold % of the context window, the
        # absolute token cap, and the summarizer-model pin ("" → session's own model).
        b = body or {}
        return manager.set_compaction_settings(
            threshold_pct=b.get("compaction_threshold_pct"),
            cap_tokens=b.get("compaction_cap_tokens"),
            model=b.get("compaction_model"),
        )

    @app.post("/v1/attachments/inspect-pdf")
    def attachments_inspect_pdf(body: dict) -> dict[str, Any]:
        # Attach-time page/size probe for the composer's threshold check. Local only.
        from ..pdf_support import inspect

        return inspect(str((body or {}).get("data_url", "")))

    @app.post("/v1/attachments/render-pdf")
    def attachments_render_pdf(body: dict) -> dict[str, Any]:
        """Server-side PDF → PNG page images. Replaces the pdfjs-dist client-side
        renderer, eliminating the 1.3MB worker from the frontend bundle."""
        from ..pdf_support import rasterize

        data_url = str((body or {}).get("data_url", ""))
        max_pages = int((body or {}).get("max_pages", 20))
        if not data_url:
            return {"ok": False, "error": "missing data_url"}
        pages = rasterize(data_url, max_pages=max_pages)
        if pages is None:
            return {"ok": False, "error": "could not render PDF"}
        return {"ok": True, "pages": pages}

    # -- direct-message routing -------------------------------------------------
    @app.get("/v1/messaging/dm-route")
    def dm_route_get() -> dict[str, Any]:
        return {"dm_session": manager.dm_session()}

    @app.post("/v1/messaging/dm-route")
    def dm_route_set(body: dict) -> dict[str, Any]:
        # A falsy session_id clears the designation (DMs then park as unrouted).
        return manager.set_dm_session((body or {}).get("session_id", ""))

    if os.environ.get("COWORKER_DEBUG_INJECT") == "1":
        # Dev-only (env-gated, localhost): feed a message through the real inbound path so the
        # messaging stack can be exercised without a live bot connection. Not registered otherwise.
        @app.post("/v1/_debug/inject_inbound")
        async def debug_inject_inbound(body: dict) -> dict[str, Any]:
            from ..connectors.base import MessageEvent, SessionSource

            event = MessageEvent(
                text=str((body or {}).get("text", "")),
                source=SessionSource(
                    platform=str(body.get("platform", "slack")),
                    chat_id=str(body.get("chat_id", "C0BD7KZ1AH5")),
                    user_id=str(body.get("user_id", "U07JK68S4BH")),
                    user_name=str(body.get("user_name", "tester")),
                    chat_type=str(body.get("chat_type", "channel")),
                    chat_name=str(body.get("chat_name", "")) or None,
                    thread_id=str(body.get("thread_ts", "")) or None,
                    team_id=str(body.get("team_id", "")) or None,
                ),
                message_id=str(body.get("ts", "")) or None,
                # §31 mention router: the flag is normally computed from the raw Slack text
                # at mapping time; the injector sets it directly.
                mentions_me=bool(body.get("mentions_me")),
            )
            await manager._dispatch_inbound(event)
            return {"ok": True}

    # -- automations (scheduled tasks) ------------------------------------------
    @app.get("/v1/automations")
    def automations_list() -> dict[str, Any]:
        return manager.list_automations()

    @app.post("/v1/automations")
    def automations_create(body: dict) -> dict[str, Any]:
        return manager.create_automation(body or {})

    @app.get("/v1/automations/{task_id}")
    def automation_get(task_id: str) -> dict[str, Any]:
        return manager.get_automation(task_id)

    @app.patch("/v1/automations/{task_id}")
    def automation_update(task_id: str, body: dict) -> dict[str, Any]:
        return manager.update_automation(task_id, body or {})

    @app.delete("/v1/automations/{task_id}")
    def automation_delete(task_id: str) -> dict[str, Any]:
        return manager.delete_automation(task_id)

    @app.post("/v1/automations/{task_id}/seen")
    def automations_seen(task_id: str) -> dict[str, Any]:
        return manager.mark_automation_seen(task_id)

    @app.post("/v1/automations/{task_id}/run")
    def automation_run(task_id: str) -> dict[str, Any]:
        # Prepare a live manual run; the GUI opens the returned session and drives it.
        return manager.prepare_manual_run(task_id)

    @app.post("/v1/automations/{task_id}/runs/{run_id}/finalize")
    def automation_run_finalize(task_id: str, run_id: str) -> dict[str, Any]:
        return manager.finalize_manual_run(task_id, run_id)

    @app.websocket("/ws/session/{session_id}")
    async def ws_session(ws: WebSocket, session_id: str) -> None:
        if not _websocket_authenticated(ws):
            await ws.close(code=1008)
            return
        # CORS never gates WebSockets, so a cross-site page could otherwise open this socket
        # and drive the session into tool calls. Reject a disallowed browser Origin before
        # accepting the handshake (1008 = policy violation).
        if not _origin_allowed(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="werubworker" if api_token else None)
        agent = ws.query_params.get("agent") or "code"

        # All four interactive prompts (approval / question / directory / plan) are parked as Inbox
        # items and awaited via inbox.wait — so they survive a dropped socket (redelivered on
        # reconnect) and can be resolved from any surface. `visibility` decides where they SHOW:
        # Unattended → the cross-session Inbox; attended → inline in this session only. The agent
        # stays blocked until the item is resolved (live WS response, REST, or a bound channel).
        def _visibility() -> str:
            return VIS_INBOX if manager.unattended.is_unattended(session_id) else VIS_INLINE

        async def _mirror(item) -> None:
            # Unattended items mirror to a bound channel as buttons (see mirror_inbox_item).
            await manager.mirror_inbox_item(item)

        def _route() -> str:
            return manager.inbox_routing.route_for(session_id, agent)

        async def approver(_request) -> ApprovalOutcome:
            # The engine has already emitted PERMISSION_REQUIRED (the live inline card). Park the
            # item so the answer can also come from the Inbox / a reconnect / after a restart.
            item = manager.inbox.add_approval(
                session_id,
                f"Run `{_request.tool_name}`?",
                body="\n".join(
                    p
                    for p in (
                        (getattr(_request, "reason", "") or "").strip(),
                        args_preview(getattr(_request, "arguments", None)),
                    )
                    if p
                ),
                inbox=_route(),
                visibility=_visibility(),
                # Automation-run context (manual "Run now" rides this socket): lets the
                # card offer the task-persistent "Allow every time" (§25). {} elsewhere.
                data=manager.approval_prompt_data(session_id, _request),
                tool_call_id=getattr(_request, "tool_call_id", None),
            )
            if item.state == "pending":  # freshly raised (not a durable-resume re-raise)
                manager.persist_session(session_id)  # the pending tool call is now on disk
                if item.visibility == VIS_INBOX:
                    await _mirror(item)
            resolution = await manager.inbox.wait(item.id)
            # Accept every vocabulary: the live card sends once/always_tool/always_command/
            # always_task/deny; the Inbox / a channel send allow/always/deny.
            return manager.approval_outcome(resolution, _request, session_id)

        async def question_asker(args: dict, tool_call_id=None) -> dict:
            # ask_user (engine does NOT emit the event — we do, only when attended).
            item = manager.inbox.add_question(
                session_id,
                str(args.get("question", "")),
                inbox=_route(),
                visibility=_visibility(),
                options=list(args.get("options") or []),
                allow_text=bool(args.get("allow_text", True)),
                multi=bool(args.get("multi", False)),
                tool_call_id=tool_call_id,
            )
            if item.state == "pending":
                manager.persist_session(session_id)
                if item.visibility == VIS_INBOX:
                    await _mirror(item)
                else:
                    await ws.send_json(
                        {
                            "type": "question_requested",
                            "data": {
                                "question": item.title,
                                "options": item.options,
                                "allow_text": item.allow_text,
                                "multi": item.multi,
                                "header": str(args.get("header", "")),
                            },
                        }
                    )
            return {"answer": await manager.inbox.wait(item.id)}

        async def directory_requester(args: dict, tool_call_id=None) -> dict:
            # The engine has already emitted DIRECTORY_REQUESTED. Park, await, then apply the grant.
            item = manager.inbox.add_directory(
                session_id,
                "Grant access to a folder?",
                body=str(args.get("reason", "")),
                inbox=_route(),
                visibility=_visibility(),
                data={
                    "path": str(args.get("path", "")),
                    "writable": bool(args.get("writable", False)),
                },
                tool_call_id=tool_call_id,
            )
            if item.state == "pending":
                manager.persist_session(session_id)
                if item.visibility == VIS_INBOX:
                    await _mirror(item)
            resp = _parse_json(await manager.inbox.wait(item.id))  # {granted, path, writable}
            if not resp.get("granted"):
                return {"granted": False, "reason": "the user declined the request"}
            path = (resp.get("path") or args.get("path") or "").strip()
            if not path:
                return {"granted": False, "error": "no directory was provided"}
            writable = bool(resp.get("writable", args.get("writable", False)))
            res = manager.add_root(session_id, path, writable)
            if not res.get("ok"):
                return {
                    "granted": False,
                    "error": res.get("error", "could not grant access"),
                }
            primary = next(
                (
                    r
                    for r in res.get("roots", [])
                    if r.get("path")
                    and Path(r["path"]).expanduser().resolve() == Path(path).expanduser().resolve()
                ),
                None,
            )
            return {
                "granted": True,
                "path": (primary or {}).get("path", path),
                "writable": writable,
            }

        async def plan_approver(_args: dict, tool_call_id=None) -> dict:
            # The engine has already emitted PLAN_PROPOSED. Park, await the verdict.
            item = manager.inbox.add_plan(
                session_id,
                "Approve the plan?",
                body=str(_args.get("plan", "")),
                inbox=_route(),
                visibility=_visibility(),
                tool_call_id=tool_call_id,
            )
            if item.state == "pending":
                manager.persist_session(session_id)
                if item.visibility == VIS_INBOX:
                    await _mirror(item)
            resp = _parse_json(await manager.inbox.wait(item.id))  # {approved, mode, feedback}
            if not resp.get("approved"):
                return {
                    "approved": False,
                    "feedback": resp.get("feedback") or "the user rejected the plan",
                }
            return {"approved": True, "mode": resp.get("mode") or "interactive"}

        async def _apply_model(model: Optional[str]) -> None:
            # Mid-session rebind is allowed (roadmap item 3, supersedes the 2026-07-04
            # lock): history is canonical and providers convert per call. A real switch
            # appends a persisted notice; broadcast it so live views render the marker
            # and update their header. Never rebind mid-turn — the running loop reads
            # `engine.model` per iteration and a mixed turn is exactly the breakage the
            # old lock existed to prevent.
            if not model or manager.is_running(session_id):
                return
            notice = engine.switch_model(model)
            if notice is None:  # same model, or first bind on a fresh session
                return
            manager.persist_session(session_id)
            await manager.broadcast_session(
                session_id,
                {"type": "model_changed", "data": {"model": model, "text": notice}},
            )

        def _resolve_pending(resolution: str) -> None:
            # Live WS responses resolve THE session's single pending prompt (one at a time, since the
            # agent blocks). Reconnect / Inbox resolve by id via REST instead.
            pend = manager.inbox.pending(session_id)
            if pend:
                manager.inbox.resolve(pend[0].id, resolution)

        workspace = ws.query_params.get("workspace")
        mcp_tools = await manager.prepare_mcp_tools(session_id, workspace=workspace, agent=agent)
        engine = manager.get_engine(
            session_id,
            workspace=workspace,
            agent=agent,
            approver=approver,
            extra_tools=mcp_tools,
            directory_requester=directory_requester,
            plan_approver=plan_approver,
            question_asker=question_asker,
        )
        if engine is None:
            await ws.send_json(
                {
                    "type": "error",
                    "data": {"error": "no valid workspace — choose a project folder first"},
                }
            )
            await ws.close()
            return
        # Auto-compaction failure prompt (OPE-27): only an ATTENDED session may be asked
        # Retry/Trim — unattended runs auto-trim (the policy in engine._compact_now).
        engine.is_attended = lambda: _visibility() == VIS_INLINE
        await ws.send_json(
            {
                "type": "ready",
                "data": {
                    "session_id": session_id,
                    "agent": getattr(engine, "agent_name", "code"),
                    "model": engine.model,
                    "mode": engine.permissions.mode.value,
                    "workspace": (
                        str(getattr(engine, "executor").cwd)
                        if getattr(engine, "executor", None)
                        else None
                    ),
                    "command_trust": manager.workspace_command_trust(
                        str(getattr(engine, "audit_context", {}).get("workspace", ""))
                    ),
                },
            }
        )

        # Checkpoint events: persist mid-turn so a crash/quit can't eat the conversation.
        # turn_start = the user message just landed (a brand-new session gets its row here,
        # not at connect — empty never-used sessions shouldn't appear in Recents);
        # permission_required/directory_requested = parked indefinitely on the user;
        # iteration_end = a model response + its tool results completed.
        _CHECKPOINTS = {
            "turn_start",
            "permission_required",
            "directory_requested",
            "plan_proposed",
            "iteration_end",
        }

        async def run_turn(content, *, retry: bool = False, display=None) -> None:
            # The receive loop atomically claims this session before scheduling the task.
            # Keeping the claim outside prevents two back-to-back frames from both starting.
            try:
                events = engine.retry() if retry else engine.run(content, display=display)
                async for event in events:
                    # Broadcast to every socket viewing this session (this socket included — it's a
                    # registered client), so a second view of the same session stays in sync too.
                    await manager.broadcast_session(
                        session_id, {"type": event.type.value, "data": event.data}
                    )
                    if event.type.value in _CHECKPOINTS:
                        manager.save(session_id, engine)
            finally:
                manager.mark_idle(session_id)
                manager.save(session_id, engine)
                await manager.broadcast_session(session_id, {"type": "turn_done", "data": {}})

        # This socket is now a live view of the session; background turns (channel delivery,
        # self-wake, durable resume) broadcast here too, not just locally driven run_turns.
        manager.register_session_client(session_id, ws.send_json)
        inbound_times: deque[float] = deque()

        async def reject_input(reason: str) -> None:
            # Input validation failures are not provider failures and must not offer "Retry"
            # or flush an in-progress assistant stream in the GUI.
            await ws.send_json({"type": "input_rejected", "data": {"error": reason}})

        async def claim_turn(*, retry: bool = False, content=None, display=None) -> None:
            if not manager.try_mark_running(session_id):
                await reject_input(
                    "This session is already running a turn. Wait for it to finish or stop it."
                )
                return
            asyncio.create_task(run_turn(content, retry=retry, display=display))

        try:
            while True:
                try:
                    message = await ws.receive_json()
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await reject_input("Invalid WebSocket message: expected JSON.")
                    continue

                now = asyncio.get_running_loop().time()
                while inbound_times and now - inbound_times[0] > _WS_RATE_LIMIT_WINDOW_SECONDS:
                    inbound_times.popleft()
                if len(inbound_times) >= _WS_RATE_LIMIT_COUNT:
                    await reject_input("Too many WebSocket messages; reconnect and try again.")
                    await ws.close(code=1008)
                    return
                inbound_times.append(now)

                if not isinstance(message, dict):
                    await reject_input("Invalid WebSocket message: expected an object.")
                    continue
                kind = message.get("type")
                if not isinstance(kind, str):
                    await reject_input("Invalid WebSocket message: missing string type.")
                    continue
                if kind == "approval":
                    _resolve_pending(message.get("decision", "deny"))
                elif kind == "directory_response":
                    _resolve_pending(
                        json.dumps(
                            {
                                "granted": bool(message.get("granted")),
                                "path": message.get("path", ""),
                                "writable": bool(message.get("writable", False)),
                            }
                        )
                    )
                elif kind == "plan_response":
                    _resolve_pending(
                        json.dumps(
                            {
                                "approved": bool(message.get("approved")),
                                "mode": message.get("mode", "interactive"),
                                "feedback": message.get("feedback", ""),
                            }
                        )
                    )
                elif kind == "question_response":
                    _resolve_pending(str(message.get("answer", "")))
                elif kind == "interrupt":
                    engine.request_interrupt()
                elif kind == "retry":
                    # Re-run after a provider error (engine guards on the error-notice
                    # tail, so a stray frame is a no-op that still ends with turn_done).
                    await claim_turn(retry=True)
                elif kind == "set_mode":
                    try:
                        engine.permissions.mode = Mode(message.get("mode"))
                    except (TypeError, ValueError):
                        pass
                elif kind == "set_model":
                    model = message.get("model")
                    if model is not None and not isinstance(model, str):
                        await reject_input("Invalid model: expected a string.")
                    else:
                        await _apply_model(model)
                elif kind == "user_message":
                    raw_text = message.get("text")
                    if raw_text is None:
                        raw_text = ""
                    if not isinstance(raw_text, str):
                        await reject_input("Invalid message text: expected a string.")
                        continue
                    text = raw_text.strip()
                    raw_attachments = message.get("attachments")
                    attachments = [] if raw_attachments is None else raw_attachments
                    # Reject an oversized frame instead of buffering it into a turn. Send a
                    # visible error so the surface can tell the user, and drop the message.
                    if not isinstance(attachments, list):
                        await reject_input("Invalid attachments: expected a list.")
                        continue
                    reject = None
                    if len(text) > _MAX_MESSAGE_TEXT_CHARS:
                        reject = (
                            f"Message too long ({len(text)} chars; "
                            f"limit {_MAX_MESSAGE_TEXT_CHARS})."
                        )
                    elif len(attachments) > _MAX_ATTACHMENTS:
                        reject = (
                            f"Too many attachments ({len(attachments)}; limit {_MAX_ATTACHMENTS})."
                        )
                    elif any(not isinstance(a, dict) for a in attachments):
                        reject = "Invalid attachment: expected an object."
                    elif _json_value_size(attachments) > _MAX_ATTACHMENTS_BYTES:
                        reject = "Attachments too large (limit 15 MB per message)."
                    else:
                        for attachment in attachments:
                            attachment_kind = attachment.get("kind")
                            name = attachment.get("name")
                            mime = attachment.get("mime")
                            if attachment_kind not in {"image", "pdf", "text"}:
                                reject = "Invalid attachment kind."
                            elif name is not None and (
                                not isinstance(name, str) or len(name) > 1024
                            ):
                                reject = "Invalid attachment name."
                            elif mime is not None and (
                                not isinstance(mime, str) or len(mime) > 255
                            ):
                                reject = "Invalid attachment MIME type."
                            elif attachment_kind == "image":
                                data = attachment.get("data_url")
                                if (
                                    not isinstance(data, str)
                                    or not data.startswith("data:image/")
                                    or ";base64," not in data
                                    or len(data) > MAX_IMAGE_CHARS
                                ):
                                    reject = "Invalid or oversized image attachment."
                            elif attachment_kind == "pdf":
                                data = attachment.get("data_url")
                                if (
                                    not isinstance(data, str)
                                    or not data.startswith("data:application/pdf;base64,")
                                    or len(data) > MAX_PDF_CHARS
                                ):
                                    reject = "Invalid or oversized PDF attachment."
                            else:
                                body = attachment.get("text")
                                if not isinstance(body, str) or len(body) > MAX_TEXT_CHARS:
                                    reject = "Invalid or oversized text attachment."
                            if reject is not None:
                                break
                    if reject is not None:
                        await reject_input(reject)
                        continue
                    # The composer sends its visible model with every message — the FIRST
                    # one binds the session (race-proof across reconnects; see api.ts
                    # Session.userMessage), later ones may switch it (notice persisted).
                    model = message.get("model")
                    if model is not None and not isinstance(model, str):
                        await reject_input("Invalid model: expected a string.")
                        continue
                    # Force-run (SKILLS-SPEC §4.1 #3): the composer's `/skill` pick rides as a
                    # separate field. Validated against the session's effective menu — a muted
                    # or unknown skill is a visible error, never a silent no-op (§4.6 #15).
                    # The model-facing framing goes into `content`; the transcript shows the
                    # user's literal "/name …" line via the `_display` sidecar (one bubble).
                    skill = message.get("skill")
                    display = None
                    if skill is not None:
                        if not isinstance(skill, str) or not skill.strip():
                            await reject_input("Invalid skill: expected a name.")
                            continue
                        skill = skill.strip()
                        menu = manager.effective_skill_names(session_id, workspace)
                        if skill not in menu:
                            await reject_input(f"Skill '{skill}' is not available in this session.")
                            continue
                        display = f"/{skill}" + (f" {text}" if text else "")
                        text = (
                            f'Use the skill "{skill}" for this request: first call '
                            f'load_skill("{skill}") and follow its instructions.'
                            + (f"\n\n{text}" if text else "")
                        )
                    await _apply_model(model)
                    if text or attachments:
                        content = build_user_content(text, attachments)
                        await claim_turn(content=content, display=display)
                else:
                    await reject_input(f"Unknown WebSocket message type: {kind}.")
        except WebSocketDisconnect:
            pass
        finally:
            manager.unregister_session_client(session_id, ws.send_json)

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        """App-wide event stream (session-independent): the GUI keeps one open for
        pushes like automation_run_started (the UX-026 toast). Read-only — inbound
        frames are ignored; the receive loop just detects disconnect."""
        if not _websocket_authenticated(ws):
            await ws.close(code=1008)
            return
        if not _origin_allowed(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="werubworker" if api_token else None)
        manager.register_event_client(ws.send_json)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            manager.unregister_event_client(ws.send_json)

    @app.websocket("/ws/metrics")
    async def ws_metrics(ws: WebSocket) -> None:
        """Real-time metric stream: pushes collected metrics to subscribers."""
        if not _websocket_authenticated(ws):
            await ws.close(code=1008)
            return
        if not _origin_allowed(ws.headers.get("origin")):
            await ws.close(code=1008)
            return
        await ws.accept(subprotocol="werubworker" if api_token else None)
        manager.register_metrics_client(ws.send_json)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            manager.unregister_metrics_client(ws.send_json)

    # ------------------------------------------------------------------
    # Wiki & Credentials endpoints
    # ------------------------------------------------------------------

    @app.get("/v1/wiki")
    def wiki_list(category: str = "", query: str = "", tags: str = "") -> dict[str, Any]:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return {
            "pages": manager.wiki_store.list_pages(category=category, query=query, tags=tag_list)
        }

    @app.get("/v1/wiki/categories")
    def wiki_categories() -> dict[str, Any]:
        return {"categories": manager.wiki_store.categories()}

    @app.get("/v1/wiki/alerts")
    def wiki_alerts() -> dict[str, Any]:
        return {"alerts": manager.wiki_store.list_alerts()}

    @app.post("/v1/wiki/alerts/{alert_id}/ack")
    def wiki_ack_alert(alert_id: int) -> dict[str, Any]:
        return manager.wiki_store.ack_alert(alert_id)

    @app.get("/v1/wiki/search")
    def wiki_search_fts(q: str = "") -> dict[str, Any]:
        if not q.strip():
            return {"ok": True, "results": []}
        results = manager.wiki_store.search_fts(q.strip())
        return {"ok": True, "results": results}

    # -- Wiki sub-resources (MUST be before /v1/wiki/{page_id} to avoid route capture) --

    @app.get("/v1/wiki/prompts")
    def wiki_prompts_list_r() -> dict:
        pages = manager.wiki_store.list_pages(category="prompt")
        return {"ok": True, "prompts": pages}

    @app.get("/v1/wiki/benchmarks")
    def wiki_benchmarks_list_r(page_id: str = "", model_id: str = "") -> dict:
        results = manager.wiki_store.get_benchmarks(page_id, model_id)
        return {"ok": True, "benchmarks": results}

    @app.get("/v1/wiki/runbooks")
    def wiki_runbooks_list_r() -> dict[str, Any]:
        pages = manager.wiki_store.list_pages(category="runbook")
        return {"ok": True, "runbooks": pages}

    @app.get("/v1/wiki/templates")
    def wiki_templates_list_r() -> dict[str, Any]:
        from ..wiki.store import WIKI_TEMPLATES
        return {"ok": True, "templates": {k: {"name": v["name"], "content": v["content"]} for k, v in WIKI_TEMPLATES.items()}}

    # -- Wiki page CRUD (catch-all {page_id}) --

    @app.get("/v1/wiki/{page_id}")
    def wiki_get(page_id: str) -> dict[str, Any]:
        page = manager.wiki_store.get_page(page_id)
        if page is None:
            return JSONResponse({"error": f"page '{page_id}' not found"}, status_code=404)
        return {"page": page}

    def _wiki_store_credentials(page_id: str, credentials: list, linked_service: str = ""):
        """Store credential values in the vault and sync to secrets.json."""
        from ..wiki.sync import WikiSync

        for cred in credentials or []:
            key = cred.get("key", "")
            value = cred.get("value", "")
            if key and value:
                vault_key = f"{page_id}:{key}"
                manager.vault.store(
                    vault_key,
                    value,
                    expires=cred.get("expires", ""),
                    rotate_days=int(cred.get("rotate_days", 0) or 0),
                    linked_services=[linked_service] if linked_service else [],
                )
        # Sync to secrets.json if linked_service is set
        if linked_service:
            sync = WikiSync(manager.wiki_store, manager.vault, manager.secrets)
            sync.sync_page_to_secrets(page_id)

    @app.post("/v1/wiki")
    def wiki_create(body: dict) -> dict[str, Any]:
        body = body or {}
        page_id = str(body.get("page_id", body.get("id", "")))
        if not page_id:
            return JSONResponse({"error": "page_id is required"}, status_code=400)
        credentials = body.get("credentials") or []
        linked_service = str(body.get("linked_service", ""))
        # Strip values from credentials before storing in wiki DB (values go to vault)
        creds_meta = [{k: v for k, v in c.items() if k != "value"} for c in credentials]
        result = manager.wiki_store.create_page(
            page_id=page_id,
            name=str(body.get("name", page_id)),
            category=str(body.get("category", "")),
            content=str(body.get("content", "")),
            credentials=creds_meta,
            linked_service=linked_service,
            tags=body.get("tags"),
            updated_by=str(body.get("updated_by", "api")),
            structured_data=body.get("structured_data"),
        )
        # Store values in vault + sync to secrets.json
        _wiki_store_credentials(page_id, credentials, linked_service)
        return result

    @app.put("/v1/wiki/{page_id}")
    def wiki_update(page_id: str, body: dict) -> dict[str, Any]:
        body = body or {}
        credentials = body.get("credentials") or []
        linked_service = body.get("linked_service")
        # Strip values before DB storage
        creds_meta = (
            [{k: v for k, v in c.items() if k != "value"} for c in credentials]
            if credentials
            else None
        )
        result = manager.wiki_store.update_page(
            page_id=page_id,
            content=body.get("content"),
            credentials=creds_meta,
            name=body.get("name"),
            category=body.get("category"),
            tags=body.get("tags"),
            linked_service=linked_service,
            updated_by=str(body.get("updated_by", "api")),
            change_note=str(body.get("change_note", "")),
        )
        # Update vault + sync
        if credentials:
            page = manager.wiki_store.get_page(page_id)
            svc = linked_service or (page.get("linked_service", "") if page else "")
            _wiki_store_credentials(page_id, credentials, svc)
        return result

    @app.post("/v1/wiki/import-secrets")
    def wiki_import_secrets() -> dict[str, Any]:
        """Import all existing secrets.json entries as wiki pages."""
        from ..wiki.sync import WikiSync

        sync = WikiSync(manager.wiki_store, manager.vault, manager.secrets)
        return sync.import_all_secrets()

    @app.post("/v1/wiki/{page_id}/sync")
    def wiki_sync_to_secrets(page_id: str) -> dict[str, Any]:
        """Sync wiki page credentials to secrets.json."""
        from ..wiki.sync import WikiSync

        sync = WikiSync(manager.wiki_store, manager.vault, manager.secrets)
        return sync.sync_page_to_secrets(page_id)

    @app.delete("/v1/wiki/{page_id}")
    def wiki_delete(page_id: str) -> dict[str, Any]:
        from ..security.rate_limiter import get_limiter

        limiter = get_limiter("destructive", 10, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        return manager.wiki_store.delete_page(page_id)

    @app.post("/v1/wiki/{page_id}/restore")
    def wiki_restore(page_id: str) -> dict[str, Any]:
        return manager.wiki_store.restore_page(page_id)

    @app.get("/v1/wiki/{page_id}/history")
    def wiki_history(page_id: str) -> dict[str, Any]:
        return {"history": manager.wiki_store.get_history(page_id)}

    @app.post("/v1/wiki/{page_id}/credentials/{key}/reveal")
    def wiki_reveal_credential(page_id: str, key: str) -> dict[str, Any]:
        from ..security.rate_limiter import get_limiter

        limiter = get_limiter("reveal", 10, 60)
        if not limiter.check():
            return JSONResponse({"ok": False, "error": "Rate limit exceeded"}, status_code=429)
        vault_key = f"{page_id}:{key}"
        try:
            value = manager.vault.retrieve(vault_key)
            return {"ok": True, "key": key, "value": value}
        except KeyError:
            return JSONResponse({"error": f"credential '{key}' not found"}, status_code=404)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=403)

    @app.post("/v1/wiki/analyze")
    def wiki_analyze(body: dict) -> dict[str, Any]:
        """AI-analyze free-form wiki content to extract credentials and service info.
        Returns suggested credentials, category, and linked_service for user confirmation."""
        from ..wiki.analyzer import analyze_document

        content = str(body.get("content", ""))
        title = str(body.get("title", ""))
        if not content:
            return {"error": "content is required"}
        return analyze_document(content, title)

    @app.post("/v1/wiki/{page_id}/analyze")
    def wiki_analyze_page(page_id: str) -> dict[str, Any]:
        """Analyze an existing wiki page to extract/update credentials."""
        from ..wiki.analyzer import analyze_document

        page = manager.wiki_store.get_page(page_id)
        if page is None:
            return JSONResponse({"error": "page not found"}, status_code=404)
        return analyze_document(page.get("content", ""), page.get("name", ""))

    @app.get("/v1/wiki/prompts")
    def wiki_prompts_list() -> dict:
        pages = manager.wiki_store.list_pages(category="prompt")
        return {"ok": True, "prompts": pages}

    @app.get("/v1/wiki/prompts/{page_id}/runs")
    def wiki_prompt_runs(page_id: str) -> dict:
        runs = manager.wiki_store.get_prompt_runs(page_id)
        return {"ok": True, "runs": runs}

    @app.post("/v1/wiki/prompts/{page_id}/test")
    async def wiki_prompt_test(page_id: str, body: dict) -> dict:
        """Test a prompt with given variables. Returns mock result for now."""
        import uuid as _uuid

        page = manager.wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "page not found"}
        variables = body.get("variables", {})
        model_id = body.get("model_id", "unknown")
        # Record the test run
        run_id = str(_uuid.uuid4())[:8]
        manager.wiki_store.record_prompt_run(
            page_id=page_id, run_id=run_id, model_id=model_id,
            input_tokens=0, output_tokens=0, latency_ms=0,
            success=True, variables=variables, output_preview="(test recorded)",
            prompt_version=page.get("version", 1)
        )
        return {"ok": True, "run_id": run_id, "message": "Test run recorded"}

    @app.get("/v1/wiki/benchmarks")
    def wiki_benchmarks_list(page_id: str = "", model_id: str = "") -> dict:
        results = manager.wiki_store.get_benchmarks(page_id, model_id)
        return {"ok": True, "benchmarks": results}

    @app.post("/v1/wiki/benchmarks")
    def wiki_benchmarks_add(body: dict) -> dict:
        import uuid as _uuid

        return manager.wiki_store.record_benchmark(
            benchmark_id=body.get("benchmark_id", str(_uuid.uuid4())[:8]),
            page_id=str(body.get("page_id", "")),
            model_id=str(body.get("model_id", "")),
            metric_name=str(body.get("metric_name", "")),
            metric_value=float(body.get("metric_value", 0)),
            run_date=str(body.get("run_date", "")),
        )

    @app.post("/v1/wiki/models/calc-cost")
    def wiki_calc_cost(body: dict) -> dict:
        """Calculate monthly cost based on model card data."""
        input_price = float(body.get("input_price_per_1m", 0))
        output_price = float(body.get("output_price_per_1m", 0))
        daily_requests = int(body.get("daily_requests", 100))
        avg_input_tokens = int(body.get("avg_input_tokens", 1000))
        avg_output_tokens = int(body.get("avg_output_tokens", 500))

        monthly_input = daily_requests * 30 * avg_input_tokens
        monthly_output = daily_requests * 30 * avg_output_tokens
        cost = (monthly_input / 1_000_000 * input_price) + (monthly_output / 1_000_000 * output_price)

        return {"ok": True, "monthly_cost": round(cost, 2),
                "monthly_input_tokens": monthly_input, "monthly_output_tokens": monthly_output}

    # -- Runbook execution -------------------------------------------------

    @app.get("/v1/wiki/runbooks")
    def wiki_runbooks_list() -> dict[str, Any]:
        pages = manager.wiki_store.list_pages(category="runbook")
        return {"ok": True, "runbooks": pages}

    @app.get("/v1/wiki/runbooks/{page_id}/executions")
    def wiki_runbook_executions(page_id: str) -> dict[str, Any]:
        execs = manager.wiki_store.get_runbook_executions(page_id)
        return {"ok": True, "executions": execs}

    @app.post("/v1/wiki/runbooks/{page_id}/execute")
    def wiki_runbook_execute(page_id: str) -> dict[str, Any]:
        import uuid
        page = manager.wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "runbook not found"}
        # Parse steps from structured_data
        sd = page.get("structured_data", {})
        steps = sd.get("steps", []) if isinstance(sd, dict) else []
        exec_id = str(uuid.uuid4())[:8]
        manager.wiki_store.record_runbook_execution(
            execution_id=exec_id,
            page_id=page_id,
            steps_total=len(steps),
            executed_by="api",
        )
        return {"ok": True, "execution_id": exec_id, "steps_total": len(steps)}

    # -- Wiki export/import ------------------------------------------------

    @app.post("/v1/wiki/export")
    def wiki_export() -> dict[str, Any]:
        pages = manager.wiki_store.export_all()
        return {"ok": True, "pages": pages}

    @app.post("/v1/wiki/import")
    def wiki_import(body: dict) -> dict[str, Any]:
        pages = (body or {}).get("pages", [])
        if not isinstance(pages, list):
            return {"ok": False, "error": "pages must be a list"}
        return manager.wiki_store.import_pages(pages)

    # -- Vault rotation + audit --------------------------------------------

    @app.post("/v1/vault/rotate/{key}")
    def vault_rotate(key: str, body: dict) -> dict[str, Any]:
        new_value = body.get("new_value", "")
        if not new_value:
            return JSONResponse({"ok": False, "error": "new_value is required"}, status_code=400)
        return manager.vault.rotate(key, new_value)

    @app.get("/v1/vault/audit")
    def vault_audit(days: int = 7) -> dict[str, Any]:
        from datetime import datetime, timedelta, timezone

        path = Path.home() / ".config" / "werubworker" / "audit.log"
        if not path.is_file():
            return {"ok": True, "entries": []}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries: list[dict[str, str]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split("  ", 2)
                if len(parts) < 3:
                    continue
                ts_str, action, key_name = parts
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
                entries.append({"timestamp": ts_str, "action": action, "key": key_name})
        except OSError:
            pass
        return {"ok": True, "entries": entries}

    @app.get("/v1/vault/expiring")
    def vault_expiring(days: int = 30) -> dict[str, Any]:
        return {"ok": True, "expiring": manager.vault.check_expiring(days)}

    # -- Wiki template system ------------------------------------------------

    @app.get("/v1/wiki/templates")
    def wiki_templates() -> dict[str, Any]:
        from ..wiki.store import WIKI_TEMPLATES

        return {"ok": True, "templates": WIKI_TEMPLATES}

    @app.get("/v1/wiki/templates/{category}")
    def wiki_template_by_category(category: str) -> dict[str, Any]:
        from ..wiki.store import WIKI_TEMPLATES

        tmpl = WIKI_TEMPLATES.get(category)
        if not tmpl:
            return JSONResponse(
                {"ok": False, "error": f"no template for '{category}'"}, status_code=404
            )
        return {"ok": True, "template": tmpl}

    # -- Prompt A/B test -----------------------------------------------------

    @app.post("/v1/wiki/prompts/{page_id}/ab-test")
    def wiki_prompt_ab_test(page_id: str, body: dict) -> dict:
        """Compare two prompt versions side by side."""
        page = manager.wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "page not found"}
        history = manager.wiki_store.get_history(page_id)
        version_a = int(body.get("version_a", page.get("version", 1)))
        version_b = int(body.get("version_b", max(1, page.get("version", 1) - 1)))
        # Get content for both versions
        content_a = page.get("content", "")
        content_b = content_a
        for h in history:
            if h.get("version") == version_b:
                content_b = h.get("content", "")
                break
        # If version_a is not current, look it up too
        if version_a != page.get("version", 1):
            for h in history:
                if h.get("version") == version_a:
                    content_a = h.get("content", "")
                    break
        return {
            "ok": True,
            "version_a": {"version": version_a, "content": content_a},
            "version_b": {"version": version_b, "content": content_b},
        }

    # -- Wiki AI Summary -----------------------------------------------------

    @app.post("/v1/wiki/{page_id}/summarize")
    def wiki_summarize(page_id: str) -> dict:
        page = manager.wiki_store.get_page(page_id)
        if not page:
            return {"ok": False, "error": "not found"}
        content = page.get("content", "")
        # Simple extractive summary: first paragraph + all headings
        lines = content.split("\n")
        headings = [line for line in lines if line.startswith("#")]
        first_para = ""
        for line in lines:
            if line.strip() and not line.startswith("#"):
                first_para = line.strip()
                break
        summary = "\n".join(headings[:10])
        if first_para:
            summary = first_para + "\n\n" + summary
        return {"ok": True, "summary": summary[:500]}

    # -- Service Registry --------------------------------------------------

    @app.get("/v1/services")
    def services_list() -> dict:
        from ..registry import ServiceRegistry
        reg = ServiceRegistry(manager.wiki_store, manager.secrets, getattr(manager, 'vault', None))
        return {"ok": True, "services": reg.list_services()}

    @app.get("/v1/services/{service_ref:path}")
    def services_resolve(service_ref: str) -> dict:
        from ..registry import ServiceRegistry
        reg = ServiceRegistry(manager.wiki_store, manager.secrets, getattr(manager, 'vault', None))
        return {"ok": True, **reg.resolve(service_ref)}

    # -- Security filter test ----------------------------------------------

    @app.post("/v1/security/filter-test")
    def security_filter_test(body: dict) -> dict:
        from ..security.response_filter import filter_credentials
        text = str(body.get("text", ""))
        filtered = filter_credentials(text)
        return {"ok": True, "original_length": len(text), "filtered": filtered}

    # -- Dashboard & monitoring API routes --
    from .dashboard_mixin import register_dashboard_routes

    register_dashboard_routes(app, manager)

    return app


def _parse_json(s: str) -> dict[str, Any]:
    """Parse a structured Inbox resolution (directory/plan carry their reply as a JSON string)."""
    try:
        v = json.loads(s) if s else {}
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _openai_response(model: str, turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": turn.text or ""}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in turn.tool_calls
        ]
    return {
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": turn.finish_reason or "stop",
            }
        ],
    }
