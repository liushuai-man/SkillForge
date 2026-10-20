"""M-09 操作日志公共模型。

每个操作记录不可变的历史事实（kind + payload）；``op`` 表结构见设计 §4.5。
``payload_json`` 的格式版本由 TBD-09 草案冻结（见设计 §2.7 / 实现契约 §2.3），
此处只承载版本化载荷，不表示 undo 文件回写已实现。
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# 载荷格式版本：变更语义时需要提升，并在 TBD-09 记录迁移。
OP_PAYLOAD_VERSION = 1


class OpKind(StrEnum):
    """操作类型（M-09）。"""

    WORKSPACE_INIT = "workspace.init"
    SNAPSHOT = "snapshot"
    REF_SET = "ref.set"
    RESTORE_PLAN = "restore.plan"
    RESTORE_BEGIN = "restore.begin"
    RESTORE_DONE = "restore.done"


def new_op_id() -> str:
    """操作标识：``OP-`` 前缀，内容不参与任何可复现键，允许随机。"""
    return f"OP-{uuid.uuid4().hex}"


class Op(BaseModel):
    """一条操作日志。``payload_json`` 为已序列化的规范 JSON 字符串。"""

    model_config = ConfigDict(frozen=True)

    op_id: str
    ws_id: str
    parent_op_id: str | None = None
    kind: str
    payload_json: str
    ts: str
