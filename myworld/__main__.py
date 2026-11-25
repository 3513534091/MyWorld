"""命令行入口：python -m myworld"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

from . import __version__
from .config import LOG_LEVELS, ConfigError, resolve
from .server import create_app, display_host

BANNER = r"""
  __  __        __        __         _
 |  \/  |_   _  \ \      / /__  _ __| |
 | |\/| | | | |  \ \ /\ / / _ \| '__| |
 | |  | | |_| |   \ V  V / (_) | |  | |
 |_|  |_|\__, |    \_/\_/ \___/|_|  |_|
         |___/
"""


def _ensure_utf8_console() -> None:
    """Windows 控制台默认 GBK，中文/符号容易乱码，这里切到 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myworld",
        description="MyWorld —— 浏览器界面 + 本地服务的个人工作台",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", help="监听地址（默认 127.0.0.1，只允许本机访问）")
    parser.add_argument("--port", type=int, help="监听端口；被占用时自动向上顺延")
    parser.add_argument("--strict-port", action="store_true", help="端口被占用时直接报错，不顺延")
    parser.add_argument("--open", dest="open_browser", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--no-open", dest="open_browser", action="store_false", help="不自动打开浏览器")
    parser.add_argument("--log-level", choices=LOG_LEVELS, help="日志级别")
    parser.add_argument("--config", metavar="PATH", help="指定配置文件（默认读取 ./myworld.config.json）")
    parser.add_argument("--version", action="version", version=f"MyWorld {__version__}")
    parser.set_defaults(open_browser=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    args = build_parser().parse_args(argv)

    try:
        settings = resolve(
            cwd=Path.cwd(),
            cli={
                "host": args.host,
                "port": args.port,
                "open_browser": args.open_browser,
                "log_level": args.log_level,
                "strict_port": args.strict_port,
            },
            config_file=args.config,
        )
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2

    url = f"http://{display_host(settings.host)}:{settings.port}"

    print(BANNER)
    print(f"  MyWorld v{__version__}   ·   {url}")
    if settings.port_shifted:
        print(f"  ! 端口 {settings.requested_port} 已被占用，自动顺延到 {settings.port}")
    print("  配置来源：" + "  ".join(f"{k}={v}" for k, v in settings.sources.items()))
    print("  按 Ctrl+C 停止服务\n")
    # 输出被重定向到文件/管道时是块缓冲，这里强制刷新，保证日志立刻可见
    sys.stdout.flush()

    if settings.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app = create_app(settings)

    import uvicorn

    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            access_log=settings.log_level == "debug",
            ws="websockets",
        )
    except KeyboardInterrupt:
        pass
    print("\nMyWorld 已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
