"""SQLite 元数据库连接（WAL 模式）。

对象库以文件形式存放内容，SQLite 只放元数据（4.5）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .schema import SCHEMA_STATEMENTS


def connect(db_path: Path) -> sqlite3.Connection:
    """打开（必要时创建）元数据库，启用 WAL 与外键约束。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
    conn.executescript(";\n".join(SCHEMA_STATEMENTS))
    conn.commit()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """事务边界：成功提交，失败回滚。"""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise