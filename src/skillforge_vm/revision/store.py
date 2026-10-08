"""M-04 修订、变更、引用与路径索引的读写。

- 读接口供 M-05 / M-10 / M-12 使用（不直查表）。
- 写接口只在业务提交入口的事务里调用（§4.1：一个事务提交对象索引、Revision、Change、引用与 Op）。
"""

from __future__ import annotations

import sqlite3

from ..core.errors import InvalidRequestError, RefNotFoundError, RevisionNotFoundError
from ..objectstore.store import FileBlob
from .models import Change, Ref, Revision

# 只读别名：``last`` 表示该工作区已提交 seq 最大的修订，禁止用户同名打标（§7.4）。
RESERVED_REF_NAMES = frozenset({"last"})


def _revision(row: sqlite3.Row) -> Revision:
    return Revision(
        rev_id=row["rev_id"],
        ws_id=row["ws_id"],
        change_id=row["change_id"],
        parent_rev_id=row["parent_rev_id"],
        root_tree_oid=row["root_tree_oid"],
        trigger=row["trigger"],
        source=row["source"],
        ts=row["ts"],
        seq=int(row["seq"]),
    )


def _change(row: sqlite3.Row) -> Change:
    return Change(
        change_id=row["change_id"],
        ws_id=row["ws_id"],
        first_rev=row["first_rev"],
        last_rev=row["last_rev"],
        summary=row["summary"],
        cluster_json=row["cluster_json"],
    )


def _ref(row: sqlite3.Row) -> Ref:
    return Ref(
        name=row["name"],
        ws_id=row["ws_id"],
        rev_id=row["rev_id"],
        updated_at=row["updated_at"],
    )


class RevisionStore:
    """基于一个 SQLite 连接读写 M-04 数据。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---- 修订 ----

    def head(self, ws_id: str) -> Revision | None:
        """当前已提交修订：工作区内 seq 最大的 Revision（``last`` 的物理含义）。"""
        row = self._conn.execute(
            "SELECT * FROM revision WHERE ws_id = ? ORDER BY seq DESC LIMIT 1",
            (ws_id,),
        ).fetchone()
        return _revision(row) if row is not None else None

    def get(self, ws_id: str, rev_id: str) -> Revision:
        row = self._conn.execute(
            "SELECT * FROM revision WHERE ws_id = ? AND rev_id = ?", (ws_id, rev_id)
        ).fetchone()
        if row is None:
            raise RevisionNotFoundError(f"修订不存在：{rev_id}", detail=rev_id)
        return _revision(row)

    def list(
        self, ws_id: str, *, max_seq: int | None = None, limit: int | None = None
    ) -> list[Revision]:
        """按稳定 ``seq`` 升序列出修订；``max_seq`` 固定一页上界（避免顺序漂移）。"""
        sql = "SELECT * FROM revision WHERE ws_id = ?"
        params: list[object] = [ws_id]
        if max_seq is not None:
            sql += " AND seq <= ?"
            params.append(max_seq)
        sql += " ORDER BY seq ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return [_revision(row) for row in self._conn.execute(sql, params)]

    def insert(self, revision: Revision) -> None:
        self._conn.execute(
            """
            INSERT INTO revision
                (rev_id, ws_id, change_id, parent_rev_id, root_tree_oid, trigger, source, ts, seq)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.rev_id,
                revision.ws_id,
                revision.change_id,
                revision.parent_rev_id,
                revision.root_tree_oid,
                revision.trigger,
                revision.source,
                revision.ts,
                revision.seq,
            ),
        )

    # ---- 变更 ----

    def get_change(self, ws_id: str, change_id: str) -> Change | None:
        row = self._conn.execute(
            "SELECT * FROM change WHERE ws_id = ? AND change_id = ?", (ws_id, change_id)
        ).fetchone()
        return _change(row) if row is not None else None

    def list_changes(self, ws_id: str) -> list[Change]:
        rows = self._conn.execute(
            "SELECT * FROM change WHERE ws_id = ? ORDER BY change_id ASC", (ws_id,)
        )
        return [_change(row) for row in rows]

    def start_change(self, ws_id: str, change_id: str, rev_id: str) -> None:
        """开一个变更：``first_rev`` 与 ``last_rev`` 均为首条修订。"""
        self._conn.execute(
            """
            INSERT INTO change (change_id, ws_id, first_rev, last_rev, summary, cluster_json)
            VALUES (?, ?, ?, ?, NULL, NULL)
            """,
            (change_id, ws_id, rev_id, rev_id),
        )

    def extend_change(self, ws_id: str, change_id: str, rev_id: str) -> None:
        """延续变更：推进 ``last_rev``，保留 ``first_rev``。"""
        self._conn.execute(
            "UPDATE change SET last_rev = ? WHERE ws_id = ? AND change_id = ?",
            (rev_id, ws_id, change_id),
        )

    # ---- 引用 ----

    def get_ref(self, ws_id: str, name: str) -> Ref:
        row = self._conn.execute(
            "SELECT * FROM ref WHERE ws_id = ? AND name = ?", (ws_id, name)
        ).fetchone()
        if row is None:
            raise RefNotFoundError(f"引用不存在：{name}", detail=name)
        return _ref(row)

    def list_refs(self, ws_id: str) -> list[Ref]:
        rows = self._conn.execute("SELECT * FROM ref WHERE ws_id = ? ORDER BY name ASC", (ws_id,))
        return [_ref(row) for row in rows]

    def set_ref(self, ref: Ref) -> None:
        """新增或移动命名引用；``last`` 为保留只读别名。"""
        if ref.name in RESERVED_REF_NAMES:
            raise InvalidRequestError(f"引用名 {ref.name} 为只读别名，不可打标", detail=ref.name)
        self._conn.execute(
            """
            INSERT INTO ref (name, ws_id, rev_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name, ws_id)
            DO UPDATE SET rev_id = excluded.rev_id, updated_at = excluded.updated_at
            """,
            (ref.name, ref.ws_id, ref.rev_id, ref.updated_at),
        )

    # ---- 路径索引 ----

    def index_paths(self, rev_id: str, files: list[FileBlob]) -> None:
        """记录该修订下每个文件路径对应的 blob（便于按路径查历史）。"""
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO blob_index (rev_id, path, oid, mode, size)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(rev_id, f.rel_path, f.oid, f.mode, f.size) for f in files],
        )
