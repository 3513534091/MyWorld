"""角色管理。

一个角色属于某个世界，存在世界目录下的 `role/` 里：

    data/
      山与海/
        world.json
        role/
          阿澈/
            character.json
            portrait.png      # 可选，9:16 立绘；没有就用默认图

早期版本用的是 `characters/`，读取时若发现旧目录会自动改名迁移成 `role/`。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .worlds import WorldError, validate_name, world_dir

FORMAT_VERSION = 1
DIR_NAME = "role"
LEGACY_DIR_NAME = "characters"
META_NAME = "character.json"
ORDER_NAME = "order.json"
ATTRIBUTES_MAX = 50
PORTRAIT_FILENAMES = (
    "portrait.png",
    "portrait.jpg",
    "portrait.jpeg",
    "portrait.webp",
)


def _root(worlds_root: Path, world_name: str) -> Path:
    """世界的角色目录（不存在就建；旧的 characters/ 会自动改名过来）。"""
    world_path = world_dir(worlds_root, world_name)
    directory = world_path / DIR_NAME
    legacy = world_path / LEGACY_DIR_NAME

    if not directory.exists() and legacy.is_dir():
        try:
            shutil.move(str(legacy), str(directory))
        except OSError:
            # 改名失败就继续用旧的，至少不丢数据
            directory = legacy

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


def _read_order(root: Path) -> list[str]:
    path = root / ORDER_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("order", [])
    if not isinstance(data, list):
        return []
    return [str(item) for item in data]


def list_characters(worlds_root: Path, world_name: str) -> list[dict[str, Any]]:
    root = _root(worlds_root, world_name)

    # 先按保存的顺序，再按名字补上没记录过的
    order = _read_order(root)
    index = {name: i for i, name in enumerate(order)}
    directories = [entry for entry in root.iterdir() if entry.is_dir()]
    directories.sort(key=lambda entry: (index.get(entry.name, len(order)), entry.name.lower()))

    items: list[dict[str, Any]] = []
    for entry in directories:
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


def save_order(worlds_root: Path, world_name: str, names: list[str]) -> dict[str, Any]:
    """保存角色显示顺序；没提到的角色按名字补在末尾。"""
    root = _root(worlds_root, world_name)
    existing = {entry.name for entry in root.iterdir() if entry.is_dir()}

    ordered: list[str] = []
    for raw in names or []:
        name = validate_name(raw)
        if name in existing and name not in ordered:
            ordered.append(name)

    for name in sorted(existing - set(ordered), key=str.lower):
        ordered.append(name)

    (root / ORDER_NAME).write_text(
        json.dumps({"order": ordered}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"world": world_name, "order": ordered}


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


def _read_meta(directory: Path) -> dict[str, Any]:
    meta = directory / META_NAME
    if not meta.is_file():
        return {}
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_attributes(items: Any) -> list[dict[str, str]]:
    """把属性整理成 [{"label": ..., "value": ...}]，丢掉空行、限制条数与长度。"""
    result: list[dict[str, str]] = []
    if not isinstance(items, list):
        return result

    for item in items:
        if isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            value = str(item.get("value", "")).strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            label = str(item[0]).strip()
            value = str(item[1]).strip()
        else:
            continue
        if not label and not value:
            continue
        result.append({"label": label[:40], "value": value[:500]})
        if len(result) >= ATTRIBUTES_MAX:
            break
    return result


def read_character(worlds_root: Path, world_name: str, raw_name: str) -> dict[str, Any]:
    directory = _character_dir(worlds_root, world_name, raw_name)
    meta = _read_meta(directory)
    created = meta.get("created_at")
    if not created:
        created = datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    return {
        "name": directory.name,
        "created_at": str(created),
        "attributes": _normalize_attributes(meta.get("attributes")),
        "path": f"data/{world_name}/{DIR_NAME}/{directory.name}",
    }


def update_character(
    worlds_root: Path,
    world_name: str,
    raw_name: str,
    *,
    new_name: str | None = None,
    attributes: Any = None,
) -> dict[str, Any]:
    """改名字（会重命名目录并同步 order.json）或改属性。"""
    directory = _character_dir(worlds_root, world_name, raw_name)
    old_name = directory.name
    target_name = old_name

    if new_name is not None:
        target_name = validate_name(new_name)
        if target_name != old_name:
            target = directory.parent / target_name
            if target.exists():
                raise WorldError(f"角色「{target_name}」已经存在", status=409)
            try:
                directory.rename(target)
            except OSError as exc:
                raise WorldError(f"重命名失败：{exc.strerror or exc}") from exc
            directory = target

            order = [target_name if name == old_name else name for name in _read_order(directory.parent)]
            if target_name not in order:
                order.append(target_name)
            save_order(worlds_root, world_name, order)

    meta = _read_meta(directory)
    meta["name"] = target_name
    meta.setdefault("format", FORMAT_VERSION)
    meta.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if attributes is not None:
        meta["attributes"] = _normalize_attributes(attributes)

    (directory / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return read_character(worlds_root, world_name, target_name)


def delete_character(worlds_root: Path, world_name: str, raw_name: str) -> dict[str, Any]:
    """删除角色目录（连同立绘等文件）。"""
    directory = _character_dir(worlds_root, world_name, raw_name)
    try:
        shutil.rmtree(directory)
    except OSError as exc:
        raise WorldError(f"删除失败：{exc.strerror or exc}") from exc
    return {"world": world_name, "name": directory.name, "deleted": True}
