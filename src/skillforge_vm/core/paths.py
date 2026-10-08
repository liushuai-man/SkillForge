"""路径扫描共享工具。

M-03（对象库整树写入）与 M-02（稳定扫描）必须用同一套「哪些入口不跟随」的规则，
否则两次遍历结果不可比。AC-16：符号链接 / Windows junction 一律跳过，不越界读取。
"""

from __future__ import annotations

from pathlib import Path


def is_link_like(path: Path) -> bool:
    """是否为不应跟随的链接类入口：符号链接或 Windows junction/reparse point。"""
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction()) if callable(is_junction) else False
