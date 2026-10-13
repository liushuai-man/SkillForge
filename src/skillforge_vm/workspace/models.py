"""M-01 工作区配置模型。

原则「文件优先于界面」：所有配置都是文件，改文件即生效，不做配置界面。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..core.types import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_LARGE_FILE_THRESHOLD,
    DEFAULT_MAX_TEXT_BYTES,
    DEFAULT_PARSERS,
    DEFAULT_TEMP_RETENTION_DAYS,
    META_DB_FILENAME,
    OBJECTS_DIRNAME,
    WORKSPACE_CONFIG_FILENAME,
)


class IgnoreRules(BaseModel):
    """FR-01.5 忽略规则：不参与纳管的目录名与文件通配。"""

    dirs: list[str] = Field(default_factory=list)
    globs: list[str] = Field(default_factory=list)
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES

    def ignores(self, rel_path: Path) -> bool:
        """判断相对于工作区根的一条路径是否应被忽略。"""
        if any(part in self.dirs for part in rel_path.parts[:-1]):
            return True
        name = rel_path.name
        if name in self.dirs:
            return True
        text = rel_path.as_posix()
        return any(
            fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(text, pattern)
            for pattern in self.globs
        )


class ParserMap(BaseModel):
    """文件类型 → 解析器映射（M-05 / M-06 使用）。"""

    by_extension: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PARSERS))


class DedupConfig(BaseModel):
    """去重参数（TBD-04）。"""

    large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD
    chunk_size: int = DEFAULT_CHUNK_SIZE


class ReportPolicy(BaseModel):
    """报告保留策略（TBD-07）。"""

    temp_retention_days: int = DEFAULT_TEMP_RETENTION_DAYS


class WorkspaceConfig(BaseModel):
    """``workspace.json`` 的结构。"""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str
    root_path: str
    data_path: str
    created_at: str
    tool_version: str
    ignore: IgnoreRules
    parsers: ParserMap = Field(default_factory=ParserMap)
    semantic_unit_extensions: list[str] = Field(default_factory=list)
    dedup: DedupConfig = Field(default_factory=DedupConfig)
    report: ReportPolicy = Field(default_factory=ReportPolicy)


@dataclass(frozen=True)
class WorkspacePaths:
    """工作区相关的关键路径，全部落在数据目录内。"""

    root: Path
    data: Path
    config_file: Path
    db_file: Path
    objects_dir: Path

    @classmethod
    def for_data_path(cls, data_path: Path, root_path: Path) -> WorkspacePaths:
        data = Path(data_path)
        return cls(
            root=Path(root_path),
            data=data,
            config_file=data / WORKSPACE_CONFIG_FILENAME,
            db_file=data / META_DB_FILENAME,
            objects_dir=data / OBJECTS_DIRNAME,
        )