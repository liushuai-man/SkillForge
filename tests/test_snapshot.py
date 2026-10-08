"""M-02 快照执行器验收：零写入、突发合并、A→B→A、串行、Change 分组、失败恢复。

对应 AC-04 / AC-05 / AC-06 / AC-15（快照故障点）/ EDGE-15 / AC-16。
"""

from __future__ import annotations

import os
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from skillforge_vm.core.errors import SnapshotUnstableError
from skillforge_vm.core.types import MODE_REGULAR
from skillforge_vm.db.connection import connect
from skillforge_vm.db.connection import transaction as real_transaction
from skillforge_vm.objectstore.store import ObjectStore
from skillforge_vm.revision.models import Revision
from skillforge_vm.revision.store import RevisionStore
from skillforge_vm.watcher import engine as engine_module
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.watcher.scanner import ScanEntry
from skillforge_vm.workspace.manager import WorkspaceHandle, WorkspaceManager


def _head(handle: WorkspaceHandle) -> Revision:
    conn = connect(handle.paths.db_file)
    try:
        head = RevisionStore(conn).head(handle.workspace_id)
    finally:
        conn.close()
    assert head is not None
    return head


def _count(handle: WorkspaceHandle, table: str) -> int:
    conn = connect(handle.paths.db_file)
    try:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    finally:
        conn.close()


def test_no_change_commits_nothing(workspace: WorkspaceHandle) -> None:
    engine = SnapshotEngine(workspace)
    before_head = _head(workspace)
    before_objects = _count(workspace, "object")

    result = engine.capture()

    assert result.created is False
    assert result.revision == before_head
    assert _count(workspace, "revision") == 1
    assert _count(workspace, "object") == before_objects
    assert _count(workspace, "op") == 0


def test_mtime_only_change_is_noop(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    engine = SnapshotEngine(workspace)
    target = skill_dir / "SKILL.md"
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))

    result = engine.capture()

    assert result.created is False
    assert _count(workspace, "revision") == 1


def test_repeated_identical_saves_are_noop(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    engine = SnapshotEngine(workspace)
    for _ in range(5):
        (skill_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

    result = engine.capture()

    assert result.created is False
    assert _count(workspace, "revision") == 1


def test_burst_commits_only_final_stable_content(
    workspace: WorkspaceHandle, skill_dir: Path
) -> None:
    engine = SnapshotEngine(workspace)
    for index in range(5):
        (skill_dir / "SKILL.md").write_text(f"# Demo {index}\n", encoding="utf-8")

    result = engine.capture()

    assert result.created is True
    assert result.revision.seq == 2
    assert _count(workspace, "revision") == 2
    store = ObjectStore(workspace.paths.objects_dir)
    _, body = store.read(result.revision.root_tree_oid)
    assert body  # 根 tree 可读回


def test_a_b_a_records_three_events_and_reuses_objects(
    workspace: WorkspaceHandle, skill_dir: Path
) -> None:
    engine = SnapshotEngine(workspace)
    first = _head(workspace)

    (skill_dir / "SKILL.md").write_text("# Demo B\n", encoding="utf-8")
    second = engine.capture()
    assert second.created is True
    objects_before = _count(workspace, "object")

    (skill_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    third = engine.capture()

    assert third.created is True
    assert third.revision.seq == 3
    assert third.revision.parent_rev_id == second.revision.rev_id
    assert third.revision.root_tree_oid == first.root_tree_oid  # 内容回到 A
    assert third.revision.rev_id != first.rev_id  # 但不是旧修订
    # 第三步只新增 meta 对象，blob/tree 全部复用
    assert _count(workspace, "object") == objects_before + 1


def test_commit_failure_is_not_visible_and_retry_succeeds(
    workspace: WorkspaceHandle, skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SnapshotEngine(workspace)

    def failing_transaction(conn: object) -> object:
        raise RuntimeError("模拟数据库提交失败")

    monkeypatch.setattr(engine_module, "transaction", failing_transaction)
    (skill_dir / "SKILL.md").write_text("# Demo X\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        engine.capture()

    # 提交失败：没有发布新修订，工作区仍停在首个修订
    assert _count(workspace, "revision") == 1
    assert _head(workspace).seq == 1

    monkeypatch.setattr(engine_module, "transaction", real_transaction)
    retry = engine.capture()
    assert retry.created is True
    assert retry.revision.seq == 2


def test_concurrent_captures_never_reuse_seq(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    engine = SnapshotEngine(workspace)
    results: list[Revision] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        (skill_dir / f"f{index}.md").write_text(f"content {index}\n", encoding="utf-8")
        for _ in range(5):
            try:
                revision = engine.capture().revision
                break
            except SnapshotUnstableError:
                continue
        else:  # pragma: no cover - 不应发生
            failures.append(AssertionError("capture 持续不稳定"))
            return
        with lock:
            results.append(revision)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    seqs = sorted({revision.seq for revision in results} - {1})
    assert len(seqs) == len(set(seqs))  # 无重复序号
    assert seqs == list(range(2, 2 + len(seqs)))  # 无跳号
    assert _count(workspace, "revision") == 1 + len(seqs)


def test_change_continues_within_idle_and_breaks_on_boundary(
    workspace: WorkspaceHandle, skill_dir: Path
) -> None:
    now = {"t": 0.0}
    engine = SnapshotEngine(
        workspace, idle_threshold=timedelta(seconds=100), clock=lambda: now["t"]
    )

    def bump(text: str) -> Revision:
        (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
        result = engine.capture()
        assert result.created is True
        return result.revision

    first = bump("# 1\n")
    now["t"] += 10
    second = bump("# 2\n")
    assert second.change_id == first.change_id

    conn = connect(workspace.paths.db_file)
    try:
        change = RevisionStore(conn).get_change(workspace.workspace_id, first.change_id)
    finally:
        conn.close()
    assert change is not None
    assert change.first_rev == first.rev_id
    assert change.last_rev == second.rev_id

    now["t"] += 1000  # 超过空闲阈值 → 新 Change
    third = bump("# 3\n")
    assert third.change_id != first.change_id

    engine.end_active_change()  # 显式边界（打锚点 / 撤销）
    fourth = bump("# 4\n")
    assert fourth.change_id != third.change_id


def test_persistent_change_raises_snapshot_unstable(
    workspace: WorkspaceHandle, skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SnapshotEngine(workspace)
    counter = {"n": 0}

    def always_moving(root: Path, ignore: object = None) -> tuple[ScanEntry, ...]:
        counter["n"] += 1
        return (ScanEntry(rel_path=f"x{counter['n']}", mode=MODE_REGULAR, size=0, mtime_ns=0),)

    monkeypatch.setattr(engine_module, "scan_files", always_moving)
    (skill_dir / "SKILL.md").write_text("# unstable\n", encoding="utf-8")

    with pytest.raises(SnapshotUnstableError):
        engine.capture()


def test_symlink_entry_is_skipped(tmp_path: Path, skill_dir: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = skill_dir / "link.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不支持创建符号链接")

    result = WorkspaceManager(data_root=tmp_path / "data").init(skill_dir)

    assert result.file_count == 2  # SKILL.md + sub/config.yaml，符号链接不纳管
