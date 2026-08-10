"""Skill loading — Anthropic SKILL.md format with progressive disclosure.

A skill is a folder containing `SKILL.md` (YAML frontmatter: name, description,
optional allowed-tools) + a markdown body of instructions + optional resources/scripts.

Progressive disclosure: at session start only the catalog (name + description) is injected
into the agent's context; the full body is loaded on demand via the `load_skill` tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

import aisuite as ai

_CACHE_TTL = 30  # seconds


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""  # full body — loaded on demand
    path: Optional[str] = None
    allowed_tools: list[str] = field(default_factory=list)


class SkillLoader:
    def __init__(self, dirs: list[str | Path]) -> None:
        self._dirs = [Path(d) for d in dirs]
        self._skills: dict[str, Skill] = {}
        self._last_scan: float = 0
        self._last_mtimes: dict[str, float] = {}
        self.rescan(force=True)

    def rescan(self, *, force: bool = False) -> None:
        """Re-read the skill dirs. Uses mtime caching with a 30s TTL — if no
        directory has changed since the last scan, the cached skills are reused.
        Pass force=True to bypass the cache (used on init and explicit refresh)."""
        now = time.monotonic()
        if not force and (now - self._last_scan) < _CACHE_TTL:
            # Quick mtime check — if all dirs have the same mtime, skip the full scan.
            if not self._dirs_changed():
                return
        self._skills = {}
        for directory in self._dirs:
            self._discover(directory)
        self._last_scan = now
        self._last_mtimes = self._snapshot_mtimes()

    def _dirs_changed(self) -> bool:
        """Check whether any skill directory's mtime has changed since last scan."""
        current = self._snapshot_mtimes()
        return current != self._last_mtimes

    def _snapshot_mtimes(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for d in self._dirs:
            try:
                out[str(d)] = d.stat().st_mtime
                # Also check immediate subdirectories (skill folders).
                for sub in d.iterdir():
                    if sub.is_dir():
                        md = sub / "SKILL.md"
                        if md.exists():
                            out[str(md)] = md.stat().st_mtime
            except OSError:
                pass
        return out

    def _discover(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for sub in sorted(directory.iterdir()):
            md = sub / "SKILL.md"
            if md.is_file():
                skill = _parse_skill(md)
                self._skills[skill.name] = skill

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def catalog(self) -> list[dict]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]


def _parse_skill(md: Path) -> Skill:
    text = md.read_text(encoding="utf-8")
    name, description, allowed, body = md.parent.name, "", [], text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key, value = key.strip().lower(), value.strip()
                if key == "name" and value:
                    name = value
                elif key == "description":
                    description = value
                elif key in ("allowed-tools", "allowed_tools"):
                    allowed = [t.strip() for t in value.split(",") if t.strip()]
    return Skill(
        name=name,
        description=description,
        instructions=body.strip(),
        path=str(md.parent),
        allowed_tools=allowed,
    )


def skill_catalog_text(loader: SkillLoader, allowed: Optional[set[str]] = None) -> str:
    catalog = [c for c in loader.catalog() if allowed is None or c["name"] in allowed]
    if not catalog:
        return ""
    lines = [f"- {c['name']}: {c['description']}" for c in catalog]
    return (
        "Available skills — call load_skill(name) to load one's full instructions when "
        "it's relevant to the task:\n" + "\n".join(lines)
    )


AllowedSkills = Union[set, Callable[[], set], None]


def skill_tools(loader: SkillLoader, allowed: AllowedSkills = None) -> list:
    """`allowed` gates load_skill: a set is a build-time snapshot; a CALLABLE is consulted
    on every call — the manager passes one so Settings disables apply to live sessions
    immediately, and skills created after the engine was built are still loadable
    (loader rescans on a miss)."""

    def _allowed_now() -> Optional[set]:
        return allowed() if callable(allowed) else allowed

    def load_skill(name: str) -> dict:
        """Load a skill's full instructions + resources path by name. Call this when a
        skill from the catalog is relevant to the current task."""
        skill = loader.get(name)
        if skill is None:
            loader.rescan(force=True)  # created after this session started? pick it up now
            skill = loader.get(name)
        gate = _allowed_now()
        if skill is None or (gate is not None and name not in gate):
            available = sorted(n for n in loader.names() if gate is None or n in gate)
            return {"error": f"unknown skill: {name}", "available": available}
        return {
            "name": skill.name,
            "instructions": skill.instructions,
            "resources_path": skill.path,
        }

    return [
        ai.tool(
            load_skill,
            metadata=ai.ToolMetadata(
                category="skills", risk_level="low", capabilities=["load_skill"]
            ),
        )
    ]
