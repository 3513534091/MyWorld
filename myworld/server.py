"""HTTP + WebSocket 服务。

职责很窄，但都是「网页与本地交互」的地基：
    1. 提供静态前端（web/ 目录）
    2. 提供 REST 状态接口，前端用它显示真实端口、版本、运行时长
    3. 提供 WebSocket 通道（心跳 + 服务端主动推送），后续任务进度走这里
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, worlds
from .config import Settings
from .events import EventBus

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEFAULT_WORLD_THUMB = WEB_DIR / "img" / "world-default.svg"
logger = logging.getLogger("myworld")


class WorldCreateRequest(BaseModel):
    """POST /api/worlds 的请求体。"""

    name: str = ""


def display_host(host: str) -> str:
    """把 0.0.0.0 / :: 这类监听地址换成本机可点的地址。"""
    return "127.0.0.1" if host in {"0.0.0.0", "::", "[::]", ""} else host


class Runtime:
    """一个服务进程的运行时状态（单例，挂在 app.state 上）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()
        self.bus = EventBus()
        self.requests = 0
        self.clients = 0
        self.max_clients = 0

    @property
    def uptime(self) -> float:
        return time.monotonic() - self.started_monotonic

    @property
    def url(self) -> str:
        return f"http://{display_host(self.settings.host)}:{self.settings.port}"

    def status(self) -> dict[str, Any]:
        settings = self.settings
        return {
            "name": "MyWorld",
            "version": __version__,
            "status": "ok",
            "host": settings.host,
            "port": settings.port,
            "requested_port": settings.requested_port,
            "port_shifted": settings.port_shifted,
            "url": self.url,
            "uptime_seconds": round(self.uptime, 3),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.started_at)),
            "pid": os.getpid(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ws_clients": self.clients,
            "ws_max_clients": self.max_clients,
            "events_published": self.bus.published,
            "requests": self.requests,
        }


async def _pump(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """把事件队列里的消息持续推给这个连接。"""
    while True:
        event = await queue.get()
        await websocket.send_json(event)


def create_app(settings: Settings) -> FastAPI:
    runtime = Runtime(settings)

    app = FastAPI(
        title="MyWorld",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.runtime = runtime

    @app.middleware("http")
    async def _count_requests(request, call_next):
        runtime.requests += 1
        return await call_next(request)

    @app.get("/api/status", summary="服务状态")
    async def api_status() -> dict[str, Any]:
        return runtime.status()

    @app.get("/api/config", summary="生效配置与来源")
    async def api_config() -> dict[str, Any]:
        settings_ = runtime.settings
        return {
            **settings_.public_dict(),
            "sources": settings_.sources,
            "web_dir": str(WEB_DIR),
            "web_dir_exists": WEB_DIR.is_dir(),
        }

    @app.get("/api/events", summary="事件总线状态")
    async def api_events() -> dict[str, Any]:
        return {
            "subscribers": runtime.bus.subscribers,
            "published": runtime.bus.published,
        }

    @app.post("/api/demo/tick", summary="向所有已连接页面广播一条 tick")
    async def api_tick() -> dict[str, Any]:
        delivered = runtime.bus.publish({"kind": "tick", "source": "http"})
        logger.info("模拟推送 tick → 送达 %d 个连接", delivered)
        return {"ok": True, "delivered": delivered, "subscribers": runtime.bus.subscribers}

    @app.get("/api/worlds", summary="列出所有世界")
    async def api_worlds() -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        return {"root": str(root), "items": worlds.list_worlds(root)}

    @app.post("/api/worlds", summary="创建新世界", status_code=201)
    async def api_create_world(payload: WorldCreateRequest) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            created = worlds.create_world(root, payload.name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("创建世界「%s」→ %s", created["name"], created["path"])
        return created

    @app.get("/api/worlds/{name}/thumbnail", summary="世界缩略图（没有则用默认图）")
    async def api_world_thumbnail(name: str) -> FileResponse:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            thumb = worlds.find_thumbnail(root, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

        headers = {"Cache-Control": "no-cache"}
        if thumb is None:
            if not DEFAULT_WORLD_THUMB.is_file():
                raise HTTPException(status_code=500, detail="默认世界图片缺失")
            return FileResponse(DEFAULT_WORLD_THUMB, media_type="image/svg+xml", headers=headers)
        return FileResponse(thumb, headers=headers)

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        token, queue = runtime.bus.subscribe()
        runtime.clients += 1
        runtime.max_clients = max(runtime.max_clients, runtime.clients)
        pump_task = asyncio.create_task(_pump(websocket, queue))
        logger.info("页面已连接 · 当前 %d 个客户端", runtime.clients)
        try:
            await websocket.send_json(
                {
                    "kind": "hello",
                    "version": __version__,
                    "port": runtime.settings.port,
                    "pid": os.getpid(),
                    "server_time": time.time(),
                    "uptime_seconds": round(runtime.uptime, 3),
                }
            )
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"kind": "error", "message": f"消息不是合法 JSON：{raw[:80]}"})
                    continue
                if not isinstance(message, dict):
                    await websocket.send_json({"kind": "error", "message": "消息必须是 JSON 对象"})
                    continue

                kind = message.get("type")
                if kind == "ping":
                    logger.debug("心跳 ping t=%s", message.get("t"))
                    await websocket.send_json(
                        {
                            "kind": "pong",
                            "t": message.get("t"),
                            "server_time": time.time(),
                            "uptime_seconds": round(runtime.uptime, 3),
                        }
                    )
                elif kind == "broadcast":
                    payload = message.get("payload")
                    delivered = runtime.bus.publish({"kind": "broadcast", "source": "ws", "payload": payload})
                    logger.info("页面广播 → 送达 %d 个连接", delivered)
                    await websocket.send_json({"kind": "ack", "delivered": delivered})
                elif kind == "stats":
                    await websocket.send_json({"kind": "stats", **runtime.status()})
                else:
                    await websocket.send_json({"kind": "error", "message": f"未知消息类型：{kind!r}"})
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except (asyncio.CancelledError, Exception):
                pass
            runtime.clients -= 1
            runtime.bus.unsubscribe(token)
            logger.info("页面已断开 · 剩余 %d 个客户端", runtime.clients)

    if WEB_DIR.is_dir():
        # 注意：静态挂载放最后，否则会抢走 /api 与 /ws 的匹配
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    else:

        @app.get("/")
        async def web_missing() -> JSONResponse:
            return JSONResponse(
                {"error": f"前端目录缺失：{WEB_DIR}"},
                status_code=500,
            )

    return app
