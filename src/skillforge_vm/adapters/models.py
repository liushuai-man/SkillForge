"""外部行为对比未来接入 M-08 时使用的最小、无执行代码契约。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class BehaviorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    adapter_id: str
    adapter_version: str
    status: str
    summary: str
    evidence: list[dict[str, object]]


class BehaviorAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def compare(self, *, base_rev: str | None, head_rev: str) -> BehaviorResult: ...
