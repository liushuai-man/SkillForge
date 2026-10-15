"""M-06/M-05 之间稳定、可序列化的语义交换模型。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class SemanticKind(StrEnum):
    ROLE = "role"
    CAPABILITY = "capability"
    CONSTRAINT = "constraint"
    TOOL = "tool"
    WORKFLOW = "workflow"
    EXAMPLE = "example"
    OUTPUT_FORMAT = "output_format"
    PARAMETER = "parameter"


class ChangeOp(StrEnum):
    ADD = "add"
    DELETE = "delete"
    MODIFY = "modify"
    MOVE = "move"


class SourceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    start_byte: int
    end_byte: int
    text: str


class SemanticElement(BaseModel):
    """单个修订中抽取出的语义事实；不是变化结论。"""

    model_config = ConfigDict(frozen=True)

    kind: SemanticKind
    span: SourceSpan
    rule_id: str
    normalized: str
    section: str | None = None


class SemanticChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    path: str
    kind: SemanticKind
    op: ChangeOp
    before: SourceSpan | None = None
    after: SourceSpan | None = None
    rule_id: str
