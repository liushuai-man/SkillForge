"""GUI bootstrap serves the same local API and never needs a second writer."""

from importlib import import_module

import httpx
import pytest

from skillforge_vm.api.app import create_app
from skillforge_vm.workspace.manager import WorkspaceManager


@pytest.mark.parametrize("packaged", [False, True])
async def test_built_source_web_is_served_and_packaged_assets_take_priority(
    tmp_path, monkeypatch, packaged
):
    app_module = import_module("skillforge_vm.api.app")
    fake_module = tmp_path / "src" / "skillforge_vm" / "api" / "app.py"
    monkeypatch.setattr(app_module, "__file__", str(fake_module))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    source_assets = tmp_path / "frontend" / "dist"
    source_assets.mkdir(parents=True)
    (source_assets / "index.html").write_text("<h1>source</h1>")
    if packaged:
        package_assets = fake_module.parents[1] / "web_assets"
        package_assets.mkdir(parents=True)
        (package_assets / "index.html").write_text("<h1>packaged</h1>")
    app = create_app(WorkspaceManager(data_root=tmp_path / "data"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert page.text == ("<h1>packaged</h1>" if packaged else "<h1>source</h1>")
        assert (await client.get("/api/health")).json()["data"] == {"status": "ok"}
