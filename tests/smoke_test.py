"""端到端冒烟测试：拉起真实服务进程，验证 REST 与 WebSocket。

运行：python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parent.parent


def pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def wait_ready(session: aiohttp.ClientSession, base: str, timeout: float = 25.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with session.get(base + "/api/status", timeout=aiohttp.ClientTimeout(total=1)) as response:
                if response.status == 200:
                    return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError("服务未在超时内就绪")


def check_launcher() -> tuple[str, bool, str]:
    """原生启动器存在且能正确报告版本。"""
    exe = ROOT / "MyWorld.exe"
    if not exe.is_file():
        return ("MyWorld.exe 存在", False, f"缺失：{exe}")
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ("MyWorld.exe --version", False, f"{type(exc).__name__}: {exc}")
    output = (proc.stdout or proc.stderr or "").strip()
    return ("MyWorld.exe --version", proc.returncode == 0 and "MyWorld" in output, output)


async def run_checks(port: int, data_dir: str) -> list[tuple[str, bool, str]]:
    base = f"http://127.0.0.1:{port}"
    checks: list[tuple[str, bool, str]] = [check_launcher()]

    async with aiohttp.ClientSession() as session:
        status = await wait_ready(session, base)
        checks.append(("GET /api/status", status["status"] == "ok", f"v{status['version']} port={status['port']} pid={status['pid']}"))

        async with session.get(base + "/") as response:
            html = await response.text()
            checks.append(
                (
                    "GET / 返回前端页面",
                    response.status == 200 and "MyWorld" in html and "btnTheme" in html,
                    f"{response.status}, {len(html)} bytes",
                )
            )

        async with session.get(base + "/js/app.js") as response:
            checks.append(("GET /js/app.js 静态资源", response.status == 200, str(response.status)))

        async with session.get(base + "/css/style.css") as response:
            css = await response.text()
            checks.append(
                (
                    "GET /css/style.css 含浅色主题变量",
                    response.status == 200 and 'data-theme="light"' in css,
                    f"{response.status}, {len(css)} bytes",
                )
            )

        async with session.get(base + "/api/config") as response:
            config = await response.json()
            ok = response.status == 200 and "sources" in config and "port" in config
            checks.append(("GET /api/config", ok, json.dumps(config.get("sources", {}), ensure_ascii=False)))

        async with session.ws_connect(base + "/ws") as ws:
            hello = json.loads((await ws.receive(timeout=5)).data)
            checks.append(("WS 握手 hello", hello.get("kind") == "hello", f"v{hello.get('version')} port={hello.get('port')}"))

            await ws.send_json({"type": "ping", "t": 12345})
            pong = json.loads((await ws.receive(timeout=5)).data)
            checks.append(("WS ping → pong", pong.get("kind") == "pong" and pong.get("t") == 12345, json.dumps(pong)))

            async def trigger() -> dict:
                async with session.post(base + "/api/demo/tick") as response:
                    return await response.json()

            result, received = await asyncio.gather(trigger(), ws.receive(timeout=5))
            event = json.loads(received.data)
            checks.append(("POST /api/demo/tick 推送到 WS", event.get("kind") == "tick", f"delivered={result.get('delivered')}"))

            await ws.send_json({"type": "bogus"})
            error = json.loads((await ws.receive(timeout=5)).data)
            checks.append(("WS 未知消息类型返回 error", error.get("kind") == "error", str(error.get("message"))))

            await ws.send_json({"type": "stats"})
            stats = json.loads((await ws.receive(timeout=5)).data)
            checks.append(("WS stats", stats.get("kind") == "stats" and "uptime_seconds" in stats, f"uptime={stats.get('uptime_seconds')}s"))

        # ---- 世界管理（数据目录指向临时目录，不碰真实的 data/） ----
        async with session.get(base + "/api/worlds") as response:
            listing = await response.json()
            checks.append(
                (
                    "GET /api/worlds 初始为空",
                    response.status == 200 and listing.get("items") == [],
                    f"root={listing.get('root')}",
                )
            )

        async with session.post(base + "/api/worlds", json={"name": "测试世界"}) as response:
            created = await response.json()
            ok = response.status == 201 and created.get("name") == "测试世界"
            checks.append(("POST /api/worlds 创建世界", ok, f"{response.status} {created.get('path')}"))

        world_dir = Path(data_dir) / "测试世界"
        checks.append(
            (
                "世界目录与 world.json 已生成",
                (world_dir / "world.json").is_file(),
                str(world_dir),
            )
        )

        async with session.get(base + "/api/worlds") as response:
            listing = await response.json()
            names = [item["name"] for item in listing.get("items", [])]
            checks.append(("新世界出现在列表里", names == ["测试世界"], str(names)))

        async with session.post(base + "/api/worlds", json={"name": "测试世界"}) as response:
            body = await response.json()
            checks.append(("重名创建返回 409", response.status == 409, str(body.get("detail", ""))))

        async with session.post(base + "/api/worlds", json={"name": "../escape"}) as response:
            body = await response.json()
            checks.append(("非法名字返回 400", response.status == 400, str(body.get("detail", ""))))

        escaped = (Path(data_dir).parent / "escape").exists()
        checks.append(("路径逃逸被挡住", not escaped, "数据目录同级没有出现 escape"))

    return checks


async def main() -> int:
    port = pick_port()
    data_dir = tempfile.mkdtemp(prefix="myworld-data-")
    env = dict(os.environ, PYTHONUTF8="1", MYWORLD_DATA_DIR=data_dir)
    process = subprocess.Popen(
        [sys.executable, "-m", "myworld", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    checks: list[tuple[str, bool, str]] = []
    try:
        checks = await run_checks(port, data_dir)
    except Exception as exc:  # noqa: BLE001 - 冒烟测试需要把异常收敛成报告
        checks.append(("测试执行", False, f"{type(exc).__name__}: {exc}"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        output = (process.stdout.read() if process.stdout else "") or ""
        shutil.rmtree(data_dir, ignore_errors=True)

    width = max(len(name) for name, _, _ in checks) + 2
    failures = 0
    print("=" * 72)
    for name, ok, detail in checks:
        if not ok:
            failures += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name:<{width}} {detail}")
    print("=" * 72)

    if failures:
        print(f"失败 {failures} 项 / 共 {len(checks)} 项")
        if output.strip():
            print("---- 服务端输出 ----")
            print(output[-3000:])
        return 1

    print(f"全部通过：{len(checks)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
