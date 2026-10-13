"""M-02 文件监听：watchfiles 抖动合并 → 触发串行快照（§7.2）。

监听只产生提示，不承担「是否真的变了」的判定；真正的变化比较与提交由
``SnapshotEngine`` 的全量扫描负责兜底（防止监听丢失事件）。
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from collections.abc import Callable

from watchfiles import awatch

from ..core.errors import SkillForgeVMError
from ..core.types import DEBOUNCE_MS
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
        capture: Callable[[], object] | None = None,
    ) -> None:
        self._engine = engine
        self._debounce_ms = debounce_ms
        self._step_ms = step_ms
        self._capture = capture or engine.capture

    async def run(self, stop_event: threading.Event | None = None) -> None:
        """持续监听直到 ``stop_event`` 置位。"""
        root = str(self._engine.handle.config.root_path)
        stop_event = stop_event or threading.Event()
        # 启动扫描兜底：补上服务启动/监听未就绪期间发生的变化（设计 §3.2 M-02）。
        # 无变化时 capture 为零写入，不违反 NFR-01。
        self._capture_safely(root)
        while not stop_event.is_set():
            try:
                async for _changes in awatch(
                    root,
                    debounce=max(2000, self._debounce_ms),
                    step=self._debounce_ms,
                    rust_timeout=2000,
                    yield_on_timeout=True,
                    watch_filter=None,
                    stop_event=stop_event,
                ):
                    self._capture_safely(root)
            except (OSError, RuntimeError) as exc:
                logger.error("文件监听不可用，等待目录恢复后重试：%s：%s", root, exc)
                await asyncio.to_thread(stop_event.wait, 1.0)

    def _capture_safely(self, root: str) -> None:
        try:
            self._capture()
        except (SkillForgeVMError, OSError, sqlite3.Error) as exc:
            logger.error("快照失败，保留已提交状态并在下一轮重试：%s：%s", root, exc)

    def start_background(self) -> tuple[threading.Thread, threading.Event]:
        """在独立线程中运行监听，返回线程与停止事件（供服务在后台调用）。"""
        stop_event = threading.Event()

        def _run() -> None:
            asyncio.run(self.run(stop_event=stop_event))

        thread = threading.Thread(target=_run, name="skillforge-watch", daemon=True)
        thread.start()
        return thread, stop_event
