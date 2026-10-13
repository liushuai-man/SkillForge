"""确认式恢复接口、撤销边界与中断后公开续作入口。"""

import httpx
import pytest

from skillforge_vm.api.app import create_app
from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.oplog.restore import RestoreExecutor
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.fixture
async def setup(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "a.md").write_bytes(b"A\r\n")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    initial = service.init(str(skill))
    ws = initial["workspace"]["workspace_id"]
    (skill / "a.md").write_bytes(b"B")
    transport = httpx.ASGITransport(app=create_app(service=service))
    async with httpx.AsyncClient(transport=transport, base_url="http://vm") as http:
        yield skill, service, ws, initial["revision_id"], http


async def test_confirm_restore_undo_and_undo_again(setup):
    skill, service, ws, first, http = setup
    base = f"/api/workspaces/{ws}"
    plan = (await http.post(f"{base}/restore/preview", json={"rev": first})).json()["data"]
    assert plan["changes"] == [{"path": "a.md", "action": "modify"}]
    assert (skill / "a.md").read_bytes() == b"B"
    assert service.status(ws)["head_seq"] == 2  # 预览先保护尚未快照的新内容
    apply = f"{base}/restore/plans/{plan['plan_id']}/apply"
    for payload in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        response = await http.post(apply, json=payload)
        assert response.status_code == 422
        assert (skill / "a.md").read_bytes() == b"B"
    done = (await http.post(apply, json={"confirm": True})).json()["data"]
    assert done["revision"]["seq"] == 3
    assert (skill / "a.md").read_bytes() == b"A\r\n"
    repeated = (await http.post(apply, json={"confirm": True})).json()["data"]
    assert repeated["created"] is False
    assert repeated["revision"]["rev_id"] == done["revision"]["rev_id"]
    for seq, content in ((4, b"B"), (5, b"A\r\n")):
        undo = (await http.post(f"{base}/undo/preview", json={})).json()["data"]
        assert undo["action"] == "undo_restore"
        result = await http.post(
            f"{base}/restore/plans/{undo['plan_id']}/apply", json={"confirm": True}
        )
        assert result.json()["data"]["revision"]["seq"] == seq
        assert (skill / "a.md").read_bytes() == content
    assert service.status(ws)["pending_restore"] is None
    (skill / "a.md").write_bytes(b"new work")
    rejected = await http.post(f"{base}/undo/preview", json={})
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "restore_conflict"
    assert (skill / "a.md").read_bytes() == b"new work"
    assert service.status(ws)["head_seq"] == 6  # 拒绝覆盖前也保留新工作


async def test_preview_conflict_and_noop(setup):
    skill, service, ws, first, http = setup
    base = f"/api/workspaces/{ws}"
    assert (await http.post(f"{base}/undo/preview", json={})).status_code == 409
    plan = (await http.post(f"{base}/restore/preview", json={"rev": first})).json()["data"]
    (skill / "a.md").write_bytes(b"C")
    rejected = await http.post(
        f"{base}/restore/plans/{plan['plan_id']}/apply", json={"confirm": True}
    )
    assert rejected.status_code == 409
    assert service.status(ws)["pending_restore"] is None
    assert (skill / "a.md").read_bytes() == b"C"
    noop = await http.post(f"{base}/restore/preview", json={"rev": "@"})
    assert noop.json()["data"] == {"no_change": True, "plan_id": None, "changes": []}
    missing = await http.get(f"{base}/restore/plans/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "restore_plan_not_found"


async def test_pending_is_visible_and_resumable(setup, monkeypatch):
    skill, service, ws, first, http = setup
    base = f"/api/workspaces/{ws}"
    plan = service.preview_restore(ws, first)
    original = RestoreExecutor._apply_files

    def fail(self, plan):
        raise OSError("simulated interruption")

    monkeypatch.setattr(RestoreExecutor, "_apply_files", fail)
    with pytest.raises(OSError, match="interruption"):
        service.apply_restore(ws, plan["plan_id"], confirm=True)
    assert (await http.get(f"{base}/status")).json()["data"]["pending_restore"] == plan["plan_id"]
    for suffix, payload in (
        ("snapshots", {}),
        ("refs", {"name": "tested", "rev": first}),
        ("restore/preview", {"rev": first}),
    ):
        rejected = await http.post(f"{base}/{suffix}", json=payload)
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "restore_pending"
    loaded = (await http.get(f"{base}/restore/plans/{plan['plan_id']}")).json()["data"]
    assert loaded == plan
    monkeypatch.setattr(RestoreExecutor, "_apply_files", original)
    result = await http.post(
        f"{base}/restore/plans/{plan['plan_id']}/apply", json={"confirm": True}
    )
    assert result.status_code == 200
    assert (skill / "a.md").read_bytes() == b"A\r\n"
    assert service.status(ws)["pending_restore"] is None
