"""通过对象公开读取接口展开不可变修订树；恢复消费者不自行解析存储路径。"""

from pathlib import PurePosixPath, PureWindowsPath

from ..core.errors import ObjectCorruptedError
from ..core.types import MODE_EXECUTABLE, MODE_REGULAR, MODE_TREE, ObjectType
from ..objectstore.objects import decode_tree
from ..objectstore.store import ObjectStore


def preview_blob(store: ObjectStore, oid: str) -> dict:
    """Read immutable bytes; never replace invalid text or interpret it as HTML."""
    kind, data = store.read(oid)
    if kind != ObjectType.BLOB:
        raise ObjectCorruptedError("文件对象类型错误", detail=oid)
    result = {"size": len(data), "content": None, "reason": None}
    if len(data) > 2 * 1024 * 1024:
        result["reason"] = "文件超过 2 MiB，暂不预览"
        return result
    try:
        text = data.decode("utf-8-sig")
        if "\x00" in text:
            raise UnicodeError()
        result["content"] = text
    except UnicodeError:
        result["reason"] = "二进制或非 UTF-8 文件，暂不预览"
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
