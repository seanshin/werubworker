"""Discord connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _clamp, _profile, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def discord_list_channels(guild_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "discord", "bot_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {profile['bot_token']}"},
        )

    discord_list_channels.__name__ = "discord_list_channels"
    tools.append(
        _attach(
            discord_list_channels,
            _schema(
                "discord_list_channels",
                "List channels in a Discord server (guild).",
                {"guild_id": {"type": "string"}},
                ["guild_id"],
            ),
            caps=["discord", "read"],
        )
    )

    def discord_read_messages(channel_id: str, max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "discord", "bot_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {profile['bot_token']}"},
            params={"limit": _clamp(max_results, ceiling=50)},
        )

    discord_read_messages.__name__ = "discord_read_messages"
    tools.append(
        _attach(
            discord_read_messages,
            _schema(
                "discord_read_messages",
                "Read recent messages from a Discord channel.",
                {"channel_id": {"type": "string"}, "max_results": {"type": "integer"}},
                ["channel_id"],
            ),
            caps=["discord", "read"],
        )
    )

    def discord_send_message(channel_id: str, content: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "discord", "bot_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {profile['bot_token']}"},
            json={"content": content[:2000]},
        )

    discord_send_message.__name__ = "discord_send_message"
    tools.append(
        _attach(
            discord_send_message,
            _schema(
                "discord_send_message",
                "Send a message to a Discord channel. Requires user approval.",
                {"channel_id": {"type": "string"}, "content": {"type": "string"}},
                ["channel_id", "content"],
            ),
            approval=True,
            caps=["discord", "write"],
        )
    )
