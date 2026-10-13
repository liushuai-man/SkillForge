"""M-04 身份编码与存储读写用例。"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillforge_vm.core.errors import InvalidRequestError, RefNotFoundError, RevisionNotFoundError
from skillforge_vm.core.types import CHANGE_ID_ALPHABET, CHANGE_ID_PREFIX, ObjectType
from skillforge_vm.db.connection import connect
from skillforge_vm.objectstore.store import ObjectStore
from skillforge_vm.revision.identity import (
    is_revision_id,
    new_change_id,
    revision_meta_payload,
)
from skillforge_vm.revision.models import Ref
from skillforge_vm.revision.store import RevisionStore
from skillforge_vm.workspace.manager import WorkspaceHandle


def test_new_change_id_uses_fixed_alphabet() -> None:
    change_id = new_change_id()

    assert change_id.startswith(CHANGE_ID_PREFIX)
    body = change_id[len(CHANGE_ID_PREFIX) :]
    assert len(body) == 64
    assert set(body) <= set(CHANGE_ID_ALPHABET)


def test_is_revision_id_checks_shape() -> None:
    assert is_revision_id("a" * 64)
    assert not is_revision_id("A" * 64)  # 大写非法
    assert not is_revision_id("a" * 63)


def test_revision_meta_payload_is_deterministic(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")
    payload = revision_meta_payload(
        ws_id="ws",
        change_id="CHG-x",
        parent_rev_id=None,
        root_tree_oid="0" * 64,
        trigger="init",
        source="initial",
        ts="2026-10-08T00:00:00+00:00",
        seq=1,
    )

    first = store.write_meta(payload)
    second = store.write_meta(dict(payload))

    assert first.oid == second.oid
    obj_type, _ = store.read(first.oid)
    assert obj_type == ObjectType.META
    assert payload["schema_version"] == 1


def test_store_head_get_and_list(workspace: WorkspaceHandle) -> None:
    conn = connect(workspace.paths.db_file)
    try:
        revisions = RevisionStore(conn)
        head = revisions.head(workspace.workspace_id)
        assert head is not None
        assert head.seq == 1
        assert revisions.get(workspace.workspace_id, head.rev_id) == head
        assert [r.seq for r in revisions.list(workspace.workspace_id)] == [1]
    finally:
        conn.close()


def test_store_missing_revision_raises(workspace: WorkspaceHandle) -> None:
    conn = connect(workspace.paths.db_file)
    try:
        with pytest.raises(RevisionNotFoundError):
            RevisionStore(conn).get(workspace.workspace_id, "f" * 64)
    finally:
        conn.close()


def test_ref_roundtrip_and_reserved_name(workspace: WorkspaceHandle) -> None:
    conn = connect(workspace.paths.db_file)
    try:
        revisions = RevisionStore(conn)
        head = revisions.head(workspace.workspace_id)
        assert head is not None

        with pytest.raises(RefNotFoundError):
            revisions.get_ref(workspace.workspace_id, "stable")

        revisions.set_ref(
            Ref(
                name="tested",
                ws_id=workspace.workspace_id,
                rev_id=head.rev_id,
                updated_at="2026-10-08T00:00:00+00:00",
            )
        )
        conn.commit()
        assert revisions.get_ref(workspace.workspace_id, "tested").rev_id == head.rev_id

        with pytest.raises(InvalidRequestError):
            revisions.set_ref(
                Ref(
                    name="last",
                    ws_id=workspace.workspace_id,
                    rev_id=head.rev_id,
                    updated_at="2026-10-08T00:00:00+00:00",
                )
            )
    finally:
        conn.close()


def test_index_paths_records_every_file(workspace: WorkspaceHandle) -> None:
    conn = connect(workspace.paths.db_file)
    try:
        rows = conn.execute("SELECT rev_id, path FROM blob_index").fetchall()
    finally:
        conn.close()

    assert {row["path"] for row in rows} == {"SKILL.md", "sub/config.yaml"}
    assert len({row["rev_id"] for row in rows}) == 1
