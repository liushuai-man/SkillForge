"""对象序列化与反序列化（M-03）。

对象 = 头部 + 主体，头部形如 ``<type> <size>\\0``；对象 ID 取整个编码的 SHA-256。
tree / meta 主体使用规范化 JSON（键排序、无多余空白），保证「同样内容 → 同样 ID」，
这是可复现约束（NFR-04）的地基。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.errors import ObjectCorruptedError
from ..core.hashing import sha256_hex
from ..core.types import ObjectType


def canonical_json(payload: Any) -> bytes:
    """确定性 JSON 编码：键排序、紧凑分隔符、保留非 ASCII。"""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def encode_object(obj_type: ObjectType, body: bytes) -> bytes:
    """编码为对象库中的存储单元：``<type> <size>\\0<body>``。"""
    header = f"{obj_type.value} {len(body)}".encode("ascii") + b"\x00"
    return header + body


def decode_object(raw: bytes) -> tuple[ObjectType, bytes]:
    """解码存储单元，校验头部与主体长度。"""
    nul = raw.find(b"\x00")
    if nul < 0:
        raise ObjectCorruptedError("对象缺少头部终止符")
    header = raw[:nul].decode("ascii", errors="replace")
    type_str, _, size_str = header.partition(" ")
    try:
        obj_type = ObjectType(type_str)
        size = int(size_str)
    except ValueError as exc:
        raise ObjectCorruptedError(f"对象头部非法：{header!r}") from exc
    body = raw[nul + 1 :]
    if len(body) != size:
        raise ObjectCorruptedError(
            f"对象主体长度不符：头部声明 {size}，实际 {len(body)}"
        )
    return obj_type, body


def object_id(obj_type: ObjectType, body: bytes) -> str:
    """内容寻址的对象 ID：整个编码的 SHA-256。"""
    return sha256_hex(encode_object(obj_type, body))


@dataclass(frozen=True)
class TreeEntry:
    """tree 的一条目录条目。"""

    name: str
    mode: str
    oid: str


def encode_tree(entries: list[TreeEntry]) -> bytes:
    """编码 tree。条目按名字的 UTF-8 字节序排序，保证顺序无关的确定性。"""
    ordered = sorted(entries, key=lambda entry: entry.name.encode("utf-8"))
    return canonical_json(
        {"entries": [{"name": e.name, "mode": e.mode, "oid": e.oid} for e in ordered]}
    )


def decode_tree(body: bytes) -> list[TreeEntry]:
    try:
        payload = json.loads(body.decode("utf-8"))
        return [
            TreeEntry(name=item["name"], mode=item["mode"], oid=item["oid"])
            for item in payload["entries"]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ObjectCorruptedError("tree 主体无法解析") from exc


def encode_meta(payload: dict[str, Any]) -> bytes:
    """编码快照元数据。"""
    return canonical_json(payload)


def decode_meta(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise ObjectCorruptedError("meta 主体无法解析") from exc
    if not isinstance(payload, dict):
        raise ObjectCorruptedError("meta 主体必须是 JSON 对象")
    return payload