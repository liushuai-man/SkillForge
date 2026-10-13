"""M-09 操作日志：版本化载荷与插入顺序。

载荷格式是 TBD-09 草案（设计 §2.7 / 契约 §2.3）：``{"v":1, ...}`` 规范 JSON。
撤销的文件回写受 TBD-08 阻塞，本文件只验证「记录」部分。
"""

from __future__ import annotations

import json
from pathlib import Path

from skillforge_vm.db.connection import connect, transaction
from skillforge_vm.oplog.models import OP_PAYLOAD_VERSION, OpKind
from skillforge_vm.oplog.store import OpStore, build_payload
from skillforge_vm.workspace.manager import WorkspaceHandle


def test_build_payload_is_versioned_and_canonical() -> None:
    payload = build_payload(name="tested", before_rev_id=None, after_rev_id="abc")
    assert json.loads(payload) == {
        "v": OP_PAYLOAD_VERSION,
        "name": "tested",
        "before_rev_id": None,
        "after_rev_id": "abc",
    }
    assert payload == json.dumps(json.loads(payload), sort_keys=True, separators=(",", ":"))


def test_store_lists_in_insertion_order(workspace: WorkspaceHandle) -> None:
    conn = connect(workspace.paths.db_file)
    try:
        store = OpStore(conn)
        with transaction(conn):
            store.record(ws_id=workspace.workspace_id, kind=OpKind.REF_SET, payload={"name": "a"})
            store.record(ws_id=workspace.workspace_id, kind=OpKind.REF_SET, payload={"name": "b"})

        ops = store.list(workspace.workspace_id)
        # init 已写一条；随后两条按插入顺序排列
        assert [op.kind for op in ops] == [
            OpKind.WORKSPACE_INIT.value,
            OpKind.REF_SET.value,
            OpKind.REF_SET.value,
        ]
        assert [json.loads(op.payload_json)["name"] for op in ops[1:]] == ["a", "b"]
        assert store.head(workspace.workspace_id) == ops[-1]
    finally:
        conn.close()


def test_no_op_written_for_unchanged_snapshot(workspace: WorkspaceHandle) -> None:
    from skillforge_vm.watcher.engine import SnapshotEngine

    conn = connect(workspace.paths.db_file)
    try:
        before = OpStore(conn).count(workspace.workspace_id)
    finally:
        conn.close()

    SnapshotEngine(workspace).capture()

    conn = connect(workspace.paths.db_file)
    try:
        assert OpStore(conn).count(workspace.workspace_id) == before
    finally:
        conn.close()


def test_init_records_one_op(tmp_path: Path) -> None:
    from skillforge_vm.workspace.manager import WorkspaceManager

    skill = tmp_path / "s"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# A\n", encoding="utf-8")
    handle = WorkspaceManager(data_root=tmp_path / "data").init(skill).workspace

    conn = connect(handle.paths.db_file)
    try:
        ops = OpStore(conn).list(handle.workspace_id)
    finally:
        conn.close()
    assert len(ops) == 1
    assert ops[0].kind == OpKind.WORKSPACE_INIT.value