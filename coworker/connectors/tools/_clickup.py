"""ClickUp connector tools."""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from ...secrets import SecretStore
from . import _helpers
from ._helpers import _attach, _profile, _schema


def register(
    secrets: SecretStore, tools: list[Callable[..., Any]], *, roots=None
) -> None:
    _CLICKUP = "https://api.clickup.com/api/v2"

    def clickup_list_teams() -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET", f"{_CLICKUP}/team", headers={"Authorization": profile["api_token"]}
        )

    clickup_list_teams.__name__ = "clickup_list_teams"
    tools.append(
        _attach(
            clickup_list_teams,
            _schema(
                "clickup_list_teams",
                "List ClickUp workspaces (team ids are needed to browse spaces).",
                {},
                [],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_spaces(team_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CLICKUP}/team/{quote(team_id)}/space",
            headers={"Authorization": profile["api_token"]},
        )

    clickup_list_spaces.__name__ = "clickup_list_spaces"
    tools.append(
        _attach(
            clickup_list_spaces,
            _schema(
                "clickup_list_spaces",
                "List spaces in a ClickUp workspace.",
                {"team_id": {"type": "string"}},
                ["team_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_lists(space_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CLICKUP}/space/{quote(space_id)}/list",
            headers={"Authorization": profile["api_token"]},
        )

    clickup_list_lists.__name__ = "clickup_list_lists"
    tools.append(
        _attach(
            clickup_list_lists,
            _schema(
                "clickup_list_lists",
                "List folderless lists in a ClickUp space (list ids hold the tasks).",
                {"space_id": {"type": "string"}},
                ["space_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_list_tasks(
        list_id: str, include_closed: bool = False, max_results: int = 10
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CLICKUP}/list/{quote(list_id)}/task",
            headers={"Authorization": profile["api_token"]},
            params={
                "include_closed": str(bool(include_closed)).lower(),
                "page": 0,
            },
        )

    clickup_list_tasks.__name__ = "clickup_list_tasks"
    tools.append(
        _attach(
            clickup_list_tasks,
            _schema(
                "clickup_list_tasks",
                "List tasks in a ClickUp list.",
                {
                    "list_id": {"type": "string"},
                    "include_closed": {"type": "boolean"},
                    "max_results": {"type": "integer"},
                },
                ["list_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_get_task(task_id: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "GET",
            f"{_CLICKUP}/task/{quote(task_id)}",
            headers={"Authorization": profile["api_token"]},
            params={"include_subtasks": "true"},
        )

    clickup_get_task.__name__ = "clickup_get_task"
    tools.append(
        _attach(
            clickup_get_task,
            _schema(
                "clickup_get_task",
                "Read a ClickUp task (with subtasks) by id.",
                {"task_id": {"type": "string"}},
                ["task_id"],
            ),
            caps=["clickup", "read"],
        )
    )

    def clickup_create_task(
        list_id: str, name: str, description: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"{_CLICKUP}/list/{quote(list_id)}/task",
            headers={"Authorization": profile["api_token"]},
            json={"name": name, "description": description},
        )

    clickup_create_task.__name__ = "clickup_create_task"
    tools.append(
        _attach(
            clickup_create_task,
            _schema(
                "clickup_create_task",
                "Create a ClickUp task in a list. Requires user approval.",
                {
                    "list_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                ["list_id", "name"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )

    def clickup_update_task(
        task_id: str, name: str = "", description: str = "", status: str = ""
    ) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        if status:
            body["status"] = status
        if not body:
            return {"error": "nothing to update: pass name, description, or status"}
        return _helpers._request(
            "PUT",
            f"{_CLICKUP}/task/{quote(task_id)}",
            headers={"Authorization": profile["api_token"]},
            json=body,
        )

    clickup_update_task.__name__ = "clickup_update_task"
    tools.append(
        _attach(
            clickup_update_task,
            _schema(
                "clickup_update_task",
                "Update a ClickUp task's name, description, or status. Requires user approval.",
                {
                    "task_id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {"type": "string"},
                },
                ["task_id"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )

    def clickup_add_comment(task_id: str, text: str) -> dict[str, Any]:
        profile, err = _profile(secrets, "clickup", "api_token")
        if err:
            return err
        return _helpers._request(
            "POST",
            f"{_CLICKUP}/task/{quote(task_id)}/comment",
            headers={"Authorization": profile["api_token"]},
            json={"comment_text": text},
        )

    clickup_add_comment.__name__ = "clickup_add_comment"
    tools.append(
        _attach(
            clickup_add_comment,
            _schema(
                "clickup_add_comment",
                "Comment on a ClickUp task. Requires user approval.",
                {"task_id": {"type": "string"}, "text": {"type": "string"}},
                ["task_id", "text"],
            ),
            approval=True,
            caps=["clickup", "write"],
        )
    )
