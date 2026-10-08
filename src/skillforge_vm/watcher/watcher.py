"""M-02 文件监听：watchfiles 抖动合并 → 触发串行快照（§7.2）。

监听只产生提示，不承担「是否真的变了」的判定；真正的变化比较与提交由
``SnapshotEngine`` 的全量扫描负责兜底（防止监听丢失事件）。
"""

from __future__ import annotations

import asyncio
import logging
import threading

from watchfiles import awatch

from ..core.errors import SnapshotUnstableError
from ..core.types import DEBOUNCE_MS, SnapshotSource, SnapshotTrigger
from .engine import SnapshotEngine

logger = logging.getLogger(__name__)


class WorkspaceWatcher:
    """把一个工作区的保存事件合并成快照请求（最后事件后静默 ``debounce_ms`` 才触发）。"""

    def __init__(
        self,
        engine: SnapshotEngine,
        *,
        debounce_ms: int = DEBOUNCE_MS,
        step_ms: int = 50,
    ) -> None:
        self._engine = engine
        self._debounce_ms = debounce_ms
        self._step_ms = step_ms

    async def run(self, stop_event: threading.Event | None = None) -> None:
        """持续监听直到 ``stop_event`` 置位。"""
        root = str(self._engine.handle.config.root_path)
        # 启动扫描兜底：补上服务启动/监听未就绪期间发生的变化（设计 §3.2 M-02）。
        # 无变化时 capture 为零写入，不违反 NFR-01。
        self._capture_safely(root)
        async for _changes in awatch(
            root,
            debounce=self._debounce_ms,
            step=self._step_ms,
            stop_event=stop_event,
        ):
            self._capture_safely(root)

    def _capture_safely(self, root: str) -> None:
        try:
            self._engine.capture(trigger=SnapshotTrigger.WATCH, source=SnapshotSource.EDIT)
        except SnapshotUnstableError:
            logger.warning("工作区持续变化，本轮快照跳过：%s", root)

    def start_background(self) -> tuple[threading.Thread, threading.Event]:
        """在独立线程中运行监听，返回线程与停止事件（供服务在后台调用）。"""
        stop_event = threading.Event()

        def _run() -> None:
            asyncio.run(self.run(stop_event=stop_event))

        thread = threading.Thread(target=_run, name="skillforge-watch", daemon=True)
        thread.start()
        return thread, stop_event
