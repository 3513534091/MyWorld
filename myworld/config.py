"""配置解析。

优先级（高 → 低）：

    命令行参数  >  环境变量 MYWORLD_*  >  配置文件 myworld.config.json  >  内置默认值

端口策略：
    - 默认监听 127.0.0.1:8000（只允许本机访问，符合「本地程序」的定位）。
    - 指定端口被占用时，自动向上找一个空闲端口，并在启动信息里说明顺延情况。
    - 传 --strict-port 则改为直接报错，不做顺延。
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

CONFIG_FILENAMES = ("myworld.config.json", "config.json")
ENV_MAP = {
    "MYWORLD_HOST": "host",
    "MYWORLD_PORT": "port",
    "MYWORLD_OPEN_BROWSER": "open_browser",
    "MYWORLD_LOG_LEVEL": "log_level",
}
LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")

# 端口顺延时最多向后探测多少个端口
PORT_SCAN_LIMIT = 128


class ConfigError(Exception):
    """配置非法：端口越界、JSON 损坏、类型不对等。"""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(slots=True)
class Settings:
    """一次启动生效的配置快照。"""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    open_browser: bool = False
    log_level: str = "info"

    # 端口顺延相关信息，便于前端/日志如实展示
    requested_port: int = DEFAULT_PORT
    port_shifted: bool = False

    # 每个字段来自哪里：default / env:MYWORLD_PORT / file:<path> / cli
    sources: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        """可安全暴露给前端的配置（不含 sources）。"""
        data = asdict(self)
        data.pop("sources", None)
        return data


def _validate_port(value: Any, origin: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{origin} 的 port 不是整数：{value!r}") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(f"{origin} 的 port 超出范围 1-65535：{port}")
    return port


def _find_config_file(explicit: str | Path | None, cwd: Path) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"配置文件不存在：{path}")
        return path
    for name in CONFIG_FILENAMES:
        candidate = cwd / name
        if candidate.is_file():
            return candidate
    return None


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是 JSON 对象：{path}")
    return raw


def is_port_free(host: str, port: int) -> bool:
    """端口能否被绑定。

    注意：Windows 上 SO_REUSEADDR 会允许「抢占」已被监听的端口，
    从而把占用误判成空闲，所以只在 POSIX 上设置它。
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if os.name != "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def find_free_port(host: str, start: int, limit: int = PORT_SCAN_LIMIT) -> int | None:
    """从 start 起向后找第一个可绑定端口，找不到返回 None。"""
    for port in range(start, min(start + limit, 65536)):
        if is_port_free(host, port):
            return port
    return None


def resolve(
    *,
    cwd: Path | None = None,
    cli: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config_file: str | Path | None = None,
) -> Settings:
    """按优先级合并各来源，产出最终配置。"""
    cwd = cwd or Path.cwd()
    env = os.environ if env is None else env
    cli = {k: v for k, v in (cli or {}).items() if v is not None}

    values: dict[str, Any] = {}
    sources: dict[str, str] = {}

    # 3. 配置文件
    path = _find_config_file(config_file, cwd)
    if path is not None:
        for key, value in _read_config_file(path).items():
            if key in {"host", "port", "open_browser", "log_level"}:
                values[key] = value
                sources[key] = f"file:{path.name}"

    # 2. 环境变量
    for env_key, key in ENV_MAP.items():
        raw = env.get(env_key)
        if raw is not None and str(raw).strip() != "":
            values[key] = raw
            sources[key] = f"env:{env_key}"

    # 1. 命令行
    for key in ("host", "port", "open_browser", "log_level"):
        if key in cli:
            values[key] = cli[key]
            sources[key] = "cli"

    host = str(values.get("host", DEFAULT_HOST)).strip() or DEFAULT_HOST
    if "host" not in sources:
        sources["host"] = "default"

    requested_port = _validate_port(values.get("port", DEFAULT_PORT), sources.get("port", "default"))
    if "port" not in sources:
        sources["port"] = "default"

    log_level = str(values.get("log_level", "info")).strip().lower()
    if log_level not in LOG_LEVELS:
        raise ConfigError(f"log_level 只能是 {', '.join(LOG_LEVELS)}，收到：{log_level!r}")
    if "log_level" not in sources:
        sources["log_level"] = "default"

    open_browser = _as_bool(values.get("open_browser", False))
    if "open_browser" not in sources:
        sources["open_browser"] = "default"

    # 端口可用性检查与顺延
    port = requested_port
    shifted = False
    if not is_port_free(host, port):
        if _as_bool(cli.get("strict_port", False)):
            raise ConfigError(f"端口 {port} 已被占用（指定了 --strict-port，不做顺延）")
        candidate = find_free_port(host, port + 1)
        if candidate is None:
            raise ConfigError(f"{host} 上从 {port} 起连续 {PORT_SCAN_LIMIT} 个端口都不可用")
        port, shifted = candidate, True
        sources["port"] = f"{sources['port']}+auto-shift"

    return Settings(
        host=host,
        port=port,
        open_browser=open_browser,
        log_level=log_level,
        requested_port=requested_port,
        port_shifted=shifted,
        sources=sources,
    )
