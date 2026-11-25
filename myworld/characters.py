"""角色管理。

一个角色属于某个世界，是世界目录下的一个子目录：

    data/
      山与海/
        world.json
        characters/
          阿澈/
            character.json
            portrait.png      # 可选，9:16 立绘；没有就用默认图
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .worlds import WorldError, validate_name, world_dir

FORMAT_VERSION = 1
DIR_NAME = "characters"
META_NAME = "character.json"
PORTRAIT_FILENAMES = (
    "portrait.png",
    "portrait.jpg",
    "portrait.jpeg",
    "portrait.webp",
)


def _root(worlds_root: Path, world_name: str) -> Path:
    """世界的角色目录（不存在就建）。"""
    directory = world_dir(worlds_root, world_name) / DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _character_dir(worlds_root: Path, world_name: str, raw_name: str) -> Path:
    name = validate_name(raw_name)
    directory = _root(worlds_root, world_name) / name
    if not directory.is_dir():
        raise WorldError(f"角色「{name}」不存在", status=404)
    return directory


def _created_at(directory: Path) -> str | None:
    meta = directory / META_NAME
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    created = data.get("created_at")
    return str(created) if created else None


def list_characters(worlds_root: Path, world_name: str) -> list[dict[str, Any]]:
    root = _root(worlds_root, world_name)
    items: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        created = _created_at(entry)
        if created is None:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            created = mtime.isoformat(timespec="seconds")
        items.append(
            {
                "name": entry.name,
                "created_at": created,
                "path": f"data/{world_name}/{DIR_NAME}/{entry.name}",
            }
        )
    return items


def create_character(worlds_root: Path, world_name: str, raw_name: str) -> dict[str, Any]:
    name = validate_name(raw_name)
    root = _root(worlds_root, world_name)
    path = root / name
    if path.exists():
        raise WorldError(f"角色「{name}」已经存在", status=409)

    try:
        path.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise WorldError(f"创建目录失败：{exc.strerror or exc}") from exc

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"name": name, "created_at": created, "format": FORMAT_VERSION}
    (path / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "name": name,
        "created_at": created,
        "path": f"data/{world_name}/{DIR_NAME}/{name}",
    }


def find_portrait(worlds_root: Path, world_name: str, raw_name: str) -> Path | None:
    directory = _character_dir(worlds_root, world_name, raw_name)
    for filename in PORTRAIT_FILENAMES:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def save_portrait(worlds_root: Path, world_name: str, raw_name: str, data: bytes, ext: str) -> Path:
    directory = _character_dir(worlds_root, world_name, raw_name)
    for filename in PORTRAIT_FILENAMES:
        (directory / filename).unlink(missing_ok=True)
    target = directory / f"portrait{ext}"
    target.write_bytes(data)
    return target
