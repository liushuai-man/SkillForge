"""M-01 工作区纳管 + SQLite 建表的验收用例。

核心交付：能绑定一个 Skill 目录并写入第一个对象。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skillforge_vm.core.errors import (
    InvalidSkillRootError,
    WorkspaceAlreadyInitializedError,
    WorkspaceNotFoundError,
)
from skillforge_vm.db.connection import connect
from skillforge_vm.db.schema import TABLE_NAMES
from skillforge_vm.objectstore.store import ObjectStore
from skillforge_vm.revision.store import RevisionStore
from skillforge_vm.workspace.manager import WorkspaceManager


def _make_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "demo-skill"
    (skill / "sub").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (skill / "sub" / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    return skill


def test_init_binds_workspace_and_writes_first_object(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    manager = WorkspaceManager(data_root=tmp_path / "data")

    result = manager.init(skill)

    assert result.file_count == 2
    assert result.object_count == 5  # 2 个 blob + sub tree + 根 tree + 首个 meta
    assert result.workspace.paths.config_file.is_file()
    assert result.workspace.paths.db_file.is_file()

    store = ObjectStore(result.workspace.paths.objects_dir)
    assert store.object_path(result.root_tree_oid).is_file()


def test_init_commits_first_revision_and_change(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    result = WorkspaceManager(data_root=tmp_path / "data").init(skill)

    conn = connect(result.workspace.paths.db_file)
    try:
        revisions = RevisionStore(conn)
        head = revisions.head(result.workspace.workspace_id)
        change = revisions.get_change(result.workspace.workspace_id, result.change_id)
    finally:
        conn.close()

    assert head is not None
    assert head.rev_id == result.revision_id
    assert head.seq == 1
    assert head.parent_rev_id is None
    assert head.root_tree_oid == result.root_tree_oid
    assert (head.trigger, head.source) == ("init", "initial")
    assert change is not None
    assert (change.first_rev, change.last_rev) == (result.revision_id, result.revision_id)


def test_failed_init_can_be_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill = _make_skill(tmp_path)
    manager = WorkspaceManager(data_root=tmp_path / "data")

    original = ObjectStore.write_directory_detailed

    def boom(self: ObjectStore, root: Path, ignore: object = None) -> object:
        raise OSError("模拟对象写入失败")

    monkeypatch.setattr(ObjectStore, "write_directory_detailed", boom)
    with pytest.raises(OSError):
        manager.init(skill)

    # 失败没有留下可见工作区（可见标志最后发布），因此可以安全重试
    assert manager.find_by_path(skill) is None
    monkeypatch.setattr(ObjectStore, "write_directory_detailed", original)

    result = manager.init(skill)
    assert result.revision_id
    assert manager.find_by_path(skill) is not None


def test_init_does_not_write_into_skill_dir(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    before = sorted(p.relative_to(skill).as_posix() for p in skill.rglob("*"))

    WorkspaceManager(data_root=tmp_path / "data").init(skill)

    after = sorted(p.relative_to(skill).as_posix() for p in skill.rglob("*"))
    assert after == before


def test_ignore_rules_exclude_git_deps_and_temp(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    (skill / ".git").mkdir()
    (skill / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
    (skill / "node_modules").mkdir()
    (skill / "node_modules" / "index.js").write_text("x", encoding="utf-8")
    (skill / "draft.tmp").write_text("x", encoding="utf-8")

    result = WorkspaceManager(data_root=tmp_path / "data").init(skill)

    assert result.file_count == 2  # 只有 SKILL.md 与 sub/config.yaml


def test_workspace_json_records_config(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    result = WorkspaceManager(data_root=tmp_path / "data").init(skill, name="demo")

    raw = json.loads(result.workspace.paths.config_file.read_text(encoding="utf-8"))
    assert raw["name"] == "demo"
    assert raw["root_path"] == str(skill.resolve())
    assert ".git" in raw["ignore"]["dirs"]
    assert raw["parsers"]["by_extension"][".md"] == "markdown"
    assert raw["tool_version"]


def test_duplicate_init_is_rejected(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    manager = WorkspaceManager(data_root=tmp_path / "data")
    manager.init(skill)

    with pytest.raises(WorkspaceAlreadyInitializedError):
        manager.init(skill)


def test_init_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(InvalidSkillRootError):
        WorkspaceManager(data_root=tmp_path / "data").init(tmp_path / "nope")


def test_init_rejects_data_root_inside_skill(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    # 数据根位于 Skill 根内：对象库会被自身扫描纳入，必须拒绝（AC-16）
    with pytest.raises(InvalidSkillRootError):
        WorkspaceManager(data_root=skill / ".skillforge").init(skill)


def test_init_rejects_data_root_equal_to_skill(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    with pytest.raises(InvalidSkillRootError):
        WorkspaceManager(data_root=skill).init(skill)


def test_manages_multiple_workspaces(tmp_path: Path) -> None:
    manager = WorkspaceManager(data_root=tmp_path / "data")
    first = tmp_path / "s1"
    first.mkdir()
    (first / "a.md").write_text("a", encoding="utf-8")
    second = tmp_path / "s2"
    second.mkdir()
    (second / "b.md").write_text("b", encoding="utf-8")

    r1 = manager.init(first, name="one")
    r2 = manager.init(second, name="two")

    ids = {handle.workspace_id for handle in manager.list()}
    assert ids == {r1.workspace.workspace_id, r2.workspace.workspace_id}
    assert manager.get(r1.workspace.workspace_id).config.name == "one"
    assert manager.find_by_path(first).workspace_id == r1.workspace.workspace_id
    assert manager.find_by_path(tmp_path / "unknown") is None

    with pytest.raises(WorkspaceNotFoundError):
        manager.get("deadbeef")


def test_all_tables_are_created(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    result = WorkspaceManager(data_root=tmp_path / "data").init(skill)

    conn = connect(result.workspace.paths.db_file)
    try:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()

    for table in TABLE_NAMES:
        assert table in names


def test_written_objects_are_indexed(tmp_path: Path) -> None:
    skill = _make_skill(tmp_path)
    result = WorkspaceManager(data_root=tmp_path / "data").init(skill)

    conn = connect(result.workspace.paths.db_file)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM object").fetchone()["n"]
    finally:
        conn.close()

    assert count == result.object_count
