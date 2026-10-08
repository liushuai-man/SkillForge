"""M-04 修订与变更的身份编码。

- Revision 身份：``rev_id`` 即修订 meta 对象的 OID，meta 规范 JSON 固定包含
  ``schema_version/ws_id/change_id/parent_rev_id/root_tree_oid/trigger/source/ts/seq``，
  不包含自身 ID（§7.2）。
- Change 身份：32 字节随机数，每个十六进制半字节映射到固定字母表，前缀 ``CHG-``（§7.3）。
"""

from __future__ import annotations

import os
import re

from ..core.types import (
    CHANGE_ID_ALPHABET,
    CHANGE_ID_BYTES,
    CHANGE_ID_PREFIX,
    REVISION_META_SCHEMA_VERSION,
    SnapshotSource,
    SnapshotTrigger,
)

REVISION_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def new_change_id() -> str:
    """生成一个新的稳定 Change ID（正文 64 字符）。"""
    raw = os.urandom(CHANGE_ID_BYTES)
    body = "".join(CHANGE_ID_ALPHABET[byte >> 4] + CHANGE_ID_ALPHABET[byte & 0x0F] for byte in raw)
    return f"{CHANGE_ID_PREFIX}{body}"


def is_revision_id(text: str) -> bool:
    """是否为完整的 Revision ID（小写十六进制 64 位）。"""
    return REVISION_ID_PATTERN.match(text) is not None


def revision_meta_payload(
    *,
    ws_id: str,
    change_id: str,
    parent_rev_id: str | None,
    root_tree_oid: str,
    trigger: SnapshotTrigger | str,
    source: SnapshotSource | str,
    ts: str,
    seq: int,
) -> dict[str, object]:
    """构造修订 meta 对象的规范载荷（键排序由对象编码负责）。"""
    return {
        "schema_version": REVISION_META_SCHEMA_VERSION,
        "ws_id": ws_id,
        "change_id": change_id,
        "parent_rev_id": parent_rev_id,
        "root_tree_oid": root_tree_oid,
        "trigger": SnapshotTrigger(trigger).value,
        "source": SnapshotSource(source).value,
        "ts": ts,
        "seq": seq,
    }
