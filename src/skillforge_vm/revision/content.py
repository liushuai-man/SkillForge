"""通过对象公开读取接口展开不可变修订树；恢复消费者不自行解析存储路径。"""

from pathlib import PurePosixPath, PureWindowsPath

from ..core.errors import InvalidRequestError, ObjectCorruptedError
from ..core.types import MODE_EXECUTABLE, MODE_REGULAR, MODE_TREE, ObjectType
from ..objectstore.objects import decode_tree
from ..objectstore.store import ObjectStore
from .store import RevisionStore


def read_revision_file(
    revisions: RevisionStore,
    objects: ObjectStore,
    ws_id: str,
    rev_id: str,
    path: str,
    *,
    max_text_bytes: int,
) -> dict:
    """只从已校验归属的历史索引读取全文，绝不访问工作区磁盘。"""
    if (
        not path
        or "\\" in path
        or "\x00" in path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).drive
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise InvalidRequestError("请提供历史中的相对文件路径")
    revisions.get(ws_id, rev_id)
    entry = revisions.files(rev_id).get(path)
    result = {
        "revision": rev_id,
        "path": path,
        "status": "absent",
        "size": 0,
        "mode": None,
        "text": None,
    }
    if entry is None:
        return result
    oid, mode = entry
    kind, data = objects.read(oid)
    if kind != ObjectType.BLOB:
        raise ObjectCorruptedError("历史文件对象类型错误", detail=path)
    result.update(size=len(data), mode=mode)
    if len(data) > max_text_bytes:
        result["status"] = "too_large"
        return result
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        result["status"] = "binary"
        return result
    if "\x00" in text:
        result["status"] = "binary"
        return result
    result.update(status="text", text=text)
    return result


def safe_relative(path: str) -> None:
    parts = path.split("/")
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or any(
            p in ("", ".", "..")
            or any(char in '\\:<>"|?*' or ord(char) < 32 for char in p)
            or p.endswith((".", " "))
            or PureWindowsPath(p).is_reserved()
            for p in parts
        )
    ):
        raise ObjectCorruptedError("修订包含不安全或不可移植的路径", detail=path)


def read_tree(store: ObjectStore, root_oid: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    files: dict[str, tuple[str, str]] = {}
    directories: list[str] = []
    seen: set[str] = set()

    def walk(oid: str, parent: str, depth: int) -> None:
        if depth > 128:
            raise ObjectCorruptedError("目录嵌套超过恢复支持范围")
        kind, data = store.read(oid)
        if kind != ObjectType.TREE:
            raise ObjectCorruptedError("目录对象类型错误", detail=oid)
        for entry in decode_tree(data):
            safe_relative(entry.name)
            if "/" in entry.name:
                raise ObjectCorruptedError("tree 条目必须是单个路径分量")
            path = f"{parent}/{entry.name}" if parent else entry.name
            key = path.casefold()
            if key in seen:
                raise ObjectCorruptedError("恢复不支持重名或大小写冲突路径", detail=path)
            seen.add(key)
            if entry.mode == MODE_TREE:
                directories.append(path)
                walk(entry.oid, path, depth + 1)
            elif entry.mode in (MODE_REGULAR, MODE_EXECUTABLE):
                if store.read(entry.oid)[0] != ObjectType.BLOB:
                    raise ObjectCorruptedError("文件对象类型错误", detail=path)
                files[path] = (entry.oid, entry.mode)
            else:
                raise ObjectCorruptedError("恢复不支持此文件模式", detail=path)

    walk(root_oid, "", 0)
    return files, sorted(directories)
