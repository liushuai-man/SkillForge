"""M-05～M-08：分层降级、语义报告、缓存与可复现身份。"""

from __future__ import annotations

import json

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
