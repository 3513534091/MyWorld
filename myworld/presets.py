"""预设管理。

一个预设 = `presets/` 下的一个目录（与世界目录同级，默认在项目根下）：

    presets/
      快速出图/
        preset.json     # 名字、创建时间、格式版本

名字规则复用 worlds.validate_name（目录名的限制是一样的）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .worlds import WorldError, validate_name

FORMAT_VERSION = 1
META_NAME = "preset.json"


def resolve_root(worlds_root: Path) -> Path:
    """预设放在世界目录的旁边（默认 <项目>/presets）。"""
    root = worlds_root.parent / "presets"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _preset_path(root: Path, name: str) -> Path:
    path = root / name
    if path.parent.resolve() != root:
        raise WorldError("非法路径")
    return path


def _read_created_at(directory: Path) -> str | None:
    meta = directory / META_NAME
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    created = data.get("created_at")
    return str(created) if created else None


def list_presets(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        created = _read_created_at(entry)
        if created is None:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            created = mtime.isoformat(timespec="seconds")
        items.append(
            {
                "name": entry.name,
                "created_at": created,
                "path": f"presets/{entry.name}",
            }
        )
    return items


def create_preset(root: Path, raw_name: str) -> dict[str, Any]:
    name = validate_name(raw_name)
    path = _preset_path(root, name)
    if path.exists():
        raise WorldError(f"预设「{name}」已经存在", status=409)

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
    return {"name": name, "created_at": created, "path": f"presets/{name}"}
