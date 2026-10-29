"""Git 风格文本 patch：保留上下文、原始换行与末尾无换行标记。"""

import difflib


def _lines(text: str) -> list[str]:
    """Git 的物理行只按 LF 划分；Unicode 分隔符和 CR 仍是原文。"""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _range(start: int, end: int) -> str:
    length = end - start
    if length == 1:
        return str(start + 1)
    return f"{start + 1 if length else start},{length}"


def compare_text(
    before: str, after: str, before_path: str, after_path: str, context: int
) -> tuple[int, int, str]:
    """v2: fix common edges before matching, then share opcodes for counts and patch."""
    if before == after:
        return 0, 0, ""
    left, right = _lines(before), _lines(after)
    prefix = 0
    while prefix < min(len(left), len(right)) and left[prefix] == right[prefix]:
        prefix += 1
    end_left, end_right = len(left), len(right)
    while end_left > prefix and end_right > prefix and left[end_left - 1] == right[end_right - 1]:
        end_left -= 1
        end_right -= 1
    middle = difflib.SequenceMatcher(
        None, left[prefix:end_left], right[prefix:end_right], autojunk=False
    ).get_opcodes()
    codes = ([("equal", 0, prefix, 0, prefix)] if prefix else []) + [
        (tag, i1 + prefix, i2 + prefix, j1 + prefix, j2 + prefix) for tag, i1, i2, j1, j2 in middle
    ]
    if end_left < len(left):
        codes.append(("equal", end_left, len(left), end_right, len(right)))
    added = sum(j2 - j1 for tag, _, _, j1, j2 in codes if tag in ("replace", "insert"))
    removed = sum(i2 - i1 for tag, i1, i2, _, _ in codes if tag in ("replace", "delete"))
    # difflib's context grouping operates on the already computed opcodes.
    matcher = difflib.SequenceMatcher()
    matcher.opcodes = codes
    output: list[str] = []

    def emit(prefix: str, lines: list[str]) -> None:
        for line in lines:
            output.append(prefix + line)
            if not line.endswith("\n"):
                output.append("\n\\ No newline at end of file\n")

    for group in matcher.get_grouped_opcodes(context):
        if not output:
            output.extend([f"--- {before_path}\n", f"+++ {after_path}\n"])
        first, last = group[0], group[-1]
        output.append(f"@@ -{_range(first[1], last[2])} +{_range(first[3], last[4])} @@\n")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                emit(" ", left[i1:i2])
            else:
                if tag in ("replace", "delete"):
                    emit("-", left[i1:i2])
                if tag in ("replace", "insert"):
                    emit("+", right[j1:j2])
    return added, removed, "".join(output)


def unified_patch(before: str, after: str, before_path: str, after_path: str, context: int) -> str:
    return compare_text(before, after, before_path, after_path, context)[2]


def line_counts(before: str, after: str) -> tuple[int, int]:
    added, removed, _ = compare_text(before, after, "a/file", "b/file", 0)
    return added, removed
