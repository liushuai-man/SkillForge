"""跨模块共享的常量与枚举。

只放「被多个模块引用」的定义，模块私有常量留在各自模块内。
"""

from __future__ import annotations

from enum import StrEnum
from importlib import metadata


class ObjectType(StrEnum):
    """内容寻址对象库的三层对象（M-03）。"""

    BLOB = "blob"  # 文件内容，不含文件名
    TREE = "tree"  # 目录结构：名字 + 模式 + 指向 blob / 子 tree
    META = "meta"  # 快照元数据：父修订、时间、触发方式、来源


# 文件模式（借鉴 Git 的 tree 条目约定）
MODE_TREE = "40000"
MODE_REGULAR = "100644"
MODE_EXECUTABLE = "100755"

# 对象压缩方式：zlib
STORAGE_ZLIB = "zlib"

# 工作区数据目录内的固定文件名
WORKSPACE_CONFIG_FILENAME = "workspace.json"
OBJECTS_DIRNAME = "objects"
META_DB_FILENAME = "meta.sqlite3"

# FR-01.5 默认忽略：VCS 元数据、依赖目录、构建产物
DEFAULT_IGNORE_DIRS: tuple[str, ...] = (
    ".git",
    "node_modules",
    "artifacts",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)
DEFAULT_IGNORE_GLOBS: tuple[str, ...] = (
    "*.tmp",
    "*.temp",
    "*~",
    ".DS_Store",
    "Thumbs.db",
    "*.pyc",
    "*.log",
)

# TBD-04：文本 ≤ 2 MB 进文本层；二进制 > 1 MB 走内容定义分块（CDC，后续落地）
DEFAULT_MAX_TEXT_BYTES = 2 * 1024 * 1024
DEFAULT_LARGE_FILE_THRESHOLD = 1024 * 1024
DEFAULT_CHUNK_SIZE = 64 * 1024

# TBD-07：临时报告保留 30 天
DEFAULT_TEMP_RETENTION_DAYS = 30

# M-01：文件类型 → 解析器映射
DEFAULT_PARSERS: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".txt": "text",
    ".prompt": "text",
    ".tmpl": "text",
}


def tool_version() -> str:
    """版本管理器自身的版本号，写进 workspace.json 与报告，用于可复现约束。"""
    try:
        return metadata.version("skillforge-vm")
    except metadata.PackageNotFoundError:  # 未安装、直接跑源码时
        return "0.1.0"