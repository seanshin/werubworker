"""WhatsApp connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    def whatsapp_send_message(to: str, text: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "whatsapp", "access_token", "phone_number_id")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"https://graph.facebook.com/v21.0/{profile['phone_number_id']}/messages",
            headers=_bearer_headers(profile["access_token"]),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )

    whatsapp_send_message.__name__ = "whatsapp_send_message"
    tools.append(
        _attach(
            whatsapp_send_message,
            _schema(
                "whatsapp_send_message",
                "Send a WhatsApp text message. Only delivered if the recipient messaged "
                "this number within the last 24 hours; otherwise use "
                "whatsapp_send_template. Requires user approval.",
                {"to": {"type": "string"}, "text": {"type": "string"}},
                ["to", "text"],
            ),
            approval=True,
            caps=["whatsapp", "write"],
        )
    )

    def whatsapp_send_template(
        to: str, template_name: str, language_code: str = "en_US"
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "whatsapp", "access_token", "phone_number_id")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"https://graph.facebook.com/v21.0/{profile['phone_number_id']}/messages",
            headers=_bearer_headers(profile["access_token"]),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language_code},
                },
            },
        )

    whatsapp_send_template.__name__ = "whatsapp_send_template"
    tools.append(
        _attach(
            whatsapp_send_template,
            _schema(
                "whatsapp_send_template",
                "Send a pre-approved WhatsApp template message (works outside the "
                "24-hour service window). Requires user approval.",
                {
                    "to": {"type": "string"},
                    "template_name": {"type": "string"},
                    "language_code": {"type": "string"},
                },
                ["to", "template_name"],
            ),
            approval=True,
            caps=["whatsapp", "write"],
        )
    )
