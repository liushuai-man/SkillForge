"""M-09 操作日志读写。

写入只在业务提交入口的事务内进行（§4.1 / §2.2：与 Revision/Change 同一事务）。
读取按 SQLite 隐式 ``rowid`` 升序稳定排序（表无 seq 列）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ..objectstore.objects import canonical_json
from .models import OP_PAYLOAD_VERSION, Op, OpKind, new_op_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_op(row: sqlite3.Row) -> Op:
    return Op(
        op_id=row["op_id"],
        ws_id=row["ws_id"],
        parent_op_id=row["parent_op_id"],
        kind=row["kind"],
        payload_json=row["payload_json"],
        ts=row["ts"],
    )


def build_payload(**fields: Any) -> str:
    """构造版本化载荷：``{"v": 1, ...}``（键排序由 canonical_json 保证）。"""
    return canonical_json({"v": OP_PAYLOAD_VERSION, **fields}).decode("utf-8")


class OpStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(
        self,
        *,
        ws_id: str,
        kind: OpKind | str,
        payload: dict[str, Any],
        parent_op_id: str | None = None,
        ts: str | None = None,
    ) -> Op:
        """写入一条操作日志；不提交，由外层事务统一提交。"""
        op = Op(
            op_id=new_op_id(),
            ws_id=ws_id,
            parent_op_id=parent_op_id,
            kind=OpKind(kind).value,
            payload_json=build_payload(**payload),
            ts=ts or _now_iso(),
        )
        self.insert(op)
        return op

    def insert(self, op: Op) -> None:
        self._conn.execute(
            """
            INSERT INTO op (op_id, ws_id, parent_op_id, kind, payload_json, ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (op.op_id, op.ws_id, op.parent_op_id, op.kind, op.payload_json, op.ts),
        )

    def list(self, ws_id: str, *, limit: int | None = None) -> list[Op]:
        """按插入顺序（rowid 升序）列出该工作区的操作。"""
        sql = "SELECT * FROM op WHERE ws_id = ? ORDER BY rowid ASC"
        params: list[object] = [ws_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_row_to_op(row) for row in self._conn.execute(sql, params)]

    def head(self, ws_id: str) -> Op | None:
        """最近一次操作（当前 Op 指针的派生来源，见 TBD-09）。"""
        row = self._conn.execute(
            "SELECT * FROM op WHERE ws_id = ? ORDER BY rowid DESC LIMIT 1", (ws_id,)
        ).fetchone()
        return _row_to_op(row) if row is not None else None

    def count(self, ws_id: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM op WHERE ws_id = ?", (ws_id,)
        ).fetchone()
        return int(row["n"])

    def get(self, ws_id: str, op_id: str) -> Op | None:
        row = self._conn.execute(
            "SELECT * FROM op WHERE ws_id = ? AND op_id = ?", (ws_id, op_id)
        ).fetchone()
        return _row_to_op(row) if row else None

    def latest_restore(self, ws_id: str, *, completed: bool = False) -> Op | None:
        kinds = (OpKind.RESTORE_DONE,) if completed else (OpKind.RESTORE_BEGIN, OpKind.RESTORE_DONE)
        marks = ",".join("?" for _ in kinds)
        row = self._conn.execute(
            f"SELECT * FROM op WHERE ws_id = ? AND kind IN ({marks}) ORDER BY rowid DESC LIMIT 1",
            (ws_id, *kinds),
        ).fetchone()
        return _row_to_op(row) if row else None

    def pending_restore(self, ws_id: str) -> str | None:
        last = self.latest_restore(ws_id)
        if last and last.kind == OpKind.RESTORE_BEGIN:
            return json.loads(last.payload_json)["plan_id"]
        return None

    def restore_done(self, ws_id: str, plan_id: str) -> Op | None:
        row = self._conn.execute(
            "SELECT * FROM op WHERE ws_id = ? AND parent_op_id = ? AND kind = ?",
            (ws_id, plan_id, OpKind.RESTORE_DONE),
        ).fetchone()
        return _row_to_op(row) if row else None
