"""当前产品：真实历史全文、Git patch 和 CLI；旧语义兼容另有回归。"""

import httpx
import pytest
from typer.testing import CliRunner

from skillforge_vm.api.app import create_app
from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.cli import main as cli
from skillforge_vm.core.errors import InvalidRequestError, ObjectCorruptedError
from skillforge_vm.core.types import ObjectType
from skillforge_vm.diff.text import line_counts, unified_patch
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.fixture
def text_workspace(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes(b"# Skill\r\nunchanged\r\nbefore\r\nlast")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    ws = service.init(str(skill))["workspace"]["workspace_id"]
    return skill, service, ws


def test_compare_preserves_context_and_fixed_fulltext(text_workspace, monkeypatch):
    skill, service, ws = text_workspace
    before = service.file_content(ws, "@", "SKILL.md")
    (skill / "SKILL.md").write_bytes(b"# Skill\r\nunchanged\r\ninserted\r\nafter\r\nlast")
    service.snapshot(ws)

    def forbidden(*args, **kwargs):
        raise AssertionError("当前比较不得调用语义解析")

    monkeypatch.setattr("skillforge_vm.diff.engine.extract_semantic_elements", forbidden)
    result = service.compare(ws)
    assert set(result) == {"base", "head", "files", "context", "algorithm", "added", "removed"}
    assert result["added"] == 2 and result["removed"] == 1
    patch = result["files"][0]["patch"]
    assert "@@ -1,4 +1,5 @@" in patch
    assert " unchanged\r\n" in patch
    assert "-before\r\n" in patch and "+inserted\r\n+after\r\n" in patch
    assert "\\ No newline at end of file" in patch
    assert service.file_content(ws, result["base"]["rev"], "SKILL.md") == before
    fixed = service.file_content(ws, result["head"]["rev"], "SKILL.md")
    (skill / "SKILL.md").write_bytes(b"later save\n")
    service.snapshot(ws)
    assert service.file_content(ws, result["head"]["rev"], "SKILL.md") == fixed
    assert service.compare(ws, base=result["base"]["rev"], head=result["head"]["rev"]) == result


def test_initial_empty_add_delete_rename_binary_and_invalid_yaml(text_workspace):
    skill, service, ws = text_workspace
    initial = service.compare(ws)
    assert initial["base"]["rev"] is None
    assert initial["files"][0]["patch"].startswith("--- /dev/null\n")
    (skill / "empty.txt").write_bytes(b"")
    (skill / "raw.bin").write_bytes(b"\xff\x00")
    (skill / "broken.yaml").write_bytes(b"key: [\n")
    (skill / "SKILL.md").rename(skill / "renamed.md")
    service.snapshot(ws)
    rows = {f["path"]: f for f in service.compare(ws)["files"]}
    assert rows["renamed.md"]["op"] == "move"
    assert rows["renamed.md"]["before_path"] == "SKILL.md"
    assert rows["renamed.md"]["patch"] == ""
    assert rows["empty.txt"]["after_status"] == "text"
    assert service.file_content(ws, "@", "empty.txt")["text"] == ""
    assert service.file_content(ws, "@~1", "empty.txt")["status"] == "absent"
    assert rows["raw.bin"]["patch"] is None and rows["raw.bin"]["added"] is None
    assert "+key: [" in rows["broken.yaml"]["patch"]
    (skill / "renamed.md").unlink()
    service.snapshot(ws)
    assert service.compare(ws)["files"][0]["after_status"] == "absent"
    assert "+++ /dev/null" in service.compare(ws)["files"][0]["patch"]


def test_content_limits_paths_and_corruption(text_workspace, monkeypatch):
    _, service, ws = text_workspace
    handle = service._handle(ws)
    handle.config.ignore.max_text_bytes = 3
    original_handle = service._handle
    monkeypatch.setattr(service, "_handle", lambda workspace_id: handle)
    assert service.file_content(ws, "@", "SKILL.md")["status"] == "too_large"
    assert service.file_content(ws, "@", "SKILL.md")["text"] is None
    monkeypatch.setattr(service, "_handle", original_handle)
    for path in ("../SKILL.md", "C:/SKILL.md", "/SKILL.md", "a//b", "a\\b", ""):
        with pytest.raises(InvalidRequestError):
            service.file_content(ws, "@", path)
    from skillforge_vm.objectstore.store import ObjectStore

    monkeypatch.setattr(ObjectStore, "read", lambda *args: (ObjectType.TREE, b"[]"))
    with pytest.raises(ObjectCorruptedError):
        service.file_content(ws, "@", "SKILL.md")


@pytest.mark.parametrize("old,new", [("x", "y"), ("x\n", "y"), ("x", "y\n")])
def test_unified_patch_marks_missing_final_newline(old, new):
    patch = unified_patch(old, new, "a/x", "b/x", 3)
    assert "@@ -1 +1 @@" in patch
    assert patch.count("\\ No newline at end of file") == (not old.endswith("\n")) + (
        not new.endswith("\n")
    )


def test_repeated_lines_and_unicode_separators_are_not_spurious_changes():
    before = "a\n" * 300 + "old\n" + "a\n" * 300
    after = "a\n" * 300 + "new\n" + "a\n" * 300
    patch = unified_patch(before, after, "a/x", "b/x", 3)
    assert line_counts(before, after) == (1, 1)
    assert patch.count("-old\n") == patch.count("+new\n") == 1
    assert "-a\n" not in patch and "+a\n" not in patch
    for separator in ("\u2028", "\u2029", "\v", "\f", "\r"):
        patch = unified_patch(f"a{separator}b\n", f"a{separator}c\n", "a/x", "b/x", 3)
        assert "@@ -1 +1 @@" in patch
        assert f"-a{separator}b\n+a{separator}c\n" in patch
        assert "No newline" not in patch


async def test_http_content_errors_and_comparison(text_workspace, tmp_path):
    _, service, ws = text_workspace
    other = tmp_path / "other"
    other.mkdir()
    (other / "SKILL.md").write_bytes(b"other")
    ws2 = service.init(str(other))["workspace"]["workspace_id"]
    foreign = service.get_revision(ws2, "@")
    app = create_app(service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://vm") as c:
        prefix = f"/api/workspaces/{ws}"
        result = await c.get(prefix + "/compare")
        assert result.status_code == 200 and result.json()["ok"] is True
        rev = result.json()["data"]["head"]["rev"]
        full = await c.get(prefix + f"/revisions/{rev}/content", params={"path": "SKILL.md"})
        assert full.json()["data"]["text"] == "# Skill\r\nunchanged\r\nbefore\r\nlast"
        absent = await c.get(prefix + f"/revisions/{rev}/content", params={"path": "absent"})
        assert absent.json()["data"]["status"] == "absent"
        foreign_rev = foreign["rev_id"]
        invalid = await c.get(
            prefix + f"/revisions/{foreign_rev}/content", params={"path": "SKILL.md"}
        )
        assert invalid.status_code == 404
        assert invalid.json()["error"]["code"] == "revision_not_found"
        assert (await c.get(prefix + "/compare?context=101")).status_code == 422


def test_cli_default_patch_positional_filter_context_and_summary(text_workspace, monkeypatch):
    skill, service, ws = text_workspace
    service.set_ref(ws, "old")
    (skill / "SKILL.md").write_bytes(b"# Skill\r\nunchanged\r\nafter\r\nlast")
    service.snapshot(ws)
    calls = []

    def get(self, path, **params):
        calls.append((path, params))
        assert path == f"/api/workspaces/{ws}/compare"
        params = dict(params)
        params["path"] = params.pop("file")
        return service.compare(ws, **params)

    monkeypatch.setattr(cli.VmClient, "get", get)
    runner = CliRunner()
    output = runner.invoke(cli.app, ["diff", "old", "@", "--ws", ws, "-f", "SKILL.md", "-U", "1"])
    assert output.exit_code == 0, output.exception
    assert calls[-1][1] == {"base": "old", "head": "@", "context": 1, "file": "SKILL.md"}
    assert "@@ -2,3 +2,3 @@" in output.output
    assert "-before" in output.output and "+after" in output.output
    assert "unchanged" in output.output and "语义" not in output.output
    assert "风险" not in output.output and "聚类" not in output.output
    summary = runner.invoke(cli.app, ["diff", "--ws", ws, "--summary"])
    assert summary.exit_code == 0 and "SKILL.md" in summary.output
    assert "@@" not in summary.output
    conflict = runner.invoke(cli.app, ["diff", "old", "--base", "@", "--ws", ws])
    assert conflict.exit_code == 1


def test_cli_selects_workspace_from_current_skill_directory(text_workspace, tmp_path, monkeypatch):
    skill, service, ws = text_workspace
    other = tmp_path / "another-skill"
    other.mkdir()
    (other / "SKILL.md").write_bytes(b"other\n")
    service.init(str(other))
    monkeypatch.chdir(skill)

    def get(self, endpoint, **params):
        if endpoint == "/api/workspaces":
            return service.list_workspaces()
        assert endpoint == f"/api/workspaces/{ws}/compare"
        params["path"] = params.pop("file")
        return service.compare(ws, **params)

    monkeypatch.setattr(cli.VmClient, "get", get)
    result = CliRunner().invoke(cli.app, ["diff", "--summary"])
    assert result.exit_code == 0, result.exception
    assert "SKILL.md" in result.output and "语义" not in result.output
