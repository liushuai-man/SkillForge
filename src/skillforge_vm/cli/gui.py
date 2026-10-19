"""Prepare or reuse the local web application without a terminal workflow."""

from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, build_opener

from ..core.config import Settings
from .client import CliError, read_runtime_base_url


def _prepare_assets() -> None:
    module = Path(__file__).resolve()
    if (module.parents[1] / "web_assets" / "index.html").is_file():
        return
    project = module.parents[3]
    if (project / "src" / "skillforge_vm" / "cli" / "gui.py").resolve() != module or not (
        project / "pyproject.toml"
    ).is_file():
        raise CliError("安装包缺少网页资源，请重新安装完整的 SkillForge wheel。")
    frontend = project / "frontend"
    index = frontend / "dist" / "index.html"
    inputs = [
        frontend / name
        for name in (
            "package.json",
            "package-lock.json",
            "index.html",
            "tsconfig.json",
            "vite.config.ts",
        )
    ]
    inputs.extend(path for path in (frontend / "src").rglob("*") if path.is_file())
    newest_input = max(path.stat().st_mtime_ns for path in inputs if path.is_file())
    if index.is_file() and index.stat().st_mtime_ns >= newest_input:
        return
    npm = shutil.which("npm")
    if npm is None:
        raise CliError("源码首次启动需要 Node.js/npm 来构建网页；完整安装包不需要 Node。")
    marker = frontend / "node_modules" / ".package-lock.json"
    try:
        if (
            not marker.is_file()
            or marker.stat().st_mtime_ns < (frontend / "package-lock.json").stat().st_mtime_ns
        ):
            subprocess.run([npm, "ci"], cwd=frontend, check=True)
        subprocess.run([npm, "run", "build"], cwd=frontend, check=True)
    except subprocess.CalledProcessError as exc:
        raise CliError("网页依赖安装或构建失败，请查看启动窗口中的具体错误。") from exc


def _local_url(value: str) -> str:
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.port
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        ):
            return value.rstrip("/")
    except ValueError:
        pass
    raise CliError("运行记录不是有效的本机 HTTP 地址，拒绝打开。")


def _ready(base: str) -> bool:
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(base + "/api/health", timeout=1) as response:
            body = json.load(response)
            return (
                isinstance(body, dict)
                and body.get("ok") is True
                and isinstance(body.get("data"), dict)
                and body["data"].get("status") == "ok"
            )
    except (OSError, ValueError, URLError):
        return False


def _has_web(base: str) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(base + "/", timeout=2) as response:
            return response.headers.get_content_type() == "text/html"
    except (OSError, ValueError, URLError):
        return False


def launch(data_root: Path | None = None, *, open_browser: bool = True) -> str:
    """Share CLI's data root, runtime discovery and single-writer service."""
    _prepare_assets()
    root = data_root or Settings().data_root
    existing = read_runtime_base_url(data_root=root)
    if existing and _ready(_local_url(existing)):
        base = _local_url(existing)
        if not _has_web(base):
            raise CliError("已有服务未加载网页，请关闭原服务窗口，再双击 start-web.cmd。")
    else:
        root.mkdir(parents=True, exist_ok=True)
        bootstrap = (
            "import site, runpy; "
            f"[site.addsitedir(p) for p in {site.getsitepackages()!r}]; "
            "runpy.run_module('skillforge_vm.cli.main', run_name='__main__')"
        )
        with (root / "gui-launch.log").open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    getattr(sys, "_base_executable", sys.executable),
                    "-c",
                    bootstrap,
                    "--data-root",
                    str(root),
                    "start",
                ],
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        base = ""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            recorded = read_runtime_base_url(data_root=root)
            if recorded and _ready(_local_url(recorded)):
                base = _local_url(recorded)
                break
            if process.poll() is not None:
                raise CliError(f"本机服务启动失败，详情见 {root / 'gui-launch.log'}")
            time.sleep(0.1)
        if not base:
            process.terminate()
            process.wait(timeout=5)
            raise CliError(f"等待服务启动超时，详情见 {root / 'gui-launch.log'}")
        if not _has_web(base):
            raise CliError("服务已启动但网页资源未就绪，请检查安装包或网页构建结果。")
    if open_browser:
        webbrowser.open(base + "/")
    return base
