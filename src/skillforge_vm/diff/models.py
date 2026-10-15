"""M-05 的纯数据结果；M-08 负责将其组装为规范报告。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..semantics.models import SemanticChange


class Layer(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"

    @property
    def depth(self) -> int:
        return int(self.value[1])


class DiffResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: Layer
    metadata_files: list[dict[str, Any]] = Field(default_factory=list)
    text_hunks: list[dict[str, Any]] = Field(default_factory=list)
    structure_nodes: list[dict[str, Any]] = Field(default_factory=list)
    semantic_units: list[SemanticChange] = Field(default_factory=list)
    needs_review: list[dict[str, Any]] = Field(default_factory=list)
    degraded: list[dict[str, str]] = Field(default_factory=list)
