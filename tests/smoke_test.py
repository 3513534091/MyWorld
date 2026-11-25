"""端到端冒烟测试：拉起真实服务进程，验证 REST 与 WebSocket。

运行：python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

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

        thumb_url = f"{base}/api/worlds/{quote('测试世界')}/thumbnail"
        async with session.get(thumb_url + "?theme=dark") as response:
            dark_body = await response.read()
            content_type = response.headers.get("Content-Type", "")
            checks.append(
                (
                    "无缩略图时回落到默认图片（深色）",
                    response.status == 200 and content_type.startswith("image/svg+xml") and b"#241d47" in dark_body,
                    f"{response.status} {content_type} {len(dark_body)}B",
                )
            )

        async with session.get(thumb_url + "?theme=light") as response:
            light_body = await response.read()
            checks.append(
                (
                    "默认图片有浅色版",
                    response.status == 200 and b"#fbfaff" in light_body,
                    f"{response.status} {len(light_body)}B",
                )
            )

        checks.append(("深浅默认图内容不同", dark_body != light_body, f"{len(dark_body)} vs {len(light_body)}B"))

        async with session.get(f"{base}/api/worlds/{quote('不存在的世界')}/thumbnail") as response:
            checks.append(("未知世界的缩略图返回 404", response.status == 404, str(response.status)))

        # ---- 上传封面（裁剪后的图直接以原始字节 POST） ----
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4GBgYGRgQEAHnQDoG5mWxoAAAAASUVORK5CYII="
        )
        async with session.post(
            thumb_url,
            data=png_bytes,
            headers={"Content-Type": "image/png"},
        ) as response:
            body = await response.json()
            checks.append(
                (
                    "上传世界封面",
                    response.status == 200 and body.get("thumbnail") == "thumbnail.png",
                    f"{response.status} {body.get('thumbnail')} {body.get('bytes')}B",
                )
            )

        async with session.get(thumb_url) as response:
            served = await response.read()
            checks.append(
                (
                    "上传后缩略图返回真实图片",
                    response.status == 200
                    and response.headers.get("Content-Type", "").startswith("image/png")
                    and served == png_bytes,
                    f"{response.status} {len(served)}B",
                )
            )

        async with session.post(
            thumb_url,
            data=png_bytes,
            headers={"Content-Type": "text/plain"},
        ) as response:
            checks.append(("非图片类型上传被拒 400", response.status == 400, str(response.status)))

        async with session.post(
            f"{base}/api/worlds/{quote('不存在的世界')}/thumbnail",
            data=png_bytes,
            headers={"Content-Type": "image/png"},
        ) as response:
            checks.append(("给不存在的世界上传封面返回 404", response.status == 404, str(response.status)))

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

        # ---- 角色（属于某个世界） ----
        char_base = f"{base}/api/worlds/{quote('测试世界')}/characters"
        async with session.get(char_base) as response:
            listing = await response.json()
            checks.append(
                ("GET 角色列表初始为空", response.status == 200 and listing.get("items") == [], str(listing.get("items")))
            )

        async with session.post(char_base, json={"name": "测试角色"}) as response:
            created_char = await response.json()
            checks.append(
                (
                    "POST 新建角色",
                    response.status == 201 and created_char.get("path") == "data/测试世界/role/测试角色",
                    f"{response.status} {created_char.get('path')}",
                )
            )

        char_dir = Path(data_dir) / "测试世界" / "role" / "测试角色"
        checks.append(("角色目录与 character.json 已生成", (char_dir / "character.json").is_file(), str(char_dir)))

        async with session.get(char_base) as response:
            listing = await response.json()
            names = [item["name"] for item in listing.get("items", [])]
            checks.append(("角色出现在列表里", names == ["测试角色"], str(names)))

        async with session.post(char_base, json={"name": "测试角色"}) as response:
            checks.append(("角色重名返回 409", response.status == 409, str(response.status)))

        portrait_url = f"{char_base}/{quote('测试角色')}/portrait"
        async with session.get(portrait_url + "?theme=dark") as response:
            body = await response.read()
            checks.append(
                (
                    "无立绘时回落到默认角色图",
                    response.status == 200
                    and response.headers.get("Content-Type", "").startswith("image/svg+xml")
                    and b"CHARACTER" in body,
                    f"{response.status} {len(body)}B",
                )
            )

        async with session.post(portrait_url, data=png_bytes, headers={"Content-Type": "image/png"}) as response:
            checks.append(("上传角色立绘", response.status == 200, str(response.status)))

        async with session.get(portrait_url) as response:
            served = await response.read()
            checks.append(
                (
                    "上传后立绘返回真实图片",
                    response.status == 200 and served == png_bytes,
                    f"{response.status} {len(served)}B",
                )
            )

        async with session.get(f"{base}/api/worlds/{quote('不存在的世界')}/characters") as response:
            checks.append(("不存在世界的角色列表 404", response.status == 404, str(response.status)))

        # ---- 删除世界（放在世界相关断言之后，否则会把后面要用的目录删掉） ----
        async with session.delete(f"{base}/api/worlds/{quote('测试世界')}") as response:
            body = await response.json()
            checks.append(
                (
                    "DELETE /api/worlds 删除世界",
                    response.status == 200 and body.get("deleted") is True,
                    f"{response.status} {body.get('name')}",
                )
            )

        checks.append(
            (
                "世界目录已从磁盘移除",
                not (Path(data_dir) / "测试世界").exists(),
                str(Path(data_dir) / "测试世界"),
            )
        )

        checks.append(
            (
                "角色随世界目录一起删除",
                not (Path(data_dir) / "测试世界" / "role").exists(),
                "role/ 已不存在",
            )
        )

        async with session.get(base + "/api/worlds") as response:
            listing = await response.json()
            names = [item["name"] for item in listing.get("items", [])]
            checks.append(("删除后列表为空", names == [], str(names)))

        async with session.delete(f"{base}/api/worlds/{quote('测试世界')}") as response:
            checks.append(("删除不存在的世界返回 404", response.status == 404, str(response.status)))

        # ---- 预设（和世界同一套名字规则，独立目录） ----
        async with session.get(base + "/api/presets") as response:
            listing = await response.json()
            checks.append(
                (
                    "GET /api/presets 初始为空",
                    response.status == 200 and listing.get("items") == [],
                    f"root={listing.get('root')}",
                )
            )

        async with session.post(base + "/api/presets", json={"name": "测试预设"}) as response:
            preset = await response.json()
            checks.append(
                (
                    "POST /api/presets 创建预设",
                    response.status == 201 and preset.get("path") == "presets/测试预设",
                    f"{response.status} {preset.get('path')}",
                )
            )

        preset_dir = Path(data_dir).parent / "presets" / "测试预设"
        checks.append(
            (
                "预设目录与 preset.json 已生成",
                (preset_dir / "preset.json").is_file(),
                str(preset_dir),
            )
        )

        async with session.post(base + "/api/presets", json={"name": "测试预设"}) as response:
            body = await response.json()
            checks.append(("预设重名返回 409", response.status == 409, str(body.get("detail", ""))))

        async with session.get(base + "/api/worlds") as response:
            listing = await response.json()
            names = [item["name"] for item in listing.get("items", [])]
            checks.append(("预设不会混进世界列表", "测试预设" not in names, str(names)))

    return checks


async def main() -> int:
    port = pick_port()
    # 用沙箱目录：data/ 放里面，预设目录 presets/ 跟着落在同一层，跑完整个删掉
    sandbox = tempfile.mkdtemp(prefix="myworld-smoke-")
    data_dir = os.path.join(sandbox, "data")
    os.makedirs(data_dir, exist_ok=True)
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
        shutil.rmtree(sandbox, ignore_errors=True)

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
