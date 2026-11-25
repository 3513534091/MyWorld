"""世界（world）管理。

一个世界 = `data/` 下的一个目录：

    data/
      第一个世界/
        world.json      # 元数据：名字、创建时间、格式版本
      第二个世界/
        world.json

目录名就是世界名，因此名字校验必须足够严：不允许路径分隔符、控制字符、
Windows 保留名、以及以点开头（避免和隐藏目录/相对路径混淆）。
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
NAME_MAX = 64
META_NAME = "world.json"

# 世界目录里放这几张图的任意一张，就会当作缩略图
THUMB_FILENAMES = (
    "thumbnail.png",
    "thumbnail.jpg",
    "thumbnail.jpeg",
    "thumbnail.webp",
    "thumbnail.gif",
)

# Windows 上不能做目录名的保留字
_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_RESERVED |= {f"COM{i}" for i in range(1, 10)}
_RESERVED |= {f"LPT{i}" for i in range(1, 10)}

_INVALID_CHARS = set('\\/:*?"<>|')


class WorldError(Exception):
    """世界名字非法，或与已有世界冲突。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def default_root() -> Path:
    """默认放在项目根目录的 data/ 下。"""
    return Path(__file__).resolve().parent.parent / "data"


def resolve_root(configured: str | None) -> Path:
    """解析世界目录的根，并确保它存在。"""
    root = Path(configured).expanduser() if configured else default_root()
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def validate_name(raw: str) -> str:
    """校验并归一化世界名；不合法直接抛 WorldError。"""
    name = unicodedata.normalize("NFC", (raw or "").strip())

    if not name:
        raise WorldError("世界名字不能为空")
    if len(name) > NAME_MAX:
        raise WorldError(f"世界名字最长 {NAME_MAX} 个字符")
    if any(ch in _INVALID_CHARS for ch in name):
        raise WorldError('名字里不能包含 \\ / : * ? " < > |')
    if any(ord(ch) < 32 for ch in name):
        raise WorldError("名字里不能有控制字符")
    if name.startswith("."):
        raise WorldError("名字不能以点开头")
    if name != name.rstrip(" ."):
        raise WorldError("名字结尾不能是空格或点")
    if name.split(".")[0].upper() in _RESERVED:
        raise WorldError("这是 Windows 的保留名，再换一个吧")
    return name


def _world_path(root: Path, name: str) -> Path:
    """把名字落到 root 下的路径，并确认没有跑出 root。"""
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


def world_dir(root: Path, raw_name: str) -> Path:
    """取一个已存在的世界目录；名字非法或世界不存在都会抛 WorldError。"""
    name = validate_name(raw_name)
    path = _world_path(root, name)
    if not path.is_dir():
        raise WorldError(f"世界「{name}」不存在", status=404)
    return path


def find_thumbnail(root: Path, raw_name: str) -> Path | None:
    """找世界的缩略图；没有就返回 None（由上层回落到默认图）。"""
    directory = world_dir(root, raw_name)
    for filename in THUMB_FILENAMES:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def list_worlds(root: Path) -> list[dict[str, Any]]:
    """列出所有世界，按名字排序。"""
    items: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not entry.is_dir():
            continue
        created = _read_created_at(entry)
        if created is None:
            # 没有 world.json（手工建的目录）就退回目录修改时间
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            created = mtime.isoformat(timespec="seconds")
        items.append(
            {
                "name": entry.name,
                "created_at": created,
                "path": f"data/{entry.name}",
            }
        )
    return items


def create_world(root: Path, raw_name: str) -> dict[str, Any]:
    """创建世界目录并写入元数据。"""
    name = validate_name(raw_name)
    path = _world_path(root, name)
    if path.exists():
        raise WorldError(f"世界「{name}」已经存在", status=409)

    try:
        path.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        raise WorldError(f"创建目录失败：{exc.strerror or exc}") from exc

    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "name": name,
        "created_at": created,
        "format": FORMAT_VERSION,
    }
    (path / META_NAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"name": name, "created_at": created, "path": f"data/{name}"}
