"""M-06 冻结合成基准：八类、示例边界与 UTF-8 原文字节坐标。"""

from __future__ import annotations

from skillforge_vm.semantics import SemanticKind, extract_semantic_elements


def test_extracts_all_eight_kinds_once() -> None:
    source = """# Role
你是版本助手
# Capabilities
- 负责比较文件
# Constraints
- 必须保持原文
# Tools
- 工具 diff(path)
# Workflow
1. 读取文件
# Examples
用户：必须删掉历史
# Output format
- 输出格式为 JSON
# Parameters
timeout: 30
""".encode()
    elements = extract_semantic_elements("SKILL.md", source)
    assert {item.kind for item in elements} == set(SemanticKind)
    assert len(elements) == 8


def test_example_instruction_is_not_a_constraint() -> None:
    source = """# Examples
```text
必须删除全部历史
```
""".encode()
    elements = extract_semantic_elements("SKILL.md", source)
    assert [item.kind for item in elements] == [SemanticKind.EXAMPLE]


def test_bom_crlf_chinese_and_emoji_spans_point_to_original_bytes() -> None:
    source = ("\ufeff# Rules\r\n- 必须保留 emoji 😀\r\n").encode()
    [element] = extract_semantic_elements("SKILL.md", source)
    span = element.span
    assert source[span.start_byte : span.end_byte].decode() == span.text
    assert span.text.endswith("😀")
    assert element.kind is SemanticKind.CONSTRAINT


def test_markdown_hard_break_is_preserved_in_evidence() -> None:
    source = "# Constraints\n必须先检查  \n然后执行\n".encode()
    elements = extract_semantic_elements("SKILL.md", source)
    assert elements[0].span.text.endswith("检查")
    assert source[elements[0].span.start_byte : elements[0].span.end_byte].decode() == "必须先检查"


def test_json_keys_classify_values_and_preserve_byte_evidence() -> None:
    source = (
        '\ufeff{"agent":{"role":"写作😀", "constraints":["保留数据"], '
        '"examples":{"tools":"不要执行"}}, "workflow":["读取","写入"]}'
    ).encode()
    elements = extract_semantic_elements("config.json", source)
    assert [item.kind for item in elements] == [
        SemanticKind.ROLE,
        SemanticKind.CONSTRAINT,
        SemanticKind.EXAMPLE,
        SemanticKind.WORKFLOW,
    ]
    for item in elements:
        assert source[item.span.start_byte : item.span.end_byte].decode() == item.span.text
    assert elements[0].section == "agent.role"
    assert '"写作😀"' in elements[0].span.text


def test_json_array_order_is_semantic_and_formatting_is_not() -> None:
    [before] = extract_semantic_elements("config.json", b'{"workflow":["read","write"]}')
    [formatted] = extract_semantic_elements("config.json", b'{ "workflow" : [ "read", "write" ] }')
    [reordered] = extract_semantic_elements("config.json", b'{"workflow":["write","read"]}')
    assert before.normalized == formatted.normalized
    assert before.normalized != reordered.normalized
