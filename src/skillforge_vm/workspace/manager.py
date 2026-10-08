"""M-01 工作区管理。

绑定一个 Skill 目录 → 生成工作区标识 → 写 ``workspace.json`` → 建立对象库与元数据库，
并写入首个对象（根 tree 及其下全部 blob）。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..core.config import Settings
from ..core.errors import (
    InvalidSkillRootError,
    WorkspaceAlreadyInitializedError,
    WorkspaceNotFoundError,
)
from ..core.types import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_IGNORE_GLOBS,
    SnapshotSource,
    SnapshotTrigger,
    tool_version,
)
from ..db.connection import connect, init_schema, transaction
from ..objectstore.index import ObjectIndex
from ..objectstore.store import ObjectStore
from ..revision.identity import new_change_id, revision_meta_payload
from ..revision.models import Revision
from ..revision.store import RevisionStore
from .models import IgnoreRules, WorkspaceConfig, WorkspacePaths


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class WorkspaceHandle:
    """一个已纳管工作区的句柄（配置 + 路径）。"""

    config: WorkspaceConfig
    paths: WorkspacePaths

    @property
    def workspace_id(self) -> str:
        return self.config.workspace_id


@dataclass(frozen=True)
class InitResult:
    """``init`` 的产物：证明「已绑定目录、写入首个对象并提交首个 Revision」。"""

    workspace: WorkspaceHandle
    root_tree_oid: str
    revision_id: str
    change_id: str
    file_count: int
    object_count: int


class WorkspaceManager:
    """负责工作区的纳管与检索，一个服务可纳管多个工作区（FR-01.2）。"""

    def __init__(self, data_root: Path | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._data_root = Path(data_root) if data_root is not None else self._settings.data_root

    @property
    def data_root(self) -> Path:
        return self._data_root

    @property
    def workspaces_dir(self) -> Path:
        return self._data_root / "workspaces"

    def init(self, skill_path: str | Path, name: str | None = None) -> InitResult:
        """绑定一个 Skill 目录并写入首个对象。"""
        root = Path(skill_path).expanduser().resolve()
        if not root.is_dir():
            raise InvalidSkillRootError(f"Skill 目录不存在或不是目录：{root}", detail=str(root))

        existing = self.find_by_path(root)
        if existing is not None:
            raise WorkspaceAlreadyInitializedError(
                f"该目录已被纳管（工作区 {existing.workspace_id}）", detail=str(root)
            )

        workspace_id = uuid.uuid4().hex
        paths = WorkspacePaths.for_data_path(self.workspaces_dir / workspace_id, root)
        paths.data.mkdir(parents=True, exist_ok=True)

        config = self._build_config(workspace_id, name or root.name, root, paths.data)

        store = ObjectStore(paths.objects_dir)
        written = store.write_directory_detailed(root, config.ignore.ignores)
        change_id = new_change_id()
        meta = store.write_meta(
            revision_meta_payload(
                ws_id=config.workspace_id,
                change_id=change_id,
                parent_rev_id=None,
                root_tree_oid=written.root.oid,
                trigger=SnapshotTrigger.INIT,
                source=SnapshotSource.INITIAL,
                ts=config.created_at,
                seq=1,
            )
        )
        revision = Revision(
            rev_id=meta.oid,
            ws_id=config.workspace_id,
            change_id=change_id,
            parent_rev_id=None,
            root_tree_oid=written.root.oid,
            trigger=SnapshotTrigger.INIT.value,
            source=SnapshotSource.INITIAL.value,
            ts=config.created_at,
            seq=1,
        )

        conn = connect(paths.db_file)
        try:
            init_schema(conn)
            revisions = RevisionStore(conn)
            with transaction(conn):
                conn.execute(
                    """
                    INSERT INTO workspace
                        (id, name, root_path, data_path, config_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        config.workspace_id,
                        config.name,
                        config.root_path,
                        config.data_path,
                        config.model_dump_json(),
                        config.created_at,
                    ),
                )
                index = ObjectIndex(conn)
                index.record_many(written.records)
                index.record(meta)
                revisions.insert(revision)
                revisions.start_change(config.workspace_id, change_id, revision.rev_id)
                revisions.index_paths(revision.rev_id, written.files)
        finally:
            conn.close()

        # 可见标志最后发布：对象、数据库与修订都完整后，工作区才出现在正常列表；
        # 失败时不会留下「已纳管但数据库/修订不存在」的假工作区，再次 init 可安全重试（AC-01）。
        self._write_config(paths.config_file, config)

        return InitResult(
            workspace=WorkspaceHandle(config=config, paths=paths),
            root_tree_oid=written.root.oid,
            revision_id=revision.rev_id,
            change_id=change_id,
            file_count=len(written.files),
            object_count=len({r.oid for r in written.records} | {meta.oid}),
        )

    def get(self, workspace_id: str) -> WorkspaceHandle:
        """按工作区标识取句柄。"""
        config_file = self.workspaces_dir / workspace_id / "workspace.json"
        if not config_file.is_file():
            raise WorkspaceNotFoundError(f"工作区不存在：{workspace_id}", detail=str(config_file))
        return self._load_handle(config_file)

    def list(self) -> list[WorkspaceHandle]:
        """列出全部已纳管工作区。"""
        if not self.workspaces_dir.is_dir():
            return []
        return [
            self._load_handle(config_file)
            for config_file in sorted(self.workspaces_dir.glob("*/workspace.json"))
        ]

    def find_by_path(self, skill_path: str | Path) -> WorkspaceHandle | None:
        """按 Skill 目录查找已纳管工作区（路径比较，不关心大小写）。"""
        target = _normalized(Path(skill_path))
        for handle in self.list():
            if _normalized(Path(handle.config.root_path)) == target:
                return handle
        return None

    def _build_config(
        self, workspace_id: str, name: str, root: Path, data_path: Path
    ) -> WorkspaceConfig:
        return WorkspaceConfig(
            workspace_id=workspace_id,
            name=name,
            root_path=str(root),
            data_path=str(data_path),
            created_at=_now_iso(),
            tool_version=tool_version(),
            ignore=IgnoreRules(dirs=list(DEFAULT_IGNORE_DIRS), globs=list(DEFAULT_IGNORE_GLOBS)),
        )

    @staticmethod
    def _load_handle(config_file: Path) -> WorkspaceHandle:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
        config = WorkspaceConfig.model_validate(raw)
        paths = WorkspacePaths.for_data_path(Path(config.data_path), Path(config.root_path))
        return WorkspaceHandle(config=config, paths=paths)

    @staticmethod
    def _write_config(config_file: Path, config: WorkspaceConfig) -> None:
        payload = json.dumps(json.loads(config.model_dump_json()), indent=2, ensure_ascii=False)
        tmp = config_file.with_name(f".{config_file.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(payload + "\n", encoding="utf-8")
            os.replace(tmp, config_file)
        finally:
            if tmp.exists():
                tmp.unlink()


def _normalized(path: Path) -> str:
    """路径比较用的规范形式：绝对化 + 平台相关的大小写归一。"""
    resolved = str(Path(path).expanduser().resolve())
    return os.path.normcase(resolved)
