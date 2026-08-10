"""Canva connector tools."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _clamp, _profile, _schema


def register(secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None) -> None:
    _CANVA = "https://api.canva.com/rest/v1"

    def canva_list_designs(query: str = "", max_results: int = 10) -> dict[str, Any]:
        profile, err = _profile(secrets, "canva", "access_token")
        if err:
            return err
        params: dict[str, Any] = {"limit": _clamp(max_results)}
        if query:
            params["query"] = query
        return _helpers._request(
            "GET",
            f"{_CANVA}/designs",
            headers=_bearer_headers(profile["access_token"]),
            params=params,
        )

    canva_list_designs.__name__ = "canva_list_designs"
    tools.append(
        _attach(
            canva_list_designs,
            _schema(
                "canva_list_designs",
                "List (or text-search) Canva designs.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                [],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_get_design(design_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "canva", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CANVA}/designs/{quote(design_id)}",
            headers=_bearer_headers(profile["access_token"]),
        )

    canva_get_design.__name__ = "canva_get_design"
    tools.append(
        _attach(
            canva_get_design,
            _schema(
                "canva_get_design",
                "Read a Canva design's metadata (title, pages, urls).",
                {"design_id": {"type": "string"}},
                ["design_id"],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_export_design(design_id: str, format: str = "pdf") -> dict[str, Any]:
        profile, err = _profile(secrets, "canva", "access_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"{_CANVA}/exports",
            headers=_bearer_headers(profile["access_token"]),
            json={"design_id": design_id, "format": {"type": format}},
        )

    canva_export_design.__name__ = "canva_export_design"
    tools.append(
        _attach(
            canva_export_design,
            _schema(
                "canva_export_design",
                "Start rendering a Canva design to pdf/png/jpg; returns an export job to poll.",
                {"design_id": {"type": "string"}, "format": {"type": "string"}},
                ["design_id"],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_get_export(export_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "canva", "access_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CANVA}/exports/{quote(export_id)}",
            headers=_bearer_headers(profile["access_token"]),
        )

    canva_get_export.__name__ = "canva_get_export"
    tools.append(
        _attach(
            canva_get_export,
            _schema(
                "canva_get_export",
                "Check a Canva export job; returns download URLs when finished.",
                {"export_id": {"type": "string"}},
                ["export_id"],
            ),
            caps=["canva", "read"],
        )
    )
