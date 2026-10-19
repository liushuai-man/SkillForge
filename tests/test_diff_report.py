"""M-05～M-08：分层降级、语义报告、缓存与可复现身份。"""

from __future__ import annotations

import json

import pytest

from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.db.connection import connect
from skillforge_vm.workspace.manager import WorkspaceManager


def _service(tmp_path, text: str) -> tuple[WorkspaceService, str, object]:
    skill = tmp_path / "skill"
    skill.mkdir()
    file = skill / "SKILL.md"
    file.write_text(text, encoding="utf-8")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    ws = service.init(str(skill))["workspace"]["workspace_id"]
    return service, ws, file


def test_default_report_uses_anchor_baseline_and_is_cached(tmp_path) -> None:
    service, ws, file = _service(tmp_path, "# Constraints\n必须保留历史\n")
    service.set_ref(ws, "tested")
    file.write_text("# Constraints\n不得删除历史\n", encoding="utf-8")
    service.snapshot(ws)

    first = service.diff(ws)
    second = service.diff(ws)
    assert first == second
    assert first["base"]["rev"] == service._baseline(ws)
    assert first["overview"]["changes"] == 1
    assert first["layers"]["semantic"]["units"][0]["op"] == "modify"
    handle = service.manager.get(ws)
    conn = connect(handle.paths.db_file)
    try:
        assert conn.execute("SELECT count(*) FROM report").fetchone()[0] == 1
        stored = conn.execute("SELECT payload_json FROM report").fetchone()[0]
    finally:
        conn.close()
    assert json.loads(stored) == first


def test_zero_baseline_reports_additions(tmp_path) -> None:
    service, ws, _ = _service(tmp_path, "# Role\n你是助手\n")
    report = service.diff(ws)
    assert report["base"]["rev"] is None
    assert report["layers"]["semantic"]["units"][0]["op"] == "add"


def test_bad_yaml_and_binary_degrade_without_hiding_good_file(tmp_path) -> None:
    service, ws, _ = _service(tmp_path, "# Role\n你是助手\n")
    service.set_ref(ws, "tested")
    root = service.manager.get(ws).paths.root
    (root / "bad.yaml").write_text("key: [", encoding="utf-8")
    (root / "raw.bin").write_bytes(b"\x00\xff")
    (root / "SKILL.md").write_text("# Role\n你是高级助手\n", encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    reasons = {item["path"]: item["reason_code"] for item in report["degraded"]}
    assert reasons == {"bad.yaml": "parse_failed", "raw.bin": "unsupported_encoding"}
    assert report["layers"]["semantic"]["status"] == "degraded"
    assert report["layers"]["semantic"]["units"]
    assert report["overview"]["risk"] == "unknown"


def test_lower_layer_does_not_claim_semantic_computed(tmp_path) -> None:
    service, ws, _ = _service(tmp_path, "# Role\n你是助手\n")
    report = service.diff(ws, layer="L1")
    assert report["layers"]["text"]["status"] == "computed"
    assert report["layers"]["semantic"]["status"] == "not_requested"
    assert report["overview"]["changes"] is None
    assert report["overview"]["risk"] == "unknown"
    assert "未计算" in report["summary"]
    assert "0 处语义变化" not in report["summary"]


def test_summary_uses_readable_chinese_risk(tmp_path) -> None:
    service, ws, file = _service(tmp_path, "# Constraints\n必须保留历史\n")
    service.set_ref(ws, "tested")
    file.write_text("# Constraints\n必须保留历史和证据\n", encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    assert report["overview"]["risk"] == "medium"
    assert "中风险" in report["summary"]
    assert "medium" not in report["summary"]


def test_repeated_unchanged_rules_do_not_become_modifications(tmp_path) -> None:
    text = "# Rules\nMust keep data local.\nMust keep data local.\n"
    service, ws, file = _service(tmp_path, text)
    service.set_ref(ws, "tested")
    file.write_text(text + "\n", encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    assert report["overview"]["files"] == 1
    assert report["layers"]["semantic"]["units"] == []
    assert report["overview"]["risk"] == "low"


def test_empty_json_and_invalid_base_both_degrade_to_text(tmp_path) -> None:
    service, ws, file = _service(tmp_path, "# Role\nYou are a writer.\n")
    config = file.parent / "config.json"
    config.write_text('{"role":"writer"}', encoding="utf-8")
    service.set_ref(ws, "tested")
    config.write_bytes(b"")
    service.snapshot(ws)
    empty = service.diff(ws)
    assert empty["degraded"] == [
        {
            "path": "config.json",
            "requested_layer": "L3",
            "available_layer": "L1",
            "reason_code": "parse_failed",
        }
    ]
    assert empty["layers"]["text"]["hunks"]
    service.set_ref(ws, "empty")
    config.write_text('{"role":"reviewer"}', encoding="utf-8")
    service.snapshot(ws)
    repaired = service.diff(ws)
    assert repaired["degraded"] == empty["degraded"]
    assert repaired["overview"]["risk"] == "unknown"


def test_json_role_change_is_not_reported_as_zero_semantic_changes(tmp_path) -> None:
    service, ws, file = _service(tmp_path, "# Role\nYou are a writer.\n")
    config = file.parent / "config.json"
    config.write_text('{"role":"writer"}', encoding="utf-8")
    service.set_ref(ws, "tested")
    config.write_text('{"role":"reviewer"}', encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    [unit] = report["layers"]["semantic"]["units"]
    assert unit["kind"] == "role"
    assert unit["op"] == "modify"


@pytest.mark.parametrize("bad", ['{"timeout":NaN}', '{"timeout":Infinity}'])
def test_nonstandard_json_constants_degrade_without_failing_report(tmp_path, bad) -> None:
    service, ws, file = _service(tmp_path, "# Role\nYou are a writer.\n")
    (file.parent / "config.json").write_text(bad, encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    assert report["degraded"][0]["reason_code"] == "parse_failed"
    assert report["layers"]["text"]["hunks"]


@pytest.mark.parametrize(
    "before,after",
    [
        ('{"timeout":1e999}', '{"timeout":2e999}'),
        ('{"timeout":0.12345678901234567890}', '{"timeout":0.12345678901234567891}'),
        ('{"a":{"timeout":30}}', '{"b":{"timeout":30}}'),
    ],
)
def test_json_numeric_and_parent_path_changes_are_not_lost(tmp_path, before, after) -> None:
    service, ws, file = _service(tmp_path, "# Role\nYou are a writer.\n")
    config = file.parent / "config.json"
    config.write_text(before, encoding="utf-8")
    service.set_ref(ws, "tested")
    config.write_text(after, encoding="utf-8")
    service.snapshot(ws)
    report = service.diff(ws)
    [unit] = report["layers"]["semantic"]["units"]
    assert unit["op"] == "modify"
    assert unit["before"]["text"] != unit["after"]["text"]
