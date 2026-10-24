"""规范报告的终端展示；只消费 API 数据，不重新分析或读取 Skill 文件。"""

from __future__ import annotations

from typing import Any


def format_comparison(result: dict[str, Any], *, summary_only: bool = False) -> str:
    """展示服务生成的统一 patch，CLI 不读取工作目录或重新比较。"""
    lines = [
        f"版本：{result['base']['rev'] or '空内容'} → {result['head']['rev']}",
        f"{len(result['files'])} 个文件 · +{result['added']} / -{result['removed']} 行",
    ]
    if not result["files"]:
        lines.append("没有文件变化。")
    for file in result["files"]:
        old = file.get("before_path", file["path"])
        display = f"{old} → {file['path']}" if old != file["path"] else file["path"]
        counts = (
            f"+{file['added']} -{file['removed']}" if file["added"] is not None else "文本不可显示"
        )
        lines.append(f"\n{LABELS[file['op']]}  {display}  {counts}")
        if summary_only:
            continue
        if file["patch"]:
            lines.append(file["patch"].rstrip("\n"))
        elif file["patch"] is None:
            statuses = {file["before_status"], file["after_status"]}
            lines.append(
                "超过文本展示上限。" if "too_large" in statuses else "二进制或非 UTF-8 文件。"
            )
        else:
            lines.append(
                "空文件已新增或删除。"
                if file["op"] in ("add", "delete")
                else "文件内容逐字节相同；仅路径或文件模式变化。"
            )
        if file["before_mode"] != file["after_mode"]:
            lines.append(
                f"文件模式：{file['before_mode'] or '不存在'} → {file['after_mode'] or '不存在'}"
            )
    return "\n".join(lines)


LABELS = {
    "add": "新增",
    "delete": "删除",
    "modify": "修改",
    "move": "移动",
    "high": "高",
    "medium": "中",
    "low": "低",
    "unknown": "未知",
    "role": "角色",
    "capability": "能力",
    "constraint": "约束",
    "tool": "工具",
    "workflow": "流程",
    "example": "示例",
    "output_format": "输出格式",
    "parameter": "参数",
    "computed": "已计算",
    "not_requested": "未计算",
    "degraded": "已降级",
}
REASONS = {
    "unsupported_encoding": "不是 UTF-8 文本，无法展示文字片段",
    "text_limit_exceeded": "超过文字分析上限",
    "parse_failed": "结构解析失败",
    "unsupported_file_type": "未支持此文件的结构分析",
    "ambiguous_move": "移动匹配存在歧义",
}


def _span(label: str, span: dict[str, Any] | None, prefix: str) -> list[str]:
    if span is None:
        return [f"  {label}：（不存在）"]
    return [
        f"  {label}：{span['path']} UTF-8 bytes [{span['start_byte']}, {span['end_byte']})",
        *(f"  {prefix} {line}" for line in span["text"].split("\n")),
    ]


def format_report(report: dict[str, Any], *, summary_only: bool = False) -> str:
    overview = report["overview"]
    changes = "未计算" if overview["changes"] is None else str(overview["changes"])
    lines = [
        report["summary"],
        f"文件 {overview['files']} · 语义变化 {changes} · "
        f"分组 {overview['clusters']} · 风险 {LABELS[overview['risk']]}",
    ]
    if not summary_only:
        lines.append(
            f"版本：{report['base']['rev'] or '空树'} → {report['head']['rev']} · {report['layer']}"
        )
        layers = report["layers"]
        for key, name in (("semantic", "语义"), ("text", "文字")):
            lines.append(f"{name}层：{LABELS[layers[key]['status']]}")
        if report["behavior"] is None:
            lines.append("行为对比：未接入，以上为静态分析。")
        units = {unit["id"]: unit for unit in layers["semantic"]["units"]}
        risks = {item["unit"]: item for item in report["risk"]["items"]}
        for cluster in report["clusters"]:
            lines.append(f"\n分组：{cluster['label']}")
            for unit_id in cluster["units"]:
                unit = units[unit_id]
                lines.append(
                    f"{LABELS[unit['op']]} · {LABELS[unit['kind']]} · {unit['path']} "
                    f"[{unit_id}; {unit['rule_id']}]"
                )
                lines.extend(_span("修改前", unit["before"], "-"))
                lines.extend(_span("修改后", unit["after"], "+"))
                if risk := risks.get(unit_id):
                    lines.append(
                        f"  风险：{LABELS[risk['level']]} · {risk['reason']} [{risk['rule_id']}]"
                    )
        lines.append("\n文件与文字差异（只读变更片段，非完整文件）：")
        for file in layers["metadata"]["files"]:
            path = file["path"]
            before_path = file.get("before_path", path)
            display = f"{before_path} → {path}" if before_path != path else path
            lines.append(f"{LABELS[file['op']]} · {display}")
            hunks = [h for h in layers["text"]["hunks"] if h["path"] in {path, before_path}]
            for hunk in hunks:
                lines.extend(_span("修改前", hunk["before"], "-"))
                lines.extend(_span("修改后", hunk["after"], "+"))
            if not hunks:
                lines.append(
                    "  文字层未计算。"
                    if layers["text"]["status"] == "not_requested"
                    else "  无可展示片段；可能仅路径/模式/格式变化，或已降级，见诊断。"
                )
        for key, name in (("degraded", "降级"), ("needs_review", "待确认")):
            for item in report[key]:
                code = item["reason_code"]
                available = (
                    f" · 可用 {item['available_layer']}" if "available_layer" in item else ""
                )
                lines.append(
                    f"{name}：{item['path']} · {REASONS.get(code, code)} [{code}]{available}"
                )
    else:
        for cluster in report["clusters"]:
            lines.append(f"- {cluster['label']}（{len(cluster['units'])}）")
    if overview["needs_review"]:
        lines.append(f"待确认：{overview['needs_review']} 项")
    lines.append(f"报告：{report['report_id']}")
    return "\n".join(lines)
