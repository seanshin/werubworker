"""Asana connector tools."""

from __future__ import annotations

from typing import Any, Callable

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _bearer_headers, _clamp, _profile, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    def asana_list_workspaces() -> dict[str, Any]:
        profile, err = _profile(secrets, "asana", "token")
        if err:
            return err
        return _helpers._request(
            "GET",
            "https://app.asana.com/api/1.0/workspaces",
            headers=_bearer_headers(profile["token"]),
        )

    asana_list_workspaces.__name__ = "asana_list_workspaces"
    tools.append(
        _attach(
            asana_list_workspaces,
            _schema(
                "asana_list_workspaces",
                "List Asana workspaces (GIDs are needed to search tasks).",
                {},
                [],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_search_tasks(
        workspace_gid: str, query: str, max_results: int = 10
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "asana", "token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"https://app.asana.com/api/1.0/workspaces/{workspace_gid}/typeahead",
            headers=_bearer_headers(profile["token"]),
            params={
                "resource_type": "task",
                "query": query,
                "count": _clamp(max_results),
            },
        )

    asana_search_tasks.__name__ = "asana_search_tasks"
    tools.append(
        _attach(
            asana_search_tasks,
            _schema(
                "asana_search_tasks",
                "Search Asana tasks by name in a workspace. Get workspace_gid from asana_list_workspaces.",
                {
                    "workspace_gid": {"type": "string"},
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["workspace_gid", "query"],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_get_task(task_gid: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "asana", "token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"https://app.asana.com/api/1.0/tasks/{task_gid}",
            headers=_bearer_headers(profile["token"]),
        )

    asana_get_task.__name__ = "asana_get_task"
    tools.append(
        _attach(
            asana_get_task,
            _schema(
                "asana_get_task",
                "Read an Asana task.",
                {"task_gid": {"type": "string"}},
                ["task_gid"],
            ),
            caps=["asana", "read"],
        )
    )

    def asana_create_task(
        project_gid: str, name: str, notes: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "asana", "token")
        if err:
            return err
        return _helpers._request(
            "POST",
            "https://app.asana.com/api/1.0/tasks",
            headers=_bearer_headers(profile["token"]),
            json={"data": {"name": name, "notes": notes, "projects": [project_gid]}},
        )

    asana_create_task.__name__ = "asana_create_task"
    tools.append(
        _attach(
            asana_create_task,
            _schema(
                "asana_create_task",
                "Create an Asana task in a project. Requires user approval.",
                {
                    "project_gid": {"type": "string"},
                    "name": {"type": "string"},
                    "notes": {"type": "string"},
                },
                ["project_gid", "name"],
            ),
            approval=True,
            caps=["asana", "write"],
        )
    )
