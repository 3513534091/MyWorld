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

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, characters, presets, worlds
from .config import Settings
from .events import EventBus

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DEFAULT_WORLD_THUMBS = {
    "dark": WEB_DIR / "img" / "world-default.svg",
    "light": WEB_DIR / "img" / "world-default-light.svg",
}
DEFAULT_CHARACTER_PORTRAITS = {
    "dark": WEB_DIR / "img" / "character-default.svg",
    "light": WEB_DIR / "img" / "character-default-light.svg",
}
logger = logging.getLogger("myworld")

# 允许上传的封面类型 → 落盘扩展名
ALLOWED_THUMB_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_THUMB_BYTES = 5 * 1024 * 1024


class NameRequest(BaseModel):
    """POST /api/worlds 与 /api/presets 的请求体。"""

    name: str = ""


class OrderRequest(BaseModel):
    """PUT /api/worlds/{世界}/characters/order 的请求体。"""

    names: list[str] = []


class CharacterUpdateRequest(BaseModel):
    """PATCH 角色：改姓名 / 改属性。"""

    name: str | None = None
    attributes: list[Any] | None = None


class PresetRequest(BaseModel):
    """POST / PATCH /api/presets：名字 + 属性名列表（只有键，没有值）。"""

    name: str = ""
    keys: list[Any] | None = None


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

    @app.middleware("http")
    async def _no_stale_assets(request, call_next):
        """本地程序的静态资源一律不缓存。

        否则改了 HTML/JS 之后浏览器可能新旧混用：新脚本绑不到旧页面上的元素，
        初始化就抛错，表现成「缩略图没了、按钮点了没反应」。
        """
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".js", ".css", ".html", ".svg")):
            response.headers["Cache-Control"] = "no-store"
        return response

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
    async def api_create_world(payload: NameRequest) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            created = worlds.create_world(root, payload.name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("创建世界「%s」→ %s", created["name"], created["path"])
        return created

    @app.delete("/api/worlds/{name}", summary="删除世界")
    async def api_delete_world(name: str) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            result = worlds.delete_world(root, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("删除世界「%s」", result["name"])
        return result

    @app.get("/api/worlds/{world}/characters", summary="列出世界里的角色")
    async def api_characters(world: str) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            items = characters.list_characters(root, world)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        return {"world": world, "items": items}

    @app.post("/api/worlds/{world}/characters", summary="新建角色", status_code=201)
    async def api_create_character(world: str, payload: NameRequest) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            created = characters.create_character(root, world, payload.name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("新建角色「%s」→ %s", created["name"], created["path"])
        return created

    @app.get("/api/worlds/{world}/characters/{name}/portrait", summary="角色立绘（没有则用默认图）")
    async def api_character_portrait(world: str, name: str, theme: str = "dark") -> FileResponse:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            found = characters.find_portrait(root, world, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

        # 立绘/封面会被就地替换，绝对不能让浏览器拿缓存（否则换完还显示旧图）
        headers = {"Cache-Control": "no-store"}
        if found is None:
            default = DEFAULT_CHARACTER_PORTRAITS.get(theme, DEFAULT_CHARACTER_PORTRAITS["dark"])
            if not default.is_file():
                raise HTTPException(status_code=500, detail="默认角色图片缺失")
            return FileResponse(default, media_type="image/svg+xml", headers=headers)
        return FileResponse(found, headers=headers)

    @app.post("/api/worlds/{world}/characters/{name}/portrait", summary="上传角色立绘")
    async def api_upload_portrait(world: str, name: str, request: Request) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)

        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        ext = ALLOWED_THUMB_TYPES.get(content_type)
        if ext is None:
            raise HTTPException(status_code=400, detail="只支持 PNG / JPEG / WebP 图片")

        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="图片内容为空")
        if len(data) > MAX_THUMB_BYTES:
            limit_mb = MAX_THUMB_BYTES // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"图片太大（上限 {limit_mb} MB）")

        try:
            target = characters.save_portrait(root, world, name, data, ext)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"保存失败：{exc}") from exc

        logger.info("更新角色立绘「%s/%s」→ %s（%.1f KB）", world, name, target.name, len(data) / 1024)
        return {"world": world, "name": name, "portrait": target.name, "bytes": len(data)}

    @app.put("/api/worlds/{world}/characters/order", summary="保存角色显示顺序")
    async def api_character_order(world: str, payload: OrderRequest) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            result = characters.save_order(root, world, payload.names)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("保存角色顺序「%s」：%s", world, " / ".join(result["order"]))
        return result

    @app.get("/api/worlds/{world}/characters/{name}", summary="角色详情")
    async def api_character_detail(world: str, name: str) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            return characters.read_character(root, world, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    @app.patch("/api/worlds/{world}/characters/{name}", summary="修改角色（姓名 / 属性）")
    async def api_update_character(world: str, name: str, payload: CharacterUpdateRequest) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            updated = characters.update_character(
                root,
                world,
                name,
                new_name=payload.name,
                attributes=payload.attributes,
            )
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info(
            "更新角色「%s/%s」→ %s（属性 %d 条）",
            world,
            name,
            updated["name"],
            len(updated["attributes"]),
        )
        return updated

    @app.delete("/api/worlds/{world}/characters/{name}/portrait", summary="恢复默认立绘")
    async def api_delete_portrait(world: str, name: str) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            result = characters.delete_portrait(root, world, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("恢复默认立绘「%s/%s」（删除 %d 个文件）", world, name, len(result["removed"]))
        return result

    @app.delete("/api/worlds/{world}/characters/{name}", summary="删除角色")
    async def api_delete_character(world: str, name: str) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            result = characters.delete_character(root, world, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("删除角色「%s/%s」", world, result["name"])
        return result

    @app.get("/api/presets", summary="列出所有预设")
    async def api_presets() -> dict[str, Any]:
        root = presets.resolve_root(worlds.resolve_root(runtime.settings.data_dir))
        return {"root": str(root), "items": presets.list_presets(root)}

    @app.post("/api/presets", summary="创建新预设", status_code=201)
    async def api_create_preset(payload: PresetRequest) -> dict[str, Any]:
        root = presets.resolve_root(worlds.resolve_root(runtime.settings.data_dir))
        try:
            created = presets.create_preset(root, payload.name, payload.keys)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info(
            "创建预设「%s」→ %s（%d 个属性名）",
            created["name"],
            created["path"],
            len(created["keys"]),
        )
        return created

    @app.patch("/api/presets/{name}", summary="修改预设（名字 / 属性）")
    async def api_update_preset(name: str, payload: PresetRequest) -> dict[str, Any]:
        root = presets.resolve_root(worlds.resolve_root(runtime.settings.data_dir))
        try:
            updated = presets.update_preset(
                root,
                name,
                new_name=payload.name or None,
                keys=payload.keys,
            )
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info(
            "更新预设「%s」→ %s（%d 个属性名）",
            name,
            updated["name"],
            len(updated["keys"]),
        )
        return updated

    @app.delete("/api/presets/{name}", summary="删除预设")
    async def api_delete_preset(name: str) -> dict[str, Any]:
        root = presets.resolve_root(worlds.resolve_root(runtime.settings.data_dir))
        try:
            result = presets.delete_preset(root, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        logger.info("删除预设「%s」", result["name"])
        return result

    @app.post("/api/worlds/{name}/thumbnail", summary="上传（裁剪后的）世界封面")
    async def api_upload_thumbnail(name: str, request: Request) -> dict[str, Any]:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            directory = worlds.world_dir(root, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        ext = ALLOWED_THUMB_TYPES.get(content_type)
        if ext is None:
            raise HTTPException(status_code=400, detail="只支持 PNG / JPEG / WebP 图片")

        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="图片内容为空")
        if len(data) > MAX_THUMB_BYTES:
            limit_mb = MAX_THUMB_BYTES // (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"图片太大（上限 {limit_mb} MB）")

        # 旧的几种扩展名都清掉，避免同一世界有多张封面
        for existing in worlds.THUMB_FILENAMES:
            (directory / existing).unlink(missing_ok=True)

        target = directory / f"thumbnail{ext}"
        target.write_bytes(data)
        logger.info("更新世界封面「%s」→ %s（%.1f KB）", name, target.name, len(data) / 1024)
        return {"name": name, "thumbnail": target.name, "bytes": len(data)}

    @app.get("/api/worlds/{name}/thumbnail", summary="世界缩略图（没有则用默认图）")
    async def api_world_thumbnail(name: str, theme: str = "dark") -> FileResponse:
        root = worlds.resolve_root(runtime.settings.data_dir)
        try:
            thumb = worlds.find_thumbnail(root, name)
        except worlds.WorldError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

        # 立绘/封面会被就地替换，绝对不能让浏览器拿缓存（否则换完还显示旧图）
        headers = {"Cache-Control": "no-store"}
        if thumb is None:
            # 默认图分深浅两版，跟着页面主题走
            default = DEFAULT_WORLD_THUMBS.get(theme, DEFAULT_WORLD_THUMBS["dark"])
            if not default.is_file():
                raise HTTPException(status_code=500, detail="默认世界图片缺失")
            return FileResponse(default, media_type="image/svg+xml", headers=headers)
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
