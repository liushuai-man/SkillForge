"""M-03 对象库骨架的验收用例：内容寻址、zlib 压缩、两级目录、去重。"""

from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from skillforge_vm.core.errors import ObjectCorruptedError, ObjectNotFoundError
from skillforge_vm.core.hashing import sha256_hex
from skillforge_vm.core.types import MODE_REGULAR, MODE_TREE, ObjectType
from skillforge_vm.objectstore.objects import (
    TreeEntry,
    decode_meta,
    decode_tree,
    encode_object,
)
from skillforge_vm.objectstore.store import ObjectStore


@pytest.fixture()
def store(tmp_path: Path) -> ObjectStore:
    return ObjectStore(tmp_path / "objects")


def test_blob_is_content_addressed(store: ObjectStore) -> None:
    data = b"# SKILL\n"
    record = store.write_blob(data)

    assert record.type == ObjectType.BLOB
    assert record.size == len(data)
    assert record.oid == sha256_hex(encode_object(ObjectType.BLOB, data))


def test_object_lands_in_two_level_dir_and_is_compressed(store: ObjectStore) -> None:
    data = b"hello skillforge"
    record = store.write_blob(data)
    path = store.object_path(record.oid)

    assert path.is_file()
    assert path.parent.name == record.oid[2:4]
    assert path.parent.parent.name == record.oid[:2]
    assert zlib.decompress(path.read_bytes()) == encode_object(ObjectType.BLOB, data)


def test_read_roundtrip(store: ObjectStore) -> None:
    data = "约束：必须输出 JSON".encode()
    record = store.write_blob(data)

    obj_type, body = store.read(record.oid)
    assert obj_type == ObjectType.BLOB
    assert body == data


def test_identical_content_is_stored_once(store: ObjectStore) -> None:
    first = store.write_blob(b"same content")
    second = store.write_blob(b"same content")

    assert first.oid == second.oid
    files = [p for p in store.objects_dir.rglob("*") if p.is_file()]
    assert len(files) == 1


def test_tree_id_is_order_independent(store: ObjectStore) -> None:
    a = TreeEntry(name="b.md", mode=MODE_REGULAR, oid="0" * 64)
    b = TreeEntry(name="a.md", mode=MODE_REGULAR, oid="1" * 64)

    assert store.write_tree([a, b]).oid == store.write_tree([b, a]).oid


def test_meta_roundtrip(store: ObjectStore) -> None:
    payload = {"workspace_id": "abc", "seq": 1}
    record = store.write_meta(payload)

    obj_type, body = store.read(record.oid)
    assert obj_type == ObjectType.META
    assert decode_meta(body) == payload


def test_read_missing_object_raises(store: ObjectStore) -> None:
    with pytest.raises(ObjectNotFoundError):
        store.read("f" * 64)


def test_write_directory_writes_blobs_and_trees(store: ObjectStore, tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    (skill / "sub").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# a\n", encoding="utf-8")
    (skill / "sub" / "b.yaml").write_text("k: v\n", encoding="utf-8")

    root, records = store.write_directory(skill)

    assert root.type == ObjectType.TREE
    assert sum(1 for r in records if r.type == ObjectType.BLOB) == 2
    assert sum(1 for r in records if r.type == ObjectType.TREE) == 2  # 根 tree + sub tree

    entries = decode_tree(store.read(root.oid)[1])
    assert [e.name for e in entries] == ["SKILL.md", "sub"]
    assert next(e for e in entries if e.name == "sub").mode == MODE_TREE


def test_write_directory_respects_ignore(store: ObjectStore, tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "keep.md").write_text("keep", encoding="utf-8")
    (skill / "skip.tmp").write_text("skip", encoding="utf-8")

    _, records = store.write_directory(skill, lambda rel: rel.name.endswith(".tmp"))

    assert sum(1 for r in records if r.type == ObjectType.BLOB) == 1


def test_truncated_compression_is_corrupted(store: ObjectStore) -> None:
    record = store.write_blob(b"payload")
    path = store.object_path(record.oid)
    path.write_bytes(path.read_bytes()[:5])  # 截断的压缩流

    with pytest.raises(ObjectCorruptedError):
        store.read_encoded(record.oid)


def test_bad_header_or_length_is_corrupted(store: ObjectStore) -> None:
    malformed = b"blob 999\x00abc"  # 头部声明 999，主体只有 3 字节
    oid = sha256_hex(malformed)
    path = store.object_path(oid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(malformed))

    with pytest.raises(ObjectCorruptedError):
        store.read(oid)


def test_valid_object_replaced_by_another_is_corrupted(store: ObjectStore) -> None:
    first = store.write_blob(b"first content")
    second = store.write_blob(b"second content")
    # 把另一个合法压缩对象的字节放到 first 的路径：合法压缩但内容被替换，必须识别
    store.object_path(first.oid).write_bytes(store.object_path(second.oid).read_bytes())

    with pytest.raises(ObjectCorruptedError):
        store.read(first.oid)