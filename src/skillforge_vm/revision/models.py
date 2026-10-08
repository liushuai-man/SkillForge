"""M-04 公共模型：Revision / Change / Ref。

这些模型是 M-05、M-10、M-12 读取历史的交换结构；字段与设计 §4.5 的表字段一致。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Revision(BaseModel):
    """一次不可变修订事件（``rev_id`` 为 meta 对象 OID，不是 tree OID）。"""

    model_config = ConfigDict(frozen=True)

    rev_id: str
    ws_id: str
    change_id: str
    parent_rev_id: str | None = None
    root_tree_oid: str
    trigger: str
    source: str
    ts: str
    seq: int


class Change(BaseModel):
    """一次逻辑修改，跨多个 Revision 保持稳定 ID。"""

    model_config = ConfigDict(frozen=True)

    change_id: str
    ws_id: str
    first_rev: str
    last_rev: str
    summary: str | None = None
    cluster_json: str | None = None


class Ref(BaseModel):
    """用户命名指针（锚点）。``last`` 为只读别名，不允许作为普通引用写入。"""

    model_config = ConfigDict(frozen=True)

    name: str
    ws_id: str
    rev_id: str
    updated_at: str
