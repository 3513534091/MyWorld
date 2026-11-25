"""进程内事件总线。

一个发布者（后端任务）→ 多个订阅者（浏览器里的 WebSocket 连接）。
后续加节点执行、任务进度时，只要往这里 publish，前端就能实时收到。
"""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

# 单个订阅者最多积压多少条事件；超过就丢最旧的一条，避免慢客户端拖垮服务
QUEUE_SIZE = 256


class EventBus:
    def __init__(self, queue_size: int = QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._ids = itertools.count(1)
        self._published = 0

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    @property
    def published(self) -> int:
        return self._published

    def subscribe(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        token = next(self._ids)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers[token] = queue
        return token, queue

    def unsubscribe(self, token: int) -> None:
        self._subscribers.pop(token, None)

    def publish(self, event: dict[str, Any]) -> int:
        """广播一条事件，返回成功送达的订阅者数量。"""
        payload = {"ts": time.time(), **event}
        delivered = 0
        for queue in list(self._subscribers.values()):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - 理论上不会发生
                    pass
            try:
                queue.put_nowait(payload)
                delivered += 1
            except asyncio.QueueFull:  # pragma: no cover
                pass
        self._published += 1
        return delivered
