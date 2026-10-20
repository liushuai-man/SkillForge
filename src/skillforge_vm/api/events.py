"""M-10 提交后事件流（SSE）的进程内广播（设计 §4.6 / 契约 §4.3）。

事件只是通知，数据库与状态接口才是真值；不承诺历史重放或恰好一次，
断线重连由客户端重取状态。本模块只做单进程内发布/订阅。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

EVENT_SNAPSHOT_CREATED = "snapshot/created"
EVENT_DIFF_READY = "diff/ready"
EVENT_PARSE_DEGRADED = "parse/degraded"


class EventBus:
    """单进程广播：发布方可能来自线程池，订阅方是 asyncio 队列。"""

    def __init__(self) -> None:
        self._subscribers: dict[
            asyncio.Queue[dict[str, Any]], tuple[asyncio.AbstractEventLoop, str | None]
        ] = {}
        self._guard = threading.Lock()

    def subscribe(self, workspace_id: str | None = None) -> asyncio.Queue[dict[str, Any]]:
        """在异步端点内订阅；顺带绑定当前事件循环。"""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
        with self._guard:
            self._subscribers[queue] = (loop, workspace_id)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._guard:
            self._subscribers.pop(queue, None)

    def publish(self, event: dict[str, Any]) -> None:
        """发布事件；线程安全地投递到已订阅队列。"""
        with self._guard:
            subscribers = list(self._subscribers.items())
        for queue, (loop, workspace_id) in subscribers:
            if workspace_id is not None and event.get("workspace_id") != workspace_id:
                continue
            try:
                loop.call_soon_threadsafe(self._deliver, queue, dict(event))
            except RuntimeError:
                self.unsubscribe(queue)  # 已关闭的消费循环不影响业务提交

    def _deliver(self, queue: asyncio.Queue, event: dict[str, Any]) -> None:
        with self._guard:
            if queue not in self._subscribers:
                return
        if queue.full():
            queue.get_nowait()  # 通知允许丢弃旧项，状态接口始终是真值
        queue.put_nowait(event)
