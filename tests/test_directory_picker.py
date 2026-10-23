"""本机选择器的安全边界与取消/失败语义；不弹出无人值守原生窗口。"""

import json
import os
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from skillforge_vm.api import directory_picker as picker
from skillforge_vm.api.app import create_app
from skillforge_vm.core.errors import OperationFailedError, WorkspaceBusyError
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.mark.parametrize("selected", [None, "directory"])
async def test_picker_returns_path_or_cancel_without_registering(tmp_path, monkeypatch, selected):
    selected = str(tmp_path) if selected else None
    monkeypatch.setattr(picker, "select_directory", lambda: selected)
    # app imports the function explicitly.
    import importlib

    module = importlib.import_module("skillforge_vm.api.app")
    monkeypatch.setattr(module, "select_directory", lambda: selected)
    app = create_app(WorkspaceManager(data_root=tmp_path / "data"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)),
        base_url="http://127.0.0.1",
    ) as client:
        response = await client.post("/api/local/select-directory", json={})
        assert response.status_code == 200
        assert response.json()["data"] == {"path": selected}
        assert (await client.get("/api/workspaces")).json()["data"] == []


@pytest.mark.parametrize(
    "base,headers,peer",
    [
        ("http://evil.example", {}, "127.0.0.1"),
        ("http://127.0.0.1", {"origin": "https://evil.example"}, "127.0.0.1"),
        ("http://127.0.0.1", {"sec-fetch-site": "cross-site"}, "127.0.0.1"),
        ("http://127.0.0.1", {}, "192.168.1.5"),
    ],
)
async def test_picker_rejects_nonlocal_call_before_opening(
    tmp_path, monkeypatch, base, headers, peer
):
    import importlib

    module = importlib.import_module("skillforge_vm.api.app")

    def forbidden():
        pytest.fail("untrusted request opened native picker")

    monkeypatch.setattr(module, "select_directory", forbidden)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_app(WorkspaceManager(data_root=tmp_path / "data")), client=(peer, 1)
        ),
        base_url=base,
    ) as client:
        assert (
            await client.post("/api/local/select-directory", json={}, headers=headers)
        ).status_code == 422


@pytest.mark.skipif(os.name != "nt", reason="Windows native bridge")
def test_windows_bridge_unicode_cancel_timeout_and_lock(tmp_path, monkeypatch):
    folder = tmp_path / "中文目录"
    folder.mkdir()

    def run(args, **kwargs):
        assert "-STA" in args and "-EncodedCommand" in args
        assert kwargs["timeout"] == 120
        return SimpleNamespace(returncode=0, stdout=json.dumps({"path": str(folder)}))

    monkeypatch.setattr(picker.subprocess, "run", run)
    assert picker.select_directory() == str(folder)
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout='{"path":null}'),
    )
    assert picker.select_directory() is None

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("picker", 120)

    monkeypatch.setattr(picker.subprocess, "run", timeout)
    with pytest.raises(OperationFailedError, match="超时"):
        picker.select_directory()
    assert picker._picker_lock.acquire(False)
    try:
        with pytest.raises(WorkspaceBusyError):
            picker.select_directory()
    finally:
        picker._picker_lock.release()
