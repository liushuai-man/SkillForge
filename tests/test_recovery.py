"""AC-15：真实进程强杀，不用异常代替提交前后崩溃。"""

from __future__ import annotations

import json
import multiprocessing
from contextlib import contextmanager
from pathlib import Path

import pytest

from skillforge_vm.core.errors import WorkspaceBusyError
from skillforge_vm.core.locking import DataRootLock
from skillforge_vm.db.connection import connect
from skillforge_vm.objectstore.store import ObjectStore
from skillforge_vm.oplog.store import OpStore
from skillforge_vm.revision.store import RevisionStore
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.workspace.manager import WorkspaceManager


def _pause(pipe, phase):
    pipe.send(phase)
    pipe.recv()  # 父进程在确定的故障点强杀；正常情况下不会继续。


def _crash_worker(data_root, ws_id, phase, pipe):
    from skillforge_vm.watcher import engine

    manager = WorkspaceManager(data_root=Path(data_root))
    lock = DataRootLock(manager.data_root)
    lock.acquire()
    real_transaction = engine.transaction
    real_write = ObjectStore._atomic_write

    if phase == "object":

        def interrupted_write(self, path, data):
            real_write(path, data)
            _pause(pipe, phase)

        ObjectStore._atomic_write = interrupted_write
    else:

        @contextmanager
        def interrupted_transaction(conn):
            with real_transaction(conn):
                yield
                if phase == "before_commit":
                    _pause(pipe, phase)
            if phase == "after_commit":
                _pause(pipe, phase)

        engine.transaction = interrupted_transaction
    SnapshotEngine(manager.get(ws_id)).capture()


@pytest.mark.parametrize("phase", ["object", "before_commit", "after_commit"])
def test_killed_writer_recovers_atomically(tmp_path: Path, phase: str) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "a.md").write_bytes(b"before")
    manager = WorkspaceManager(data_root=tmp_path / "data")
    handle = manager.init(skill).workspace
    (skill / "a.md").write_bytes(b"after")
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(
        target=_crash_worker,
        args=(str(manager.data_root), handle.workspace_id, phase, child),
    )
    process.start()
    try:
        assert parent.poll(15), "子进程未到达故障点"
        assert parent.recv() == phase
        competing = DataRootLock(manager.data_root)
        with pytest.raises(WorkspaceBusyError):
            competing.acquire()
        process.kill()
        process.join(10)
        assert not process.is_alive()
        competing.acquire()  # 强杀自动释放系统锁；无需删除锁文件
        try:
            conn = connect(handle.paths.db_file)
            try:
                head = RevisionStore(conn).head(handle.workspace_id)
                assert head.seq == (2 if phase == "after_commit" else 1)
                assert len(OpStore(conn).list(handle.workspace_id)) == head.seq
            finally:
                conn.close()
            result = SnapshotEngine(manager.get(handle.workspace_id)).capture()
            assert result.revision.seq == 2
            assert result.created is (phase != "after_commit")
            store = ObjectStore(handle.paths.objects_dir)
            root = json.loads(store.read(result.revision.root_tree_oid)[1])
            assert root["entries"][0]["name"] == "a.md"
            assert store.read(root["entries"][0]["oid"])[1] == b"after"
            assert json.loads(store.read(result.revision.rev_id)[1])["seq"] == 2
            conn = connect(handle.paths.db_file)
            try:
                assert len(OpStore(conn).list(handle.workspace_id)) == 2
                assert len(RevisionStore(conn).list(handle.workspace_id)) == 2
                assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                conn.close()
        finally:
            competing.release()
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)
        parent.close()
        child.close()


async def test_second_service_cannot_start_on_same_root(tmp_path: Path) -> None:
    from skillforge_vm.api.app import create_app

    manager = WorkspaceManager(data_root=tmp_path / "data")
    first, second = create_app(manager), create_app(manager)
    async with first.router.lifespan_context(first):
        with pytest.raises(WorkspaceBusyError):
            async with second.router.lifespan_context(second):
                pytest.fail("第二个服务不得启动")
    async with second.router.lifespan_context(second):
        pass
