from pathlib import Path

import httpx
import pytest

from skillforge_vm.api.app import create_app
from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.mark.asyncio
async def test_browser_reads_history_not_live_files(tmp_path: Path):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_bytes("# 原始内容\n".encode())
    (skill / "binary.bin").write_bytes(b"\x00\xff")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    initial = service.init(str(skill))
    ws = initial["workspace"]["workspace_id"]
    first = initial["revision_id"]
    (skill / "SKILL.md").write_bytes("# 新内容\n".encode())
    service.snapshot(ws)
    transport = httpx.ASGITransport(app=create_app(service=service))
    async with httpx.AsyncClient(transport=transport, base_url="http://vm") as client:
        prefix = f"/api/workspaces/{ws}/revisions/{first}"
        listing = (await client.get(prefix + "/files")).json()["data"]
        assert {item["path"] for item in listing["files"]} == {"SKILL.md", "binary.bin"}
        old = (await client.get(prefix + "/file", params={"path": "SKILL.md"})).json()
        assert old["data"]["content"] == "# 原始内容\n"
        binary = (await client.get(prefix + "/file", params={"path": "binary.bin"})).json()
        assert binary["data"]["content"] is None
        assert binary["data"]["reason"]
        missing = await client.get(prefix + "/file", params={"path": "../secret"})
        assert missing.status_code == 422
        wrong = await client.get(f"/api/workspaces/missing/revisions/{first}/files")
        assert wrong.status_code == 404
