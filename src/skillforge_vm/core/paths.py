"""路径扫描共享工具。

M-03（对象库整树写入）与 M-02（稳定扫描）必须用同一套「哪些入口不跟随」的规则，
否则两次遍历结果不可比。AC-16：符号链接 / Windows junction 一律跳过，不越界读取。
"""

from __future__ import annotations

import logging
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def is_link_like(path: Path) -> bool:
    """是否为不应跟随的链接类入口：符号链接或 Windows junction/reparse point。"""
    metadata = path.lstat()
    linked = stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    if linked:
        logger.warning("跳过链接或 reparse point，不纳管其内容：%s", path)
    return linked
