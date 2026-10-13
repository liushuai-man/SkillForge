"""M-10 提交后事件流（SSE）的进程内广播（设计 §4.6 / 契约 §4.3）。

事件只是通知，数据库与状态接口才是真值；不承诺历史重放或恰好一次，
断线重连由客户端重取状态。本模块只做单进程内发布/订阅。
"""

from __future__ import annotations

import asyncio
from typing import Any

# 事件类型：MVP 落地 snapshot/created；diff/ready、parse/degraded 待 M-05 接入后补。
EVENT_SNAPSHOT_CREATED = "snapshot/created"


class EventBus:
    """单进程广播：发布方可能来自线程池，订阅方是 asyncio 队列。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """在异步端点内订阅；顺带绑定当前事件循环。"""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - 只可能在无循环的同步上下文调用
            self._loop = None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        """发布事件；线程安全地投递到已订阅队列。"""
        for queue in list(self._subscribers):
            if self._loop is not None:
                self._loop.call_soon_threadsafe(queue.put_nowait, event)
            else:  # pragma: no cover - 无订阅者时无需投递
                queue.put_nowait(event)