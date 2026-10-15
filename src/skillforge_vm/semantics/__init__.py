"""M-06 规则语义抽取器的公共入口。"""

from .extractor import extract_semantic_elements
from .models import ChangeOp, SemanticChange, SemanticElement, SemanticKind, SourceSpan

__all__ = [
    "ChangeOp",
    "SemanticChange",
    "SemanticElement",
    "SemanticKind",
    "SourceSpan",
    "extract_semantic_elements",
]
