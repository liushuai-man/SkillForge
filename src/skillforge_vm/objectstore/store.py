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

from ..core.errors import ObjectCorruptedError, ObjectNotFoundError, ObjectStoreNotWritableError
from ..core.hashing import sha256_hex
from ..core.paths import is_link_like
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


@dataclass(frozen=True)
class FileBlob:
    """一个文件在本次 tree 中的落点（M-04 ``blob_index`` 的数据来源）。"""

    rel_path: str
    oid: str
    mode: str
    size: int


@dataclass(frozen=True)
class DirectoryWriteResult:
    """整棵目录写入对象库的明细。"""

    root: ObjectRecord
    records: list[ObjectRecord]
    files: list[FileBlob]


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
        """读取并校验一个对象的完整存储单元（头部 + 主体）。

        依次验证存在性、解压、OID（完整编码哈希）。按契约「合法压缩但内容被替换
        也必须识别」，任何不匹配都报 ``object_corrupted`` 而不是返回错误内容（AC-03）。
        """
        path = self.object_path(oid)
        if not path.is_file():
            raise ObjectNotFoundError(f"对象不存在：{oid}", detail=str(path))
        try:
            encoded = zlib.decompress(path.read_bytes())
        except zlib.error as exc:
            raise ObjectCorruptedError(f"对象解压失败：{oid}", detail=str(exc)) from exc
        actual = sha256_hex(encoded)
        if actual != oid:
            raise ObjectCorruptedError(
                f"对象内容与 OID 不符：期望 {oid}，实际 {actual}", detail=str(path)
            )
        return encoded

    def read(self, oid: str) -> tuple[ObjectType, bytes]:
        return decode_object(self.read_encoded(oid))

    def write_directory(
        self, root: Path, ignore: IgnoreFn | None = None
    ) -> tuple[ObjectRecord, list[ObjectRecord]]:
        """把一个目录整棵写入对象库。

        返回 ``(根 tree 记录, 本次涉及的全部对象记录)``；未变化的文件复用已有对象。
        """
        result = self.write_directory_detailed(root, ignore)
        return result.root, result.records

    def write_directory_detailed(
        self, root: Path, ignore: IgnoreFn | None = None
    ) -> DirectoryWriteResult:
        """同 ``write_directory``，但额外返回文件路径到 blob 的映射（供 M-04 建索引）。"""
        collected: list[ObjectRecord] = []
        files: list[FileBlob] = []
        root_record = self._write_dir(Path(root), Path("."), ignore, collected, files)
        return DirectoryWriteResult(root=root_record, records=collected, files=files)

    def _write_dir(
        self,
        root: Path,
        rel: Path,
        ignore: IgnoreFn | None,
        collected: list[ObjectRecord],
        files: list[FileBlob],
    ) -> ObjectRecord:
        current = root if rel == Path(".") else root / rel
        entries: list[TreeEntry] = []
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            child_rel = child.relative_to(root)
            if ignore is not None and ignore(child_rel):
                continue
            if is_link_like(child):
                continue  # AC-16：不跟随符号链接 / junction
            if child.is_dir():
                sub = self._write_dir(root, child_rel, ignore, collected, files)
                entries.append(TreeEntry(name=child.name, mode=MODE_TREE, oid=sub.oid))
            elif child.is_file():
                record = self.write_blob_from_file(child)
                collected.append(record)
                mode = MODE_EXECUTABLE if child.stat().st_mode & 0o111 else MODE_REGULAR
                files.append(
                    FileBlob(
                        rel_path=child_rel.as_posix(),
                        oid=record.oid,
                        mode=mode,
                        size=record.size,
                    )
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
