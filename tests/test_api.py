"""M-10 接口层验收：统一外壳、错误映射、快照/修订/引用路由、事件流。

对应 AC-08（零基线/锚点/显式缺失报错）、AC-17（事件为通知，状态接口为真值）。
只用测试临时 Skill 与独立数据目录。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest

from skillforge_vm.api.app import create_app
from skillforge_vm.api.events import EVENT_SNAPSHOT_CREATED, EventBus
from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.fixture()
def api_app(tmp_path: Path):
    manager = WorkspaceManager(data_root=tmp_path / "data")
    return create_app(service=WorkspaceService(manager))


@pytest.fixture()
async def client(api_app: Any):
    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://vm") as http:
        yield http


async def _init(client: httpx.AsyncClient, skill_dir: Path) -> dict[str, Any]:
    response = await client.post("/api/workspaces", json={"path": str(skill_dir)})
    assert response.status_code == 200
    return response.json()


async def test_health_uses_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["error"] is None
    assert body["request_id"]
    assert response.headers["x-request-id"] == body["request_id"]


async def test_init_and_list_workspaces(client: httpx.AsyncClient, skill_dir: Path) -> None:
    body = await _init(client, skill_dir)
    assert body["ok"] is True
    workspace_id = body["data"]["workspace"]["workspace_id"]
    assert body["data"]["file_count"] == 2

    listing = (await client.get("/api/workspaces")).json()
    assert [row["workspace_id"] for row in listing["data"]] == [workspace_id]

    single = (await client.get(f"/api/workspaces/{workspace_id}")).json()
    assert single["data"]["root_path"] == str(skill_dir.resolve())


async def test_status_and_snapshot_roundtrip(client: httpx.AsyncClient, skill_dir: Path) -> None:
    workspace_id = (await _init(client, skill_dir))["data"]["workspace"]["workspace_id"]

    first = (await client.get(f"/api/workspaces/{workspace_id}/status")).json()["data"]
    assert first["has_pending_changes"] is False

    (skill_dir / "SKILL.md").write_text("# Demo changed\n", encoding="utf-8")
    pending = (await client.get(f"/api/workspaces/{workspace_id}/status")).json()["data"]
    assert pending["has_pending_changes"] is True

    created = (
        await client.post(f"/api/workspaces/{workspace_id}/snapshots", json={"message": "改标题"})
    ).json()["data"]
    assert created["created"] is True
    assert created["revision"]["seq"] == 2

    again = (await client.post(f"/api/workspaces/{workspace_id}/snapshots", json={})).json()["data"]
    assert again["created"] is False

    settled = (await client.get(f"/api/workspaces/{workspace_id}/status")).json()["data"]
    assert settled["has_pending_changes"] is False


async def test_revision_lookup_by_id_last_and_unknown_ref(
    client: httpx.AsyncClient, skill_dir: Path
) -> None:
    workspace_id = (await _init(client, skill_dir))["data"]["workspace"]["workspace_id"]
    revision_id = (await client.get(f"/api/workspaces/{workspace_id}/revisions")).json()["data"][0][
        "rev_id"
    ]

    by_id = (await client.get(f"/api/workspaces/{workspace_id}/revisions/{revision_id}")).json()
    assert by_id["data"]["rev_id"] == revision_id

    by_last = (await client.get(f"/api/workspaces/{workspace_id}/revisions/last")).json()
    assert by_last["data"]["rev_id"] == revision_id

    missing = await client.get(f"/api/workspaces/{workspace_id}/revisions/no-such-ref")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ref_not_found"


async def test_tag_and_reserved_ref(client: httpx.AsyncClient, skill_dir: Path) -> None:
    workspace_id = (await _init(client, skill_dir))["data"]["workspace"]["workspace_id"]

    tagged = (
        await client.post(f"/api/workspaces/{workspace_id}/refs", json={"name": "tested"})
    ).json()
    assert tagged["data"]["name"] == "tested"

    refs = (await client.get(f"/api/workspaces/{workspace_id}/refs")).json()["data"]
    names = {row["name"] for row in refs}
    assert {"tested", "last"} <= names

    reserved = await client.post(f"/api/workspaces/{workspace_id}/refs", json={"name": "last"})
    assert reserved.status_code == 422
    assert reserved.json()["error"]["code"] == "invalid_request"


async def test_ops_record_init_snapshot_and_ref(client: httpx.AsyncClient, skill_dir: Path) -> None:
    workspace_id = (await _init(client, skill_dir))["data"]["workspace"]["workspace_id"]
    (skill_dir / "SKILL.md").write_text("# Demo 2\n", encoding="utf-8")
    await client.post(f"/api/workspaces/{workspace_id}/snapshots", json={})
    await client.post(f"/api/workspaces/{workspace_id}/refs", json={"name": "stable"})

    kinds = [
        row["kind"]
        for row in (await client.get(f"/api/workspaces/{workspace_id}/ops")).json()["data"]
    ]
    assert kinds == ["workspace.init", "snapshot", "ref.set"]


async def test_error_mapping(client: httpx.AsyncClient, tmp_path: Path) -> None:
    unknown = await client.get("/api/workspaces/nope")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "workspace_not_found"

    bad_root = await client.post("/api/workspaces", json={"path": str(tmp_path / "missing")})
    assert bad_root.status_code == 400
    assert bad_root.json()["error"]["code"] == "invalid_skill_root"

    validation = await client.get("/api/workspaces/nope/revisions", params={"limit": 0})
    assert validation.status_code == 422
    assert validation.json()["error"]["code"] == "invalid_request"


async def test_event_bus_delivers_from_worker_thread() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    threading.Thread(target=lambda: bus.publish({"type": "ping"})).start()
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event == {"type": "ping"}


async def test_snapshot_publishes_created_event(tmp_path: Path) -> None:
    """服务提交快照后向订阅者推送 snapshot/created（事件只是通知）。"""
    skill = tmp_path / "s"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# A\n", encoding="utf-8")
    service = WorkspaceService(WorkspaceManager(data_root=tmp_path / "data"))
    workspace_id = service.init(str(skill))["workspace"]["workspace_id"]

    queue = service.bus.subscribe()
    (skill / "SKILL.md").write_text("# B\n", encoding="utf-8")
    service.snapshot(workspace_id)

    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event["type"] == EVENT_SNAPSHOT_CREATED
    assert event["workspace_id"] == workspace_id
    assert event["revision_id"]


async def test_service_lifecycle_watches_new_and_existing_workspaces(
    tmp_path: Path, skill_dir: Path
) -> None:
    manager = WorkspaceManager(data_root=tmp_path / "data")
    service = WorkspaceService(manager)
    app = create_app(service=service)
    async with app.router.lifespan_context(app):
        ws = service.init(str(skill_dir))["workspace"]["workspace_id"]
        await asyncio.sleep(0.7)  # 启动扫描及原生监听就绪后再验证真实事件合并
        queue = service.bus.subscribe()
        for index in range(5):
            (skill_dir / "SKILL.md").write_text(f"# burst {index}", encoding="utf-8")
            await asyncio.sleep(0.1)
        event = await asyncio.wait_for(queue.get(), timeout=5)
        assert event["seq"] == 2
        await asyncio.sleep(0.7)
        assert service.status(ws)["head_seq"] == 2
        assert not service.status(ws)["has_pending_changes"]
        assert queue.empty()
        service.bus.unsubscribe(queue)

    (skill_dir / "SKILL.md").write_text("# offline edit", encoding="utf-8")
    restarted = WorkspaceService(manager)
    app = create_app(service=restarted)
    async with app.router.lifespan_context(app):
        for _ in range(100):
            if restarted.status(ws)["head_seq"] == 3:
                break
            await asyncio.sleep(0.05)
        assert restarted.status(ws)["head_seq"] == 3
        assert not restarted.status(ws)["has_pending_changes"]
    assert not restarted._watchers


async def test_tag_captures_current_files_and_ends_change(
    client: httpx.AsyncClient, skill_dir: Path
) -> None:
    ws = (await _init(client, skill_dir))["data"]["workspace"]["workspace_id"]
    (skill_dir / "SKILL.md").write_text("# uncommitted", encoding="utf-8")
    tag = (await client.post(f"/api/workspaces/{ws}/refs", json={"name": "tested"})).json()
    head = (await client.get(f"/api/workspaces/{ws}/revisions/last")).json()["data"]
    assert head["seq"] == 2
    assert tag["data"]["rev_id"] == head["rev_id"]
    (skill_dir / "SKILL.md").write_text("# next change", encoding="utf-8")
    next_rev = (await client.post(f"/api/workspaces/{ws}/snapshots", json={})).json()["data"]
    assert next_rev["revision"]["change_id"] != head["change_id"]
    refs = (await client.get(f"/api/workspaces/{ws}/refs")).json()["data"]
    assert next(ref for ref in refs if ref["name"] == "tested")["rev_id"] == head["rev_id"]


async def test_event_subscriptions_are_scoped_and_bounded() -> None:
    bus = EventBus()
    a, b = bus.subscribe("a"), bus.subscribe("b")
    for seq in range(200):
        bus.publish({"workspace_id": "a", "seq": seq})
    await asyncio.sleep(0)
    assert b.empty()
    assert a.qsize() == 128
    events = [a.get_nowait() for _ in range(a.qsize())]
    assert events[-1]["seq"] == 199
    bus.unsubscribe(a)
    bus.unsubscribe(b)
