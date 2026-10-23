"""覆盖纳管后页面立即请求报告/摘要的真实 HTTP 链路。"""

import httpx

from skillforge_vm.api.app import create_app
from skillforge_vm.workspace.manager import WorkspaceManager


async def test_open_workspace_report_summary_and_anchor(tmp_path):
    skill = tmp_path / "skill"
    skill.mkdir()
    file = skill / "SKILL.md"
    file.write_text("# Constraints\n必须保留历史。\n", encoding="utf-8")
    app = create_app(WorkspaceManager(data_root=tmp_path / "data"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://vm"
    ) as client:
        initialized = await client.post("/api/workspaces", json={"path": str(skill)})
        ws = initialized.json()["data"]["workspace"]["workspace_id"]
        url = f"/api/workspaces/{ws}"
        report = await client.get(url + "/diff")
        assert report.status_code == 200
        assert report.json()["data"]["layers"]["semantic"]["status"] == "computed"
        assert (await client.get(url + "/diff/summary")).json()["data"][
            "report_id"
        ] == report.json()["data"]["report_id"]
        assert (await client.post(url + "/refs", json={"name": "tested"})).status_code == 200
        assert (await client.get(url + "/diff?base=tested")).json()["data"]["overview"][
            "files"
        ] == 0
        file.write_text("# Constraints\n必须保留历史与证据。\n", encoding="utf-8")
        assert (await client.post(url + "/snapshots", json={})).status_code == 200
        changed = (await client.get(url + "/diff")).json()["data"]
        assert changed["overview"]["changes"] == 1
        assert changed["layers"]["text"]["hunks"]
        assert (await client.get(url + "/diff")).json()["data"] == changed
