"""按路径、语义类型和章节证据聚类；每个单元只进入一个主聚类。"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from ..semantics.models import SemanticChange

_LABELS = {
    "role": "角色定义变化",
    "capability": "能力职责变化",
    "constraint": "约束规则变化",
    "tool": "工具调用变化",
    "workflow": "工作流程变化",
    "example": "示例变化",
    "output_format": "输出格式变化",
    "parameter": "参数配置变化",
}


def cluster_changes(changes: list[SemanticChange]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[SemanticChange]] = defaultdict(list)
    for change in sorted(changes, key=lambda item: item.id):
        top = change.path.split("/", 1)[0]
        grouped[(top, change.kind.value)].append(change)
    result = []
    for (top, kind), units in sorted(grouped.items()):
        unit_ids = sorted(item.id for item in units)
        digest = sha256((top + "\0" + kind + "\0" + "\0".join(unit_ids)).encode()).hexdigest()[:16]
        result.append(
            {
                "id": f"c-{digest}",
                "label": _LABELS[kind],
                "units": unit_ids,
            }
        )
    return result
