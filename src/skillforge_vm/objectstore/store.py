"""内容寻址对象库（M-03）。

- 命名：SHA-256；两级目录存放（``objects/ab/cd/<oid>``）。
- 压缩：zlib。
- 去重：内容哈希一致 → 同一份文件，重复写入为零写入（NFR-01）。
"""

from __future__ import annotations

import os
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ObjectNotFoundError, ObjectStoreNotWritableError
from ..core.types import (
    MODE_EXECUTABLE,
    MODE_REGULAR,
    MODE_TREE,
    STORAGE_ZLIB,
    ObjectType,
)
from .objects import (
    TreeEntry,
    decode_object,
    encode_meta,
    encode_object,
    encode_tree,
    object_id,
)

IgnoreFn = Callable[[Path], bool]


@dataclass(frozen=True)
class ObjectRecord:
    """一次对象写入的结果。``size`` 为主体未压缩大小。"""

    oid: str
    type: ObjectType
    size: int
    storage: str = STORAGE_ZLIB


class ObjectStore:
    def __init__(self, objects_dir: Path) -> None:
        self._objects_dir = Path(objects_dir)
        try:
            self._objects_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ObjectStoreNotWritableError(
                f"对象库不可写：{self._objects_dir}", detail=str(exc)
            ) from exc

    @property
    def objects_dir(self) -> Path:
        return self._objects_dir

    def object_path(self, oid: str) -> Path:
        """两级目录布局：``ab/cd/<oid>``。"""
        return self._objects_dir / oid[:2] / oid[2:4] / oid

    def has(self, oid: str) -> bool:
        return self.object_path(oid).is_file()

    def write(self, obj_type: ObjectType, body: bytes) -> ObjectRecord:
        """写入一个对象；内容已存在时不重复写盘。"""
        encoded = encode_object(obj_type, body)
        oid = object_id(obj_type, body)
        path = self.object_path(oid)
        if not path.is_file():
            self._atomic_write(path, zlib.compress(encoded))
        return ObjectRecord(oid=oid, type=obj_type, size=len(body))

    def write_blob(self, data: bytes) -> ObjectRecord:
        return self.write(ObjectType.BLOB, data)

    def write_blob_from_file(self, path: Path) -> ObjectRecord:
        return self.write_blob(Path(path).read_bytes())

    def write_tree(self, entries: list[TreeEntry]) -> ObjectRecord:
        return self.write(ObjectType.TREE, encode_tree(entries))

    def write_meta(self, payload: dict[str, Any]) -> ObjectRecord:
        return self.write(ObjectType.META, encode_meta(payload))

    def read_encoded(self, oid: str) -> bytes:
        """读取解压后的完整存储单元（头部 + 主体）。"""
        path = self.object_path(oid)
        if not path.is_file():
            raise ObjectNotFoundError(f"对象不存在：{oid}", detail=str(path))
        return zlib.decompress(path.read_bytes())

    def read(self, oid: str) -> tuple[ObjectType, bytes]:
        return decode_object(self.read_encoded(oid))

    def write_directory(
        self, root: Path, ignore: IgnoreFn | None = None
    ) -> tuple[ObjectRecord, list[ObjectRecord]]:
        """把一个目录整棵写入对象库。

        返回 ``(根 tree 记录, 本次涉及的全部对象记录)``；未变化的文件复用已有对象。
        """
        collected: list[ObjectRecord] = []
        root_record = self._write_dir(Path(root), Path("."), ignore, collected)
        return root_record, collected

    def _write_dir(
        self,
        root: Path,
        rel: Path,
        ignore: IgnoreFn | None,
        collected: list[ObjectRecord],
    ) -> ObjectRecord:
        current = root if rel == Path(".") else root / rel
        entries: list[TreeEntry] = []
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            child_rel = child.relative_to(root)
            if ignore is not None and ignore(child_rel):
                continue
            if child.is_dir() and not child.is_symlink():
                sub = self._write_dir(root, child_rel, ignore, collected)
                entries.append(TreeEntry(name=child.name, mode=MODE_TREE, oid=sub.oid))
            elif child.is_file():
                record = self.write_blob_from_file(child)
                collected.append(record)
                mode = (
                    MODE_EXECUTABLE
                    if child.stat().st_mode & 0o111
                    else MODE_REGULAR
                )
                entries.append(TreeEntry(name=child.name, mode=mode, oid=record.oid))
        tree = self.write_tree(entries)
        collected.append(tree)
        return tree

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()