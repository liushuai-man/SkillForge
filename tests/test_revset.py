"""M-04 最小 revset 解析用例（§7.4）。

只接受 `@`、`last`、完整 Revision ID、`<ref>`、`<rev-or-ref>~N`；
区间表达式与未知引用明确报错，不回退成零基线。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from skillforge_vm.core.errors import InvalidRequestError, RefNotFoundError, RevisionNotFoundError
from skillforge_vm.db.connection import connect
from skillforge_vm.revision.models import Ref, Revision
from skillforge_vm.revision.revset import resolve_revset
from skillforge_vm.revision.store import RevisionStore
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.workspace.manager import WorkspaceHandle


def _make_history(workspace: WorkspaceHandle, skill_dir: Path, count: int = 3) -> list[Revision]:
    """返回 [初始修订, 之后每次内容变化产生的修订...]。"""
    conn = connect(workspace.paths.db_file)
    try:
        head = RevisionStore(conn).head(workspace.workspace_id)
    finally:
        conn.close()
    assert head is not None

    engine = SnapshotEngine(workspace)
    revisions = [head]
    for index in range(count):
        (skill_dir / "SKILL.md").write_text(f"# v{index}\n", encoding="utf-8")
        result = engine.capture()
        assert result.created is True
        revisions.append(result.revision)
    return revisions


def _store(workspace: WorkspaceHandle) -> tuple[RevisionStore, sqlite3.Connection]:
    conn = connect(workspace.paths.db_file)
    return RevisionStore(conn), conn


def test_resolve_at_and_last(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    revisions = _make_history(workspace, skill_dir)
    store, conn = _store(workspace)
    try:
        head = revisions[-1]
        assert (
            resolve_revset("@", store=store, ws_id=workspace.workspace_id, current=head.rev_id)
            == head.rev_id
        )
        assert resolve_revset("last", store=store, ws_id=workspace.workspace_id) == head.rev_id
    finally:
        conn.close()


def test_resolve_full_id_and_parent_walk(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    revisions = _make_history(workspace, skill_dir)
    store, conn = _store(workspace)
    try:
        assert (
            resolve_revset(revisions[1].rev_id, store=store, ws_id=workspace.workspace_id)
            == revisions[1].rev_id
        )
        assert (
            resolve_revset("last~1", store=store, ws_id=workspace.workspace_id)
            == revisions[-2].rev_id
        )
        assert (
            resolve_revset("last~3", store=store, ws_id=workspace.workspace_id)
            == revisions[0].rev_id
        )
        assert (
            resolve_revset("last~0", store=store, ws_id=workspace.workspace_id)
            == revisions[-1].rev_id
        )
    finally:
        conn.close()


def test_resolve_named_ref(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    revisions = _make_history(workspace, skill_dir)
    store, conn = _store(workspace)
    try:
        store.set_ref(
            Ref(
                name="tested",
                ws_id=workspace.workspace_id,
                rev_id=revisions[1].rev_id,
                updated_at="2026-10-08T00:00:00+00:00",
            )
        )
        conn.commit()
        assert (
            resolve_revset("tested", store=store, ws_id=workspace.workspace_id)
            == revisions[1].rev_id
        )
        assert (
            resolve_revset("tested~1", store=store, ws_id=workspace.workspace_id)
            == revisions[0].rev_id
        )
    finally:
        conn.close()


def test_unknown_ref_and_out_of_range(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    _make_history(workspace, skill_dir)
    store, conn = _store(workspace)
    try:
        with pytest.raises(RefNotFoundError):
            resolve_revset("stable", store=store, ws_id=workspace.workspace_id)
        with pytest.raises(RevisionNotFoundError):
            resolve_revset("last~99", store=store, ws_id=workspace.workspace_id)
    finally:
        conn.close()


def test_invalid_expressions(workspace: WorkspaceHandle, skill_dir: Path) -> None:
    revisions = _make_history(workspace, skill_dir)
    store, conn = _store(workspace)
    try:
        with pytest.raises(InvalidRequestError):
            resolve_revset("", store=store, ws_id=workspace.workspace_id)
        with pytest.raises(InvalidRequestError):
            resolve_revset("last~1~2", store=store, ws_id=workspace.workspace_id)
        with pytest.raises(InvalidRequestError):
            resolve_revset("last~x", store=store, ws_id=workspace.workspace_id)
        with pytest.raises(InvalidRequestError):
            resolve_revset("stable..last", store=store, ws_id=workspace.workspace_id)
        with pytest.raises(InvalidRequestError):
            resolve_revset("@", store=store, ws_id=workspace.workspace_id, current=None)
        assert resolve_revset(
            "@", store=store, ws_id=workspace.workspace_id, current=revisions[-1].rev_id
        )
    finally:
        conn.close()
