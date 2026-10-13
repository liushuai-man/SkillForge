"""M-02 文件监听集成用例：真实保存事件 → 抖动合并 → 串行快照。

用真实文件系统与临时数据根；不依赖 mock，也不在真实用户 Skill 上操作。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from skillforge_vm.db.connection import connect
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.watcher.watcher import WorkspaceWatcher
from skillforge_vm.workspace.manager import WorkspaceHandle


def _revision_count(handle: WorkspaceHandle) -> int:
    conn = connect(handle.paths.db_file)
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM revision").fetchone()["n"])
    finally:
        conn.close()


def test_watcher_commits_a_save(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    engine = SnapshotEngine(workspace)
    watcher = WorkspaceWatcher(engine, debounce_ms=100, step_ms=20)
    thread, stop_event = watcher.start_background()
    try:
        (skill_dir / "SKILL.md").write_text("# Watched\n", encoding="utf-8")

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and _revision_count(workspace) < 2:
            time.sleep(0.05)

        assert _revision_count(workspace) >= 2, "监听未在超时前提交快照"
        # 监听已经把当前状态提交；再手动捕获应为零写入
        assert engine.capture().created is False
    finally:
        stop_event.set()
        thread.join(timeout=5)


def test_database_failure_is_reported_and_next_attempt_recovers(workspace, caplog) -> None:
    calls = []

    def capture():
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")

    watcher = WorkspaceWatcher(SnapshotEngine(workspace), capture=capture)
    watcher._capture_safely(workspace.config.root_path)
    watcher._capture_safely(workspace.config.root_path)
    assert len(calls) == 2
    assert "database is locked" in caplog.text
