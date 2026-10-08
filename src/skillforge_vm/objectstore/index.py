"""对象索引：``object`` 表的读写（M-03）。

对象内容在文件系统里，这里是它的索引与引用计数载体。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from .store import ObjectRecord


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ObjectIndex:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, record: ObjectRecord, *, refcount: int = 0) -> bool:
        """登记一个对象；已登记过则不重复插入。返回是否为新增。"""
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO object (oid, type, size, storage, refcount, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (record.oid, record.type.value, record.size, record.storage, refcount, _now_iso()),
        )
        return cursor.rowcount > 0

    def record_many(self, records: list[ObjectRecord], *, refcount: int = 0) -> int:
        """批量登记，返回新增条数。"""
        return sum(1 for record in records if self.record(record, refcount=refcount))

    def get(self, oid: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM object WHERE oid = ?", (oid,)).fetchone()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM object").fetchone()
        return int(row["n"])