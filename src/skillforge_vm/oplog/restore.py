"""恢复编排：持久化计划、冲突检查、逐文件回写与原子业务提交。

仅由服务串行通道调用；普通监听从不调用本入口。恢复中断后不自动写文件。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from ..core.errors import RestoreConflictError, RestorePendingError, RestorePlanNotFoundError
from ..core.hashing import sha256_hex
from ..core.paths import is_link_like
from ..core.types import MODE_EXECUTABLE, MODE_REGULAR, ObjectType, SnapshotTrigger
from ..db.connection import connect, transaction
from ..objectstore.objects import canonical_json, object_id
from ..objectstore.store import ObjectStore
from ..revision.content import read_tree, safe_relative
from ..revision.store import RevisionStore
from ..watcher.engine import SnapshotEngine, SnapshotResult
from ..workspace.manager import WorkspaceHandle
from .models import OpKind
from .restore_models import FileState, RestoreCommit, RestorePlan
from .store import OpStore


class RestoreExecutor:
    def __init__(self, handle: WorkspaceHandle, engine: SnapshotEngine) -> None:
        self.handle = handle
        self.engine = engine
        self.root = Path(handle.config.root_path)
        self.objects = ObjectStore(handle.paths.objects_dir)

    def _root_identity(self) -> tuple[int, int]:
        for part in (self.root, *self.root.parents):
            if is_link_like(part):
                raise RestoreConflictError("恢复路径含链接或 reparse point", detail=str(part))
        info = self.root.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise RestoreConflictError("工作区根不再是目录")
        return info.st_dev, info.st_ino

    def _config_hash(self) -> str:
        return sha256_hex(canonical_json(self.handle.config.model_dump()))

    def _path(self, relative: str) -> Path:
        safe_relative(relative)
        self._root_identity()
        path = self.root
        for part in relative.split("/"):
            path /= part
            if path.exists() or path.is_symlink():
                if is_link_like(path):
                    raise RestoreConflictError("恢复路径含链接或 reparse point", detail=relative)
        return path

    def _inventory(self, plan: RestorePlan | None = None):
        self._root_identity()
        files: dict[str, FileState] = {}
        dirs: set[str] = set()
        protected: set[str] = set()
        stages = self._stages(plan) if plan else {}

        def walk(parent: Path):
            for path in parent.iterdir():
                name = path.relative_to(self.root).as_posix()
                if name in stages:
                    if is_link_like(path) or not path.is_file():
                        raise RestoreConflictError("恢复临时路径被其他类型占用", detail=name)
                    target = stages[name]
                    data = self.objects.read(plan.after[target].oid)[1]
                    if not data.startswith(path.read_bytes()):
                        raise RestoreConflictError("恢复临时文件被外部修改", detail=name)
                    continue
                if self.handle.config.ignore.ignores(Path(name)) or is_link_like(path):
                    protected.add(name)
                elif path.is_dir():
                    dirs.add(name)
                    walk(path)
                elif path.is_file():
                    data = path.read_bytes()
                    mode = MODE_EXECUTABLE if path.stat().st_mode & 0o111 else MODE_REGULAR
                    files[name] = FileState(oid=object_id(ObjectType.BLOB, data), mode=mode)
                else:
                    protected.add(name)

        walk(self.root)
        return files, dirs, protected

    @staticmethod
    def _stages(plan: RestorePlan | None) -> dict[str, str]:
        if plan is None:
            return {}
        result = {}
        for index, path in enumerate(sorted(plan.after)):
            if plan.before.get(path) == plan.after[path]:
                continue
            parent = path.rpartition("/")[0]
            name = f".skillforge-{plan.plan_id}-{index}.tmp"
            result[f"{parent}/{name}" if parent else name] = path
        return result

    def load(self, plan_id: str) -> RestorePlan:
        conn = connect(self.handle.paths.db_file)
        try:
            op = OpStore(conn).get(self.handle.workspace_id, plan_id)
            if op is None or op.kind != OpKind.RESTORE_PLAN:
                raise RestorePlanNotFoundError("恢复计划不存在", detail=plan_id)
            return RestorePlan.model_validate({**json.loads(op.payload_json), "plan_id": op.op_id})
        finally:
            conn.close()

    def preview(self, before_rev: str, target_rev: str, *, action="restore") -> RestorePlan | None:
        conn = connect(self.handle.paths.db_file)
        try:
            ops = OpStore(conn)
            if pending := ops.pending_restore(self.handle.workspace_id):
                raise RestorePendingError("请先继续未完成的恢复", detail=pending)
            revisions = RevisionStore(conn)
            before = revisions.get(self.handle.workspace_id, before_rev)
            target = revisions.get(self.handle.workspace_id, target_rev)
            if before.root_tree_oid == target.root_tree_oid:
                return None
            old_files, old_dirs = read_tree(self.objects, before.root_tree_oid)
            new_files, new_dirs = read_tree(self.objects, target.root_tree_oid)
            plan = RestorePlan(
                plan_id="preview",
                before_rev=before_rev,
                target_rev=target_rev,
                action=action,
                config_hash=self._config_hash(),
                root_identity=self._root_identity(),
                before={p: FileState(oid=v[0], mode=v[1]) for p, v in old_files.items()},
                after={p: FileState(oid=v[0], mode=v[1]) for p, v in new_files.items()},
                before_dirs=old_dirs,
                after_dirs=new_dirs,
            )
            self._validate(plan, resuming=False)
            with transaction(conn):
                op = ops.record(
                    ws_id=self.handle.workspace_id,
                    kind=OpKind.RESTORE_PLAN,
                    payload=plan.model_dump(exclude={"plan_id"}),
                )
            return plan.model_copy(update={"plan_id": op.op_id})
        finally:
            conn.close()

    def _validate(self, plan: RestorePlan, *, resuming: bool) -> None:
        if plan.config_hash != self._config_hash() or plan.root_identity != self._root_identity():
            raise RestoreConflictError("工作区根或配置已变化，请重新制定计划")
        files, directories, protected = self._inventory(plan if resuming else None)
        all_paths = (
            plan.before.keys() | plan.after.keys() | set(plan.before_dirs) | set(plan.after_dirs)
        )
        if len({path.casefold() for path in all_paths}) != len(all_paths):
            raise RestoreConflictError("恢复前后存在大小写冲突路径")
        for path in all_paths:
            safe_relative(path)
            if self.handle.config.ignore.ignores(Path(path)):
                raise RestoreConflictError("恢复目标涉及当前忽略路径", detail=path)
        # 文件/目录转换暂时明确拒绝，避免删除包含未纳管内容的目录。
        if (plan.before.keys() & set(plan.after_dirs)) or (
            plan.after.keys() & set(plan.before_dirs)
        ):
            raise RestoreConflictError("恢复包含文件与目录类型转换，请先解决路径冲突")
        touched = {item["path"] for item in plan.changes()}
        for path in protected:
            if any(
                path == p or path.startswith(p + "/") or p.startswith(path + "/") for p in touched
            ):
                raise RestoreConflictError("恢复路径与忽略文件、链接或特殊文件冲突", detail=path)
        if not resuming:
            for stage in self._stages(plan):
                if self._path(stage).exists():
                    raise RestoreConflictError("恢复临时路径已被占用", detail=stage)
            if files != plan.before or directories != set(plan.before_dirs):
                raise RestoreConflictError("预览后文件已变化，请重新预览")
        else:
            for path in files.keys() | plan.before.keys() | plan.after.keys():
                if files.get(path) not in (plan.before.get(path), plan.after.get(path)):
                    raise RestoreConflictError("恢复期间文件被外部修改，停止覆盖", detail=path)
            if not set(plan.before_dirs).intersection(plan.after_dirs) <= directories:
                raise RestoreConflictError("恢复期间公共目录被移除")
            if not directories <= set(plan.before_dirs) | set(plan.after_dirs):
                raise RestoreConflictError("恢复期间出现新目录")
        for path, state in plan.after.items():
            if os.name == "nt" and state.mode != MODE_REGULAR:
                raise RestoreConflictError("Windows 不支持恢复此可执行模式", detail=path)
            if self.objects.read(state.oid)[0] != ObjectType.BLOB:
                raise RestoreConflictError("恢复文件对象不是 blob", detail=path)

    def _apply_files(self, plan: RestorePlan) -> None:
        # 每一步复核剩余磁盘状态；任一步失败都保持 begin，重试可幂等继续。
        for name in sorted(plan.before.keys() - plan.after.keys()):
            self._validate(plan, resuming=True)
            path = self._path(name)
            if path.exists():
                path.unlink()
        for name in sorted(
            set(plan.before_dirs) - set(plan.after_dirs), key=lambda p: -p.count("/")
        ):
            self._validate(plan, resuming=True)
            path = self._path(name)
            if path.exists():
                path.rmdir()  # 仅空目录，绝不递归删除
        for name in sorted(
            set(plan.after_dirs) - set(plan.before_dirs), key=lambda p: p.count("/")
        ):
            self._validate(plan, resuming=True)
            self._path(name).mkdir(exist_ok=True)
        for stage, name in self._stages(plan).items():
            self._validate(plan, resuming=True)
            path = self._path(name)
            data = self.objects.read(plan.after[name].oid)[1]
            tmp = self._path(stage)
            if tmp.exists():
                tmp.unlink()  # inventory 已验证是本计划的目标字节前缀
            with tmp.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                tmp.chmod(0o755 if plan.after[name].mode == MODE_EXECUTABLE else 0o644)
            self._validate(plan, resuming=True)
            os.replace(tmp, path)
        self._validate(plan, resuming=True)

    def apply(self, plan_id: str) -> SnapshotResult:
        plan = self.load(plan_id)
        conn = connect(self.handle.paths.db_file)
        try:
            ops = OpStore(conn)
            if done := ops.restore_done(self.handle.workspace_id, plan_id):
                rev = RevisionStore(conn).get(
                    self.handle.workspace_id, json.loads(done.payload_json)["after_rev"]
                )
                return SnapshotResult(revision=rev, created=False)
            pending = ops.pending_restore(self.handle.workspace_id)
            if pending and pending != plan_id:
                raise RestorePendingError("另一个恢复尚未完成", detail=pending)
            head = RevisionStore(conn).head(self.handle.workspace_id)
            if head is None or head.rev_id != plan.before_rev:
                raise RestoreConflictError("预览后的已提交修订发生变化，请重新预览")
            self._validate(plan, resuming=pending == plan_id)
            if not pending:
                with transaction(conn):
                    ops.record(
                        ws_id=self.handle.workspace_id,
                        kind=OpKind.RESTORE_BEGIN,
                        parent_op_id=plan_id,
                        payload={"plan_id": plan_id},
                    )
            target = RevisionStore(conn).get(self.handle.workspace_id, plan.target_rev)
        finally:
            conn.close()
        self._apply_files(plan)
        self.engine.end_active_change()
        result = self.engine.capture(
            trigger=SnapshotTrigger.MANUAL,
            restore=RestoreCommit(
                plan_id=plan_id,
                before_rev=plan.before_rev,
                target_rev=plan.target_rev,
                target_tree=target.root_tree_oid,
                action=plan.action,
            ),
        )
        self.engine.end_active_change()
        return result
