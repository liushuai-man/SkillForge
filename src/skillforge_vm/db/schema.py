"""SQLite 表结构（对应设计文档 4.5 数据模型）。

本阶段（第 1 周）只建表；各表的写入逻辑随对应模块落地。
"""

from __future__ import annotations

SCHEMA_STATEMENTS: tuple[str, ...] = (
    # 工作区（M-01）
    """
    CREATE TABLE IF NOT EXISTS workspace (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        root_path   TEXT NOT NULL,
        data_path   TEXT NOT NULL,
        config_json TEXT NOT NULL,
        created_at  TEXT NOT NULL
    )
    """,
    # 对象索引（M-03）
    """
    CREATE TABLE IF NOT EXISTS object (
        oid        TEXT PRIMARY KEY,
        type       TEXT NOT NULL,
        size       INTEGER NOT NULL,
        storage    TEXT NOT NULL,
        refcount   INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    # 快照 / 修订（M-04）
    """
    CREATE TABLE IF NOT EXISTS revision (
        rev_id        TEXT PRIMARY KEY,
        ws_id         TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        change_id     TEXT NOT NULL,
        parent_rev_id TEXT,
        root_tree_oid TEXT NOT NULL,
        trigger       TEXT NOT NULL,
        source        TEXT NOT NULL,
        ts            TEXT NOT NULL,
        seq           INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_revision_ws_seq ON revision(ws_id, seq)",
    # 变更（M-04）
    """
    CREATE TABLE IF NOT EXISTS change (
        change_id    TEXT PRIMARY KEY,
        ws_id        TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        first_rev    TEXT NOT NULL,
        last_rev     TEXT NOT NULL,
        summary      TEXT,
        cluster_json TEXT
    )
    """,
    # 命名引用 / 锚点（M-04）
    """
    CREATE TABLE IF NOT EXISTS ref (
        name       TEXT NOT NULL,
        ws_id      TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        rev_id     TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (name, ws_id)
    )
    """,
    # 按路径查历史（M-04）
    """
    CREATE TABLE IF NOT EXISTS blob_index (
        rev_id TEXT NOT NULL,
        path   TEXT NOT NULL,
        oid    TEXT NOT NULL,
        mode   TEXT NOT NULL,
        size   INTEGER NOT NULL,
        PRIMARY KEY (rev_id, path)
    )
    """,
    # 差异缓存（M-05）
    """
    CREATE TABLE IF NOT EXISTS diff_cache (
        cache_key    TEXT PRIMARY KEY,
        layer        TEXT NOT NULL,
        algo_version TEXT NOT NULL,
        result_json  TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    # 对比报告（M-08）
    """
    CREATE TABLE IF NOT EXISTS report (
        report_id    TEXT PRIMARY KEY,
        ws_id        TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        base_rev     TEXT,
        head_rev     TEXT NOT NULL,
        algo_version TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )
    """,
    # 操作日志（M-09）
    """
    CREATE TABLE IF NOT EXISTS op (
        op_id        TEXT PRIMARY KEY,
        ws_id        TEXT NOT NULL REFERENCES workspace(id) ON DELETE CASCADE,
        parent_op_id TEXT,
        kind         TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        ts           TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_op_ws_ts ON op(ws_id, ts)",
    # 可选注解（M-08 / FR-05.3）
    """
    CREATE TABLE IF NOT EXISTS note (
        id         TEXT PRIMARY KEY,
        rev_id     TEXT NOT NULL,
        text       TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)

TABLE_NAMES: tuple[str, ...] = (
    "workspace",
    "object",
    "revision",
    "change",
    "ref",
    "blob_index",
    "diff_cache",
    "report",
    "op",
    "note",
)