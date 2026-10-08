"""M-02 快照执行器：稳定扫描 → 写入不可变对象 → 单一事务提交 Revision/Change。

边界（§4.1 / §7.2）：
- 同一工作区同一时刻只有一个快照提交（工作区级互斥），绝不并行写。
- 原始 tree 与当前已提交状态相同 → 不写对象、不建修订、不分配 seq（零写入）。
- 对象已落盘但事务失败时，允许留下未引用对象供重试，绝不发布半提交状态。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..core.errors import SnapshotUnstableError
from ..core.types import (
    CHANGE_IDLE_MINUTES,
    SCAN_ATTEMPTS,
    SnapshotSource,
    SnapshotTrigger,
)
from ..db.connection import connect, transaction
from ..objectstore.index import ObjectIndex
from ..objectstore.store import DirectoryWriteResult, ObjectStore
from ..revision.identity import new_change_id, revision_meta_payload
from ..revision.models import Revision
from ..revision.store import RevisionStore
from ..workspace.manager import WorkspaceHandle
from .scanner import scan_files

# 工作区级互斥：同一进程内保证单一写通道（EDGE-15）。
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(workspace_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(workspace_id, threading.Lock())


@dataclass(frozen=True)
class SnapshotResult:
    """一次快照请求的结果。``created=False`` 表示内容与当前修订相同。"""

    revision: Revision
    created: bool


class SnapshotEngine:
    """把一个工作区的「已提交状态」推进到工作区当前内容。"""

    def __init__(
        self,
        handle: WorkspaceHandle,
        *,
        idle_threshold: timedelta = timedelta(minutes=CHANGE_IDLE_MINUTES),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._handle = handle
        self._idle_threshold = idle_threshold
        self._clock = clock
        self._active_change_id: str | None = None
        self._last_commit_at: float | None = None

    @property
    def handle(self) -> WorkspaceHandle:
        return self._handle

    def capture(
        self,
        *,
        trigger: SnapshotTrigger = SnapshotTrigger.WATCH,
        source: SnapshotSource = SnapshotSource.EDIT,
    ) -> SnapshotResult:
        """串行捕获一次快照；无变化时返回当前修订且不写任何业务元数据。"""
        ws_id = self._handle.workspace_id
        with _lock_for(ws_id):
            return self._capture(ws_id, trigger, source)

    def end_active_change(self) -> None:
        """显式边界（打锚点 / 撤销）后，下次内容变化另起 Change（§7.2）。"""
        self._active_change_id = None

    def _capture(
        self,
        ws_id: str,
        trigger: SnapshotTrigger,
        source: SnapshotSource,
    ) -> SnapshotResult:
        root = Path(self._handle.config.root_path)
        ignore = self._handle.config.ignore.ignores
        store = ObjectStore(self._handle.paths.objects_dir)
        written = self._stable_write(store, root, ignore)

        conn = connect(self._handle.paths.db_file)
        try:
            revisions = RevisionStore(conn)
            head = revisions.head(ws_id)
            if head is not None and head.root_tree_oid == written.root.oid:
                return SnapshotResult(revision=head, created=False)

            seq = 1 if head is None else head.seq + 1
            parent_rev_id = None if head is None else head.rev_id
            ts = _now_iso()
            change_id = self._next_change_id()
            meta = store.write_meta(
                revision_meta_payload(
                    ws_id=ws_id,
                    change_id=change_id,
                    parent_rev_id=parent_rev_id,
                    root_tree_oid=written.root.oid,
                    trigger=trigger,
                    source=source,
                    ts=ts,
                    seq=seq,
                )
            )
            revision = Revision(
                rev_id=meta.oid,
                ws_id=ws_id,
                change_id=change_id,
                parent_rev_id=parent_rev_id,
                root_tree_oid=written.root.oid,
                trigger=SnapshotTrigger(trigger).value,
                source=SnapshotSource(source).value,
                ts=ts,
                seq=seq,
            )

            with transaction(conn):
                index = ObjectIndex(conn)
                index.record_many(written.records)
                index.record(meta)
                revisions.insert(revision)
                if revisions.get_change(ws_id, change_id) is None:
                    revisions.start_change(ws_id, change_id, revision.rev_id)
                else:
                    revisions.extend_change(ws_id, change_id, revision.rev_id)
                revisions.index_paths(revision.rev_id, written.files)

            self._active_change_id = change_id
            self._last_commit_at = self._clock()
            return SnapshotResult(revision=revision, created=True)
        finally:
            conn.close()

    def _stable_write(
        self,
        store: ObjectStore,
        root: Path,
        ignore: Callable[[Path], bool] | None,
    ) -> DirectoryWriteResult:
        """写入对象树；读取期间工作区变化则重试，连续不稳定明确报错（§7.2）。"""
        before = scan_files(root, ignore)
        for _ in range(SCAN_ATTEMPTS):
            try:
                written = store.write_directory_detailed(root, ignore)
                after = scan_files(root, ignore)
            except OSError:
                # 读取途中文件被删除/替换：以最新清单为基线重试。
                before = scan_files(root, ignore)
                continue
            if before == after:
                return written
            before = after
        raise SnapshotUnstableError("工作区持续变化，无法捕获稳定内容，可重试", detail=str(root))

    def _next_change_id(self) -> str:
        """延续还是新开 Change：同进程内空闲未满阈值则延续（§7.2）。"""
        if self._active_change_id is not None and self._last_commit_at is not None:
            idle = self._clock() - self._last_commit_at
            if idle < self._idle_threshold.total_seconds():
                return self._active_change_id
        return new_change_id()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
