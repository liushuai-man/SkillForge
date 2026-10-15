"""面向 Markdown/YAML/JSON 文本的确定性八类规则抽取。

规则只在有明确词法或章节证据时产出；无法归类的正文留给 L1/L2，避免猜测。
"""

from __future__ import annotations

import re
import unicodedata

from .models import SemanticElement, SemanticKind, SourceSpan

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_NUMBERED = re.compile(r"^\s*(?:\d+[.)]|[-*+]\s+\d+[.)])\s+")
_YAML_KEY = re.compile(r"^\s*[-*]?\s*([\w.-]+)\s*:\s*(.*)$", re.UNICODE)

_SECTION_RULES: tuple[tuple[SemanticKind, tuple[str, ...]], ...] = (
    (SemanticKind.EXAMPLE, ("example", "examples", "示例", "样例")),
    (SemanticKind.WORKFLOW, ("workflow", "steps", "process", "流程", "步骤")),
    (SemanticKind.TOOL, ("tool", "tools", "function", "api", "工具", "函数")),
    (SemanticKind.OUTPUT_FORMAT, ("output", "format", "schema", "输出", "格式")),
    (SemanticKind.PARAMETER, ("parameter", "parameters", "config", "参数", "配置")),
    (SemanticKind.CONSTRAINT, ("constraint", "rules", "限制", "约束", "规则")),
    (SemanticKind.CAPABILITY, ("capability", "abilities", "职责", "能力")),
    (SemanticKind.ROLE, ("role", "identity", "角色", "身份")),
)

_INLINE_RULES: tuple[tuple[SemanticKind, tuple[str, ...], str], ...] = (
    (
        SemanticKind.OUTPUT_FORMAT,
        ("output format", "response format", "json output", "输出格式", "返回格式"),
        "semantic.output_format.v1",
    ),
    (
        SemanticKind.CONSTRAINT,
        (
            "must ",
            "must not",
            "never ",
            "do not",
            "required",
            "禁止",
            "不得",
            "必须",
            "不要",
            "仅限",
        ),
        "semantic.constraint.v1",
    ),
    (
        SemanticKind.TOOL,
        ("tool ", "tools ", "function ", "api ", "工具", "函数调用", "接口"),
        "semantic.tool.v1",
    ),
    (
        SemanticKind.PARAMETER,
        ("parameter", "default", "option", "config", "参数", "默认值", "配置项"),
        "semantic.parameter.v1",
    ),
    (
        SemanticKind.ROLE,
        ("you are", "act as", "your role", "你是", "扮演", "角色是", "身份是"),
        "semantic.role.v1",
    ),
    (
        SemanticKind.CAPABILITY,
        ("can ", "able to", "responsible for", "capability", "能够", "可以", "负责", "职责"),
        "semantic.capability.v1",
    ),
)


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _section_kind(title: str) -> SemanticKind | None:
    value = _normalized(title)
    for kind, words in _SECTION_RULES:
        if any(word in value for word in words):
            return kind
    return None


def _inline_kind(text: str, section: SemanticKind | None) -> tuple[SemanticKind, str] | None:
    value = _normalized(text)
    if section is SemanticKind.EXAMPLE:
        return SemanticKind.EXAMPLE, "semantic.example.section.v1"
    if section is SemanticKind.WORKFLOW or _NUMBERED.match(text):
        return SemanticKind.WORKFLOW, "semantic.workflow.order.v1"
    yaml = _YAML_KEY.match(text)
    if yaml:
        key = _normalized(yaml.group(1))
        key_kind = _section_kind(key)
        if key_kind is not None:
            return key_kind, f"semantic.{key_kind.value}.key.v1"
        return SemanticKind.PARAMETER, "semantic.parameter.yaml_key.v1"
    for kind, words, rule_id in _INLINE_RULES:
        if any(word in value for word in words):
            return kind, rule_id
    if section is not None:
        return section, f"semantic.{section.value}.section.v1"
    return None


def extract_semantic_elements(path: str, data: bytes) -> list[SemanticElement]:
    """从原始 UTF-8 bytes 提取语义事实，并保留精确 byte span。"""
    data.decode("utf-8")  # 严格验证；降级决策由 M-05 统一处理
    elements: list[SemanticElement] = []
    offset = 0
    section_title: str | None = None
    section_kind: SemanticKind | None = None
    in_fence = False
    for index, raw_with_end in enumerate(data.splitlines(keepends=True)):
        raw = raw_with_end.rstrip(b"\r\n")
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = offset + leading
        end = offset + trailing
        if index == 0 and raw.startswith(b"\xef\xbb\xbf"):
            start = max(start, offset + 3)
        text = data[start:end].decode("utf-8") if end > start else ""
        offset += len(raw_with_end)
        if not text:
            continue
        if text.startswith("```") or text.startswith("~~~"):
            in_fence = not in_fence
            continue
        heading = _HEADING.match(text)
        if heading and not in_fence:
            section_title = heading.group("title")
            section_kind = _section_kind(section_title)
            continue
        classified = (
            (SemanticKind.EXAMPLE, "semantic.example.code.v1")
            if in_fence
            else _inline_kind(text, section_kind)
        )
        if classified is None:
            continue
        kind, rule_id = classified
        elements.append(
            SemanticElement(
                kind=kind,
                span=SourceSpan(path=path, start_byte=start, end_byte=end, text=text),
                rule_id=rule_id,
                normalized=_normalized(text),
                section=section_title,
            )
        )
    return elements
