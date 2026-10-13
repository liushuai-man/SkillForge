"""AC-18 受控恢复；全部写入测试专用临时 Skill。"""

import json
import multiprocessing
from contextlib import contextmanager
from pathlib import Path

import pytest

from skillforge_vm.core.errors import RestoreConflictError, RestorePendingError
from skillforge_vm.db.connection import connect
from skillforge_vm.oplog.restore import RestoreExecutor
from skillforge_vm.oplog.store import OpStore
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.fixture()
def recovery(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "a.md").write_bytes(b"original\r\n")
    (root / "removed.md").write_bytes(b"restore me")
    (root / "empty").mkdir()
    handle = WorkspaceManager(data_root=tmp_path / "data").init(root).workspace
    engine = SnapshotEngine(handle)
    original = engine.capture().revision
    (root / "a.md").write_bytes(b"edited")
    (root / "removed.md").unlink()
    (root / "added.md").write_bytes(b"delete me")
    (root / "empty").rmdir()
    before = engine.capture().revision
    return root, handle, engine, original, before


def test_preview_restore_idempotency_and_undo_roundtrip(recovery):
    root, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)
    assert (root / "a.md").read_bytes() == b"edited"
    assert (root / "added.md").exists()
    assert {c["action"] for c in plan.changes()} == {"add", "modify", "delete", "mkdir"}
    result = executor.apply(plan.plan_id)
    assert result.revision.seq == 3
    assert result.revision.root_tree_oid == original.root_tree_oid
    assert (root / "a.md").read_bytes() == b"original\r\n"
    assert (root / "empty").is_dir()
    assert not (root / "added.md").exists()
    repeated = executor.apply(plan.plan_id)
    assert repeated.revision == result.revision and not repeated.created
    undo = executor.preview(result.revision.rev_id, before.rev_id, action="undo_restore")
    undone = executor.apply(undo.plan_id)
    assert undone.revision.seq == 4
    assert (root / "a.md").read_bytes() == b"edited"
    assert (root / "added.md").read_bytes() == b"delete me"
    redo = executor.preview(undone.revision.rev_id, result.revision.rev_id, action="undo_restore")
    assert executor.apply(redo.plan_id).revision.seq == 5


def test_confirm_rejects_new_edit_without_overwriting(recovery):
    root, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)
    (root / "a.md").write_bytes(b"new edit after preview")
    with pytest.raises(RestoreConflictError):
        executor.apply(plan.plan_id)
    assert (root / "a.md").read_bytes() == b"new edit after preview"
    conn = connect(handle.paths.db_file)
    try:
        assert OpStore(conn).pending_restore(handle.workspace_id) is None
    finally:
        conn.close()


def test_partial_failure_blocks_snapshots_and_resumes_after_restart(recovery, monkeypatch):
    root, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)

    def fail(plan):
        (root / "added.md").unlink()
        raise OSError("injected disk failure")

    monkeypatch.setattr(executor, "_apply_files", fail)
    with pytest.raises(OSError):
        executor.apply(plan.plan_id)
    with pytest.raises(RestorePendingError):
        engine.capture()
    restarted = RestoreExecutor(handle, SnapshotEngine(handle))
    result = restarted.apply(plan.plan_id)
    assert result.revision.seq == 3
    assert result.revision.root_tree_oid == original.root_tree_oid
    assert not restarted.apply(plan.plan_id).created


def test_resume_rejects_external_edits(recovery, monkeypatch):
    root, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)
    monkeypatch.setattr(
        executor, "_apply_files", lambda plan: (_ for _ in ()).throw(OSError("fail"))
    )
    with pytest.raises(OSError):
        executor.apply(plan.plan_id)
    (root / "a.md").write_bytes(b"external edit")
    with pytest.raises(RestoreConflictError):
        RestoreExecutor(handle, engine).apply(plan.plan_id)
    assert (root / "a.md").read_bytes() == b"external edit"


def test_ignored_content_in_removed_directory_is_protected(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    manager = WorkspaceManager(data_root=tmp_path / "data")
    handle = manager.init(root).workspace
    engine = SnapshotEngine(handle)
    original = engine.capture().revision
    (root / "folder").mkdir()
    (root / "folder" / "keep.log").write_bytes(b"ignored")
    before = engine.capture().revision
    with pytest.raises(RestoreConflictError):
        RestoreExecutor(handle, engine).preview(before.rev_id, original.rev_id)
    assert (root / "folder" / "keep.log").read_bytes() == b"ignored"


def test_current_ignore_rules_cannot_overwrite_historical_path(recovery):
    root, handle, engine, original, before = recovery
    config = handle.config.model_copy(deep=True)
    config.ignore.globs.append("removed.md")
    new_handle = type(handle)(config=config, paths=handle.paths)
    with pytest.raises(RestoreConflictError):
        RestoreExecutor(new_handle, engine).preview(before.rev_id, original.rev_id)
    assert not (root / "removed.md").exists()


def test_completed_plan_has_atomic_revision_link(recovery):
    _, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)
    after = executor.apply(plan.plan_id).revision
    conn = connect(handle.paths.db_file)
    try:
        op = OpStore(conn).restore_done(handle.workspace_id, plan.plan_id)
        assert json.loads(op.payload_json)["after_rev"] == after.rev_id
        assert OpStore(conn).pending_restore(handle.workspace_id) is None
    finally:
        conn.close()


def test_no_change_creates_no_plan(recovery):
    _, handle, engine, _, before = recovery
    conn = connect(handle.paths.db_file)
    try:
        count = OpStore(conn).count(handle.workspace_id)
        assert RestoreExecutor(handle, engine).preview(before.rev_id, before.rev_id) is None
        assert OpStore(conn).count(handle.workspace_id) == count
    finally:
        conn.close()


def test_path_traversal_in_tree_is_rejected(recovery):
    from skillforge_vm.core.errors import ObjectCorruptedError
    from skillforge_vm.objectstore.objects import TreeEntry
    from skillforge_vm.revision.content import read_tree

    _, handle, engine, _, _ = recovery
    executor = RestoreExecutor(handle, engine)
    blob = executor.objects.write_blob(b"escape")
    tree = executor.objects.write_tree([TreeEntry("../escape", "100644", blob.oid)])
    with pytest.raises(ObjectCorruptedError):
        read_tree(executor.objects, tree.oid)


def _restore_worker(data_root, ws, plan_id, phase, pipe):
    from skillforge_vm.watcher import engine as engine_module

    handle = WorkspaceManager(data_root=Path(data_root)).get(ws)
    executor = RestoreExecutor(handle, SnapshotEngine(handle))

    def pause():
        pipe.send(phase)
        pipe.recv()

    if phase == "partial":

        def partial(plan):
            (Path(handle.config.root_path) / "added.md").unlink()
            pause()

        executor._apply_files = partial
    else:
        real = engine_module.transaction

        @contextmanager
        def interrupt(conn):
            with real(conn):
                yield
                if phase == "before_commit":
                    pause()
            if phase == "after_commit":
                pause()

        engine_module.transaction = interrupt
    executor.apply(plan_id)


@pytest.mark.parametrize("phase", ["partial", "before_commit", "after_commit"])
def test_killed_restore_is_pending_or_atomically_complete(recovery, phase):
    _, handle, engine, original, before = recovery
    executor = RestoreExecutor(handle, engine)
    plan = executor.preview(before.rev_id, original.rev_id)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(
        target=_restore_worker,
        args=(
            str(handle.paths.data.parent.parent),
            handle.workspace_id,
            plan.plan_id,
            phase,
            child,
        ),
    )
    process.start()
    try:
        assert parent.poll(15), "恢复子进程没有到达强杀点"
        assert parent.recv() == phase
        process.kill()
        process.join(10)
        assert not process.is_alive()
        restarted = RestoreExecutor(handle, SnapshotEngine(handle))
        if phase != "after_commit":
            with pytest.raises(RestorePendingError):
                restarted.engine.capture()
        result = restarted.apply(plan.plan_id)
        assert result.revision.seq == 3
        assert result.revision.root_tree_oid == original.root_tree_oid
        assert result.created is (phase != "after_commit")
        assert not restarted.apply(plan.plan_id).created
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)
        parent.close()
        child.close()
