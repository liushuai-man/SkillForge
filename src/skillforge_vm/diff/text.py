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


def unified_patch(before: str, after: str, before_path: str, after_path: str, context: int) -> str:
    left, right = _lines(before), _lines(after)
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
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
    return "".join(output)


def line_counts(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, _lines(before), _lines(after), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            added += j2 - j1
        if tag in ("replace", "delete"):
            removed += i2 - i1
    return added, removed
