"""预设管理。

一个预设 = `presets/` 下的一个目录（与世界目录同级，默认在项目根下）：

    presets/
      角色模板/
        preset.json     # 名字、创建时间、格式版本，以及一组「属性名」（只有键，没有值）

预设只描述**有哪些属性**，具体值永远存在角色自己身上，所以套用预设不会改动任何已有值。
名字规则复用 worlds.validate_name（目录名的限制是一样的）。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .worlds import WorldError, validate_name

FORMAT_VERSION = 2
META_NAME = "preset.json"
KEYS_MAX = 50


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


def normalize_keys(items: Any) -> list[str]:
    """预设只存属性名：去空、去重、截断长度、上限若干条。"""
    keys: list[str] = []
    if not isinstance(items, list):
        return keys

    for item in items:
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("label") or "").strip()
        else:
            key = str(item).strip()
        if not key or key in keys:
            continue
        keys.append(key[:40])
        if len(keys) >= KEYS_MAX:
            break
    return keys


def _preset_keys(meta: dict[str, Any]) -> list[str]:
    """读预设的键；兼容旧版存 attributes（带值）的格式。"""
    keys = normalize_keys(meta.get("keys"))
    if keys:
        return keys
    # 旧格式：[{"label": "年龄", "value": "17"}] → 只取 label
    return normalize_keys(meta.get("attributes"))


def _read_meta(directory: Path) -> dict[str, Any]:
    meta = directory / META_NAME
    if not meta.is_file():
        return {}
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def list_presets(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        meta = _read_meta(entry)
        created = meta.get("created_at")
        if not created:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            created = mtime.isoformat(timespec="seconds")
        items.append(
            {
                "name": entry.name,
                "created_at": str(created),
                "path": f"presets/{entry.name}",
                "keys": _preset_keys(meta),
            }
        )
    return items


def create_preset(root: Path, raw_name: str, keys: Any = None) -> dict[str, Any]:
    name = validate_name(raw_name)
    path = _preset_path(root, name)
    if path.exists():
        raise WorldError(f"预设「{name}」已经存在", status=409)

    try:
        path.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise WorldError(f"创建目录失败：{exc.strerror or exc}") from exc

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized = normalize_keys(keys)
    meta = {
        "name": name,
        "created_at": created,
        "format": FORMAT_VERSION,
        "keys": normalized,
    }
    (path / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "name": name,
        "created_at": created,
        "path": f"presets/{name}",
        "keys": normalized,
    }


def delete_preset(root: Path, raw_name: str) -> dict[str, Any]:
    """删除预设目录（连同 preset.json）。"""
    name = validate_name(raw_name)
    path = _preset_path(root, name)
    if not path.is_dir():
        raise WorldError(f"预设「{name}」不存在", status=404)

    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise WorldError(f"删除失败：{exc.strerror or exc}") from exc
    return {"name": name, "deleted": True, "path": f"presets/{name}"}


def update_preset(
    root: Path,
    raw_name: str,
    *,
    new_name: str | None = None,
    keys: Any = None,
) -> dict[str, Any]:
    """改预设：重命名目录 + 覆盖属性名列表。"""
    name = validate_name(raw_name)
    directory = _preset_path(root, name)
    if not directory.is_dir():
        raise WorldError(f"预设「{name}」不存在", status=404)

    target_name = name
    if new_name is not None:
        target_name = validate_name(new_name)
        if target_name != name:
            target = root / target_name
            if target.exists():
                raise WorldError(f"预设「{target_name}」已经存在", status=409)
            try:
                directory.rename(target)
            except OSError as exc:
                raise WorldError(f"重命名失败：{exc.strerror or exc}") from exc
            directory = target

    meta = _read_meta(directory)
    meta["name"] = target_name
    meta["format"] = FORMAT_VERSION
    meta.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if keys is not None:
        meta["keys"] = normalize_keys(keys)
    else:
        meta["keys"] = _preset_keys(meta)
    meta.pop("attributes", None)  # 旧格式字段不再保留

    (directory / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "name": target_name,
        "created_at": meta["created_at"],
        "path": f"presets/{target_name}",
        "keys": meta["keys"],
    }
