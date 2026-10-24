"""保留旧 --layer 显式兼容入口的证据回归；新默认文本比较另测。"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.cli import main as cli
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.fixture
def report_workspace(tmp_path: Path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    file = skill / "SKILL.md"
    file.write_text("# Constraints\n必须保留历史。\n", encoding="utf-8")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    ws = service.init(str(skill))["workspace"]["workspace_id"]
    service.set_ref(ws, "tested")
    calls = []

    def get(self, path, **params):
        calls.append((path, params))
        assert path == f"/api/workspaces/{ws}/diff"
        return service.diff(ws, **params)

    monkeypatch.setattr(cli.VmClient, "get", get)

    def invoke(*args):
        if "--layer" not in args:
            args = ("--layer", "L3", *args)
        result = CliRunner().invoke(cli.app, ["diff", "--ws", ws, *args])
        assert result.exit_code == 0, result.exception or result.output
        return result.output

    return skill, service, ws, invoke, calls


def test_cli_renders_real_semantic_and_text_evidence(report_workspace):
    skill, service, ws, invoke, calls = report_workspace
    (skill / "SKILL.md").write_text("# Constraints\n必须保留历史和证据。\n", encoding="utf-8")
    service.snapshot(ws)
    output = invoke("--base", "tested", "--head", "last")
    report = service.diff(ws, base="tested", head="last")
    assert calls == [
        (f"/api/workspaces/{ws}/diff", {"base": "tested", "head": "last", "layer": "L3"})
    ]
    assert f"版本：{report['base']['rev']} → {report['head']['rev']} · L3" in output
    assert "修改 · 约束 · SKILL.md" in output
    assert "- 必须保留历史。" in output
    assert "+ 必须保留历史和证据。" in output
    assert "UTF-8 bytes [" in output
    assert "修改可能影响既有行为" in output
    assert "行为对比：未接入" in output
    assert report["report_id"] in output
    for unit in report["layers"]["semantic"]["units"]:
        assert unit["id"] in output and unit["rule_id"] in output
    summary = invoke("--summary")
    assert "报告：RPT-" in summary
    assert "UTF-8 bytes" not in summary


@pytest.mark.parametrize("layer", ["L0", "L1"])
def test_cli_lower_layers_do_not_claim_zero_semantic_changes(report_workspace, layer):
    skill, service, ws, invoke, _ = report_workspace
    (skill / "SKILL.md").write_text("# Constraints\n必须本地处理。\n禁止上传。\n", encoding="utf-8")
    service.snapshot(ws)
    output = invoke("--layer", layer)
    assert "语义变化 未计算" in output
    assert "语义层：未计算" in output
    assert "风险 未知" in output
    assert "语义变化 0" not in output
    assert "None" not in output
    if layer == "L0":
        assert "文字层未计算。" in output
    else:
        assert "+ 必须本地处理。" in output
        assert "+ 禁止上传。" in output


def test_cli_add_delete_and_move_keep_paths_and_absent_sides(report_workspace):
    skill, service, ws, invoke, _ = report_workspace
    (skill / "old.md").write_text("# Role\n你是旧助手。\n", encoding="utf-8")
    service.snapshot(ws)
    service.set_ref(ws, "tested")
    (skill / "old.md").rename(skill / "renamed.md")
    (skill / "SKILL.md").unlink()
    (skill / "new.md").write_text("# Tool\n使用专用搜索工具。\n", encoding="utf-8")
    service.snapshot(ws)
    output = invoke()
    assert "移动 · old.md → renamed.md" in output
    assert "删除 · SKILL.md" in output
    assert "新增 · new.md" in output
    assert "修改后：（不存在）" in output
    assert "修改前：（不存在）" in output
    assert "None" not in output


def test_cli_degraded_files_do_not_hide_available_text(report_workspace):
    skill, service, ws, invoke, _ = report_workspace
    (skill / "bad.yaml").write_text("key: [", encoding="utf-8")
    (skill / "raw.bin").write_bytes(b"\xff\x00")
    service.snapshot(ws)
    output = invoke()
    assert "语义层：已降级" in output
    assert "降级：bad.yaml · 结构解析失败 [parse_failed] · 可用 L1" in output
    assert "降级：raw.bin" in output and "unsupported_encoding" in output
    assert "+ key: [" in output
    assert "风险 未知" in output


def test_cli_unchanged_report_is_explicit(report_workspace):
    _, _, _, invoke, _ = report_workspace
    output = invoke("--base", "tested")
    assert "当前版本与基线没有变化。" in output
    assert "文件 0 · 语义变化 0" in output
    assert "报告：RPT-" in output


def test_cli_ambiguous_move_is_explicitly_pending_review(report_workspace):
    skill, service, ws, invoke, _ = report_workspace
    (skill / "SKILL.md").unlink()
    (skill / "moved.md").write_text("# Constraints\n必须保留完整历史。\n", encoding="utf-8")
    service.snapshot(ws)
    output = invoke()
    assert "待确认：moved.md · 移动匹配存在歧义 [ambiguous_move]" in output
    assert "待确认：1 项" in output
