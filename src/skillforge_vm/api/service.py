"""M-10 接口层的服务门面：把路由请求映射到 M-01/M-02/M-04/M-09 的公开入口。

接口层不直读数据库以外的模块私有实现；业务读写都通过各模块的公开类型与 store。
工作区级快照引擎在此按工作区缓存，保证 Change 分组状态在服务进程内延续（§7.2）。
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

from ..core.errors import (
    InvalidRequestError,
    RefNotFoundError,
    RestoreConflictError,
    RestorePendingError,
    RevisionNotFoundError,
)
from ..core.locking import DataRootLock, SerialGate
from ..core.types import ObjectType, SnapshotSource, SnapshotTrigger
from ..db.connection import connect, transaction
from ..diff import Layer
from ..diff.text import line_counts, unified_patch
from ..objectstore.objects import object_id
from ..objectstore.store import ObjectStore
from ..oplog.models import OpKind
from ..oplog.restore import RestoreExecutor
from ..oplog.restore_models import RestorePlan
from ..oplog.store import OpStore
from ..report import build_report
from ..revision.content import read_revision_file
from ..revision.models import Ref
from ..revision.revset import resolve_revset
from ..revision.store import RESERVED_REF_NAMES, RevisionStore
from ..watcher.engine import SnapshotEngine
from ..watcher.scanner import scan_files
from ..watcher.watcher import WorkspaceWatcher
from ..workspace.manager import WorkspaceHandle, WorkspaceManager
from .events import EVENT_SNAPSHOT_CREATED, EventBus


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._writes:
            return method(self, *args, **kwargs)

    return call


def _workspace_info(handle: WorkspaceHandle) -> dict[str, Any]:
    return {
        "workspace_id": handle.workspace_id,
        "name": handle.config.name,
        "root_path": handle.config.root_path,
        "created_at": handle.config.created_at,
        "tool_version": handle.config.tool_version,
    }


class WorkspaceService:
    """供路由调用的一层薄服务；不掺 HTTP 细节，只返回纯数据。"""

    def __init__(
        self,
        manager: WorkspaceManager | None = None,
        *,
        bus: EventBus | None = None,
    ) -> None:
        self._manager = manager or WorkspaceManager()
        self._bus = bus or EventBus()
        self._engines: dict[str, SnapshotEngine] = {}
        self._guard = threading.Lock()
        self._writes = SerialGate()
        self._watchers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._running = False
        self._root_lock = DataRootLock(self._manager.data_root)

    def start(self) -> None:
        with self._writes:
            if self._running:
                return
            self._root_lock.acquire()
            self._running = True
            for handle in self._manager.list():
                self._start_watcher(handle)

    def stop(self) -> None:
        with self._writes:
            self._running = False
            watchers = list(self._watchers.values())
            self._watchers.clear()
            for _, stop in watchers:
                stop.set()
        for thread, _ in watchers:
            thread.join()
        self._root_lock.release()

    def _start_watcher(self, handle: WorkspaceHandle) -> None:
        ws_id = handle.workspace_id
        if self._running and ws_id not in self._watchers:
            watcher = WorkspaceWatcher(
                self._engine(handle),
                capture=lambda: self.snapshot(ws_id, trigger=SnapshotTrigger.WATCH),
            )
            self._watchers[ws_id] = watcher.start_background()

    @property
    def manager(self) -> WorkspaceManager:
        return self._manager

    @property
    def bus(self) -> EventBus:
        return self._bus

    def _handle(self, ws_id: str) -> WorkspaceHandle:
        return self._manager.get(ws_id)

    def _engine(self, handle: WorkspaceHandle) -> SnapshotEngine:
        with self._guard:
            engine = self._engines.get(handle.workspace_id)
            if engine is None:
                engine = SnapshotEngine(handle)
                self._engines[handle.workspace_id] = engine
            else:
                engine.use_config(handle)
            return engine

    # ---- 工作区 ----

    @_serialized
    def init(self, path: str, name: str | None = None) -> dict[str, Any]:
        result = self._manager.init(path, name)
        self._start_watcher(result.workspace)
        self._publish(
            {
                "type": EVENT_SNAPSHOT_CREATED,
                "workspace_id": result.workspace.workspace_id,
                "revision_id": result.revision_id,
                "seq": 1,
            }
        )
        return {
            "workspace": _workspace_info(result.workspace),
            "root_tree_oid": result.root_tree_oid,
            "revision_id": result.revision_id,
            "change_id": result.change_id,
            "file_count": result.file_count,
            "object_count": result.object_count,
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [_workspace_info(handle) for handle in self._manager.list()]

    def get_workspace(self, ws_id: str) -> dict[str, Any]:
        return _workspace_info(self._handle(ws_id))

    def status(self, ws_id: str) -> dict[str, Any]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            head = RevisionStore(conn).head(ws_id)
            pending_restore = OpStore(conn).pending_restore(ws_id)
        finally:
            conn.close()
        pending = self._has_pending(handle, head)
        return {
            "workspace_id": ws_id,
            "initialized": True,
            "head_revision": None if head is None else head.rev_id,
            "head_seq": None if head is None else head.seq,
            "change_id": None if head is None else head.change_id,
            "has_pending_changes": pending,
            "pending_restore": pending_restore,
            "baseline_revision": self._baseline(ws_id),
        }

    def _baseline(self, ws_id: str) -> str | None:
        conn = connect(self._handle(ws_id).paths.db_file)
        try:
            try:
                return RevisionStore(conn).get_ref(ws_id, "baseline").rev_id
            except RefNotFoundError:
                return None
        finally:
            conn.close()

    def _has_pending(self, handle: WorkspaceHandle, head: Any) -> bool:
        """只读判定「当前原始树是否与已提交 head 相同」，不写任何对象/元数据。"""
        current = self._current_files(handle)
        if current is None:
            return True  # 扫描途中出错：保守地视为有待处理，绝不谎报「已是最新」
        if head is None:
            return bool(current)
        committed = self._committed_files(handle, head.rev_id)
        return current != committed

    def _current_files(self, handle: WorkspaceHandle) -> dict[str, tuple[str, str]] | None:
        root = Path(handle.config.root_path)
        ignore = handle.config.ignore.ignores
        try:
            entries = scan_files(root, ignore)
            result: dict[str, tuple[str, str]] = {}
            for entry in entries:
                data = (root / entry.rel_path).read_bytes()
                result[entry.rel_path] = (object_id(ObjectType.BLOB, data), entry.mode)
        except OSError:
            return None
        return result

    def _committed_files(self, handle: WorkspaceHandle, rev_id: str) -> dict[str, tuple[str, str]]:
        conn = connect(handle.paths.db_file)
        try:
            return RevisionStore(conn).files(rev_id)
        finally:
            conn.close()

    # ---- 快照 ----

    @_serialized
    def snapshot(
        self,
        ws_id: str,
        message: str | None = None,
        *,
        trigger: SnapshotTrigger = SnapshotTrigger.MANUAL,
    ) -> dict[str, Any]:
        handle = self._handle(ws_id)
        result = self._engine(handle).capture(
            trigger=trigger, source=SnapshotSource.EDIT, message=message
        )
        if result.created:
            self._publish(
                {
                    "type": EVENT_SNAPSHOT_CREATED,
                    "workspace_id": ws_id,
                    "revision_id": result.revision.rev_id,
                    "seq": result.revision.seq,
                }
            )
        return {"created": result.created, "revision": result.revision.model_dump()}

    # ---- 修订 / 变更 ----

    def _restore_executor(self, ws_id: str) -> RestoreExecutor:
        handle = self._handle(ws_id)
        return RestoreExecutor(handle, self._engine(handle))

    @staticmethod
    def _plan_data(plan: RestorePlan | None) -> dict[str, Any]:
        if plan is None:
            return {"no_change": True, "plan_id": None, "changes": []}
        return {
            "no_change": False,
            "plan_id": plan.plan_id,
            "before_rev": plan.before_rev,
            "target_rev": plan.target_rev,
            "action": plan.action,
            "changes": plan.changes(),
        }

    @_serialized
    def preview_restore(self, ws_id: str, rev: str) -> dict[str, Any]:
        before = self.snapshot(ws_id)["revision"]["rev_id"]
        target = self.get_revision(ws_id, rev)["rev_id"]
        return self._plan_data(self._restore_executor(ws_id).preview(before, target))

    @_serialized
    def preview_undo(self, ws_id: str) -> dict[str, Any]:
        before = self.snapshot(ws_id)["revision"]["rev_id"]
        conn = connect(self._handle(ws_id).paths.db_file)
        try:
            done = OpStore(conn).latest_restore(ws_id, completed=True)
        finally:
            conn.close()
        if done is None:
            raise RestoreConflictError("没有可撤销的文件恢复")
        payload = json.loads(done.payload_json)
        if before != payload["after_rev"]:
            raise RestoreConflictError("恢复后已有新改动，请显式选择历史修订进行 restore")
        return self._plan_data(
            self._restore_executor(ws_id).preview(
                before, payload["before_rev"], action="undo_restore"
            )
        )

    def get_restore_plan(self, ws_id: str, plan_id: str) -> dict[str, Any]:
        return self._plan_data(self._restore_executor(ws_id).load(plan_id))

    @_serialized
    def apply_restore(self, ws_id: str, plan_id: str, *, confirm: bool) -> dict[str, Any]:
        if confirm is not True:
            raise InvalidRequestError("文件恢复必须显式确认 confirm=true")
        result = self._restore_executor(ws_id).apply(plan_id)
        if result.created:
            self._publish(
                {
                    "type": EVENT_SNAPSHOT_CREATED,
                    "workspace_id": ws_id,
                    "revision_id": result.revision.rev_id,
                    "seq": result.revision.seq,
                }
            )
        return {
            "plan_id": plan_id,
            "created": result.created,
            "revision": result.revision.model_dump(),
        }

    def list_revisions(
        self, ws_id: str, *, limit: int | None = None, max_seq: int | None = None
    ) -> list[dict[str, Any]]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            revisions = RevisionStore(conn).list(ws_id, max_seq=max_seq, limit=limit)
        finally:
            conn.close()
        return [revision.model_dump() for revision in revisions]

    def get_revision(self, ws_id: str, spec: str) -> dict[str, Any]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            store = RevisionStore(conn)
            head = store.head(ws_id)
            rev_id = resolve_revset(
                spec, store=store, ws_id=ws_id, current=None if head is None else head.rev_id
            )
            revision = store.get(ws_id, rev_id)
        finally:
            conn.close()
        return revision.model_dump()

    def list_changes(self, ws_id: str) -> list[dict[str, Any]]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            changes = RevisionStore(conn).list_changes(ws_id)
        finally:
            conn.close()
        return [change.model_dump() for change in changes]

    # ---- 引用 / 锚点 ----

    @_serialized
    def set_ref(self, ws_id: str, name: str, rev_spec: str | None = None) -> dict[str, Any]:
        if not name.strip() or name in RESERVED_REF_NAMES:
            raise InvalidRequestError(f"引用名为空或为只读别名：{name}", detail=name)
        handle = self._handle(ws_id)
        if rev_spec is None or rev_spec.split("~", 1)[0] == "@":
            self.snapshot(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            store = RevisionStore(conn)
            head = store.head(ws_id)
            current = None if head is None else head.rev_id
            if pending := OpStore(conn).pending_restore(ws_id):
                raise RestorePendingError("请先继续未完成的恢复", detail=pending)
            if rev_spec is None:
                if head is None:
                    raise RevisionNotFoundError("工作区还没有任何修订，无法打锚点", detail=ws_id)
                target = head.rev_id
            else:
                target = resolve_revset(rev_spec, store=store, ws_id=ws_id, current=current)
            before: str | None
            try:
                before = store.get_ref(ws_id, name).rev_id
            except RefNotFoundError:
                before = None
            ref = Ref(name=name, ws_id=ws_id, rev_id=target, updated_at=_now_iso())
            with transaction(conn):
                store.set_ref(ref)  # 保留名（last）在此报 invalid_request
                store.set_baseline(ws_id, target, ref.updated_at)
                OpStore(conn).record(
                    ws_id=ws_id,
                    kind=OpKind.REF_SET,
                    payload={"name": name, "before_rev_id": before, "after_rev_id": target},
                )
        finally:
            conn.close()
        # 打锚点是 Change 边界：下次内容变化另起 Change（§7.2）。
        self._engine(handle).end_active_change()
        return ref.model_dump()

    def list_refs(self, ws_id: str) -> list[dict[str, Any]]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            store = RevisionStore(conn)
            refs = [ref.model_dump() for ref in store.list_refs(ws_id) if ref.name != "baseline"]
            head = store.head(ws_id)
        finally:
            conn.close()
        if head is not None:
            refs.append(
                {
                    "name": "last",
                    "ws_id": ws_id,
                    "rev_id": head.rev_id,
                    "updated_at": head.ts,
                    "readonly": True,
                }
            )
        return refs

    def diff(
        self,
        ws_id: str,
        *,
        base: str | None = None,
        head: str | None = None,
        layer: str = "L3",
    ) -> dict[str, Any]:
        handle = self._handle(ws_id)
        try:
            requested = Layer(layer.upper())
        except ValueError as exc:
            raise InvalidRequestError(f"不支持的对比层级：{layer}") from exc
        if base == "" or head == "":
            raise InvalidRequestError("显式引用不能为空")
        conn = connect(handle.paths.db_file)
        try:
            store = RevisionStore(conn)
            current = store.head(ws_id)
            if current is None:
                raise RevisionNotFoundError("工作区还没有任何修订", detail=ws_id)
            if head is None and self._has_pending(handle, current):
                from ..core.errors import SnapshotUnstableError

                raise SnapshotUnstableError("文件修改尚未形成快照，请等待后重试")
            head_rev = store.get(
                ws_id,
                current.rev_id
                if head is None
                else resolve_revset(
                    head,
                    store=store,
                    ws_id=ws_id,
                    current=current.rev_id,
                ),
            )
            base_id = (
                head_rev.parent_rev_id
                if base is None
                else resolve_revset(
                    base,
                    store=store,
                    ws_id=ws_id,
                    current=current.rev_id,
                )
            )
            base_rev = None if base_id is None else store.get(ws_id, base_id)
            report, created = build_report(
                conn,
                ObjectStore(handle.paths.objects_dir),
                ws_id=ws_id,
                base=base_rev,
                head=head_rev,
                base_files={} if base_rev is None else store.files(base_rev.rev_id),
                head_files=store.files(head_rev.rev_id),
                layer=requested,
                analysis_config={
                    "max_text_bytes": handle.config.ignore.max_text_bytes,
                    "parsers": handle.config.parsers.model_dump(mode="json"),
                    "semantic_unit_extensions": handle.config.semantic_unit_extensions,
                },
                max_text_bytes=handle.config.ignore.max_text_bytes,
            )
        finally:
            conn.close()
        if created:
            self._publish(
                {
                    "type": "diff/ready",
                    "workspace_id": ws_id,
                    "report_id": report["report_id"],
                    "revision_id": head_rev.rev_id,
                }
            )
            for item in report["degraded"]:
                self._publish(
                    {
                        "type": "parse/degraded",
                        "workspace_id": ws_id,
                        "report_id": report["report_id"],
                        "path": item["path"],
                        "reason_code": item["reason_code"],
                    }
                )
        return report

    def file_content(self, ws_id: str, rev: str, path: str) -> dict[str, Any]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            store = RevisionStore(conn)
            current = store.head(ws_id)
            target = resolve_revset(
                rev,
                store=store,
                ws_id=ws_id,
                current=None if current is None else current.rev_id,
            )
            return read_revision_file(
                store,
                ObjectStore(handle.paths.objects_dir),
                ws_id,
                target,
                path,
                max_text_bytes=handle.config.ignore.max_text_bytes,
            )
        finally:
            conn.close()

    def compare(
        self,
        ws_id: str,
        *,
        base: str | None = None,
        head: str | None = None,
        context: int = 3,
        path: str | None = None,
    ) -> dict[str, Any]:
        if not 0 <= context <= 100:
            raise InvalidRequestError("上下文行数应在 0 到 100 之间")
        # L0 只解析固定版本和文件变化，不调用解析器、语义或风险分析。
        metadata = self.diff(ws_id, base=base, head=head, layer="L0")
        files = []
        for item in metadata["layers"]["metadata"]["files"]:
            old_path = item.get("before_path", item["path"])
            if path is not None and path not in (item["path"], old_path):
                continue
            old = (
                {"status": "absent", "text": None, "mode": None}
                if metadata["base"]["rev"] is None
                else self.file_content(ws_id, metadata["base"]["rev"], old_path)
            )
            new = self.file_content(ws_id, metadata["head"]["rev"], item["path"])
            readable = all(side["status"] in ("text", "absent") for side in (old, new))
            before_text, after_text = old["text"] or "", new["text"] or ""
            added, removed = line_counts(before_text, after_text) if readable else (None, None)
            patch = (
                unified_patch(
                    before_text,
                    after_text,
                    "/dev/null" if old["status"] == "absent" else f"a/{old_path}",
                    "/dev/null" if new["status"] == "absent" else f"b/{item['path']}",
                    context,
                )
                if readable
                else None
            )
            files.append(
                {
                    **item,
                    "added": added,
                    "removed": removed,
                    "patch": patch,
                    "before_status": old["status"],
                    "after_status": new["status"],
                    "before_mode": old["mode"],
                    "after_mode": new["mode"],
                }
            )
        return {
            "base": metadata["base"],
            "head": metadata["head"],
            "files": files,
            "context": context,
            "algorithm": "text-unified-v1",
            "added": sum(f["added"] or 0 for f in files),
            "removed": sum(f["removed"] or 0 for f in files),
        }

    def diff_summary(
        self, ws_id: str, *, base: str | None = None, head: str | None = None
    ) -> dict[str, Any]:
        report = self.diff(ws_id, base=base, head=head)
        return {key: report[key] for key in ("report_id", "base", "head", "summary", "overview")}

    # ---- 操作日志 ----

    def list_ops(self, ws_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        handle = self._handle(ws_id)
        conn = connect(handle.paths.db_file)
        try:
            ops = OpStore(conn).list(ws_id, limit=limit)
        finally:
            conn.close()
        return [op.model_dump() for op in ops]

    def _publish(self, event: dict[str, Any]) -> None:
        self._bus.publish(event)
