"""Gmail connector tools."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import (
    _attach,
    _gmail_filters,
    _gmail_is_hidden,
    _gmail_label_map,
    _gmail_profile,
    _google_headers,
    _schema,
)


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    _ACCOUNT_PROP = {
        "type": "string",
        "description": "Mailbox email to use; omit for the default account.",
    }

    def gmail_search_messages(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        token = profile["access_token"]
        result = _helpers._request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=_google_headers(token),
            params={"q": query, "maxResults": max(1, min(int(max_results or 10), 20))},
        )
        filters = _gmail_filters(secrets)
        if result.get("ok") and filters:
            # Enforce "Never show agents" HERE, silently: matching hits are
            # omitted (no tombstone); the count rides the `_display` sidecar for
            # the user's tool card + audit — never the agent-visible content.
            data = dict(result.get("data") or {})
            label_map = _gmail_label_map(token) if filters["labels"] else {}
            kept, hidden = [], 0
            for m in data.get("messages") or []:
                meta = _helpers._request(
                    "GET",
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m.get('id')}",
                    headers=_google_headers(token),
                    params={"format": "metadata", "metadataHeaders": "From"},
                )
                detail = meta.get("data") if meta.get("ok") else None
                # Fail-open on a metadata miss: ids alone reveal nothing, and
                # gmail_get_message re-enforces before any content flows.
                if isinstance(detail, dict) and _gmail_is_hidden(
                    detail, filters, label_map
                ):
                    hidden += 1
                else:
                    kept.append(m)
            if hidden:
                data["messages"] = kept
                if isinstance(data.get("resultSizeEstimate"), int):
                    data["resultSizeEstimate"] = max(
                        0, data["resultSizeEstimate"] - hidden
                    )
                result = {
                    "ok": True,
                    "data": data,
                    "_display": {"hidden_by_filters": hidden, "connector": "gmail"},
                }
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_search_messages.__name__ = "gmail_search_messages"
    tools.append(
        _attach(
            gmail_search_messages,
            _schema(
                "gmail_search_messages",
                "Search Gmail messages using Gmail query syntax.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": _ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["gmail", "read"],
        )
    )

    def gmail_get_message(message_id: str, account: str = "") -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        token = profile["access_token"]
        result = _helpers._request(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers=_google_headers(token),
            params={"format": "full"},
        )
        filters = _gmail_filters(secrets)
        if result.get("ok") and filters:
            data = result.get("data") or {}
            label_map = _gmail_label_map(token) if filters["labels"] else {}
            if isinstance(data, dict) and _gmail_is_hidden(data, filters, label_map):
                # Indistinguishable from a real miss — the agent must not be able
                # to tell "filtered" from "gone" (a tombstone invites probing).
                return {
                    "error": "HTTP 404",
                    "details": {"error": {"code": 404, "message": "Not Found"}},
                    "_display": {"hidden_by_filters": 1, "connector": "gmail"},
                }
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_get_message.__name__ = "gmail_get_message"
    tools.append(
        _attach(
            gmail_get_message,
            _schema(
                "gmail_get_message",
                "Read a Gmail message by ID.",
                {"message_id": {"type": "string"}, "account": _ACCOUNT_PROP},
                ["message_id"],
            ),
            caps=["gmail", "read"],
        )
    )

    def gmail_send_email(
        to: str, subject: str, body: str, cc: str = "", account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        msg = EmailMessage()
        msg["To"], msg["Subject"] = to, subject
        if cc:
            msg["Cc"] = cc
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        result = _helpers._request(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers=_google_headers(profile["access_token"]),
            json={"raw": raw},
        )
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_send_email.__name__ = "gmail_send_email"
    tools.append(
        _attach(
            gmail_send_email,
            _schema(
                "gmail_send_email",
                "Send an email through Gmail. Requires user approval; the "
                "`account` argument names the sending mailbox on the approval card.",
                {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "account": _ACCOUNT_PROP,
                },
                ["to", "subject", "body"],
            ),
            approval=True,
            caps=["gmail", "write"],
        )
    )
