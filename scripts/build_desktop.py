"""构建内置独立 Python 运行时的 Windows 桌面便携包。"""

from __future__ import annotations

import argparse
import json
import shutil
import site
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/desktop/留痕"))
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("本轮仅构建 Windows 便携包，其他平台尚未验收。")
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"输出目录已存在，请指定新的 --output：{output}")
    electron = root / "desktop/node_modules/electron/dist"
    if not (electron / "electron.exe").is_file():
        raise SystemExit("请先执行 npm --prefix desktop ci")
    if not (root / "frontend/dist/index.html").is_file():
        raise SystemExit("请先执行 npm --prefix frontend run build")
    shutil.copytree(electron, output)
    (output / "electron.exe").rename(output / "留痕.exe")
    resources = output / "resources"
    app = resources / "app"
    app.mkdir()
    for name in ("main.cjs", "backend.cjs", "icon.png", "package.json"):
        shutil.copy2(root / "desktop" / name, app / name)
    python = resources / "python"
    shutil.copytree(
        Path(sys.base_prefix),
        python,
        ignore=shutil.ignore_patterns("site-packages", "__pycache__", "*.pyc"),
    )
    packages = python / "Lib/site-packages"
    packages.mkdir(parents=True, exist_ok=True)
    # Copy installed distributions, never .pth/editable pointers to the developer checkout.
    # Importing CLI/ASGI in isolation below detects missing distribution files.
    for location in site.getsitepackages():
        source = Path(location)
        if source.name != "site-packages":
            continue
        for item in source.iterdir():
            if (
                item.name.startswith(("_", "pip", "pytest", "ruff", "mypy"))
                or item.suffix == ".pth"
            ):
                continue
            target = packages / item.name
            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            else:
                shutil.copy2(item, target)
    # Private extension modules (e.g. _yaml) belong to runtime dependencies too.
    for location in site.getsitepackages():
        source = Path(location)
        if source.name == "site-packages":
            for item in source.glob("_*"):
                if item.suffix == ".pth" or item.name.startswith(("__", "_pytest", "_virtualenv")):
                    continue
                target = packages / item.name
                if item.is_dir():
                    shutil.copytree(
                        item,
                        target,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                else:
                    shutil.copy2(item, target)
    package = packages / "skillforge_vm"
    shutil.copytree(
        root / "src/skillforge_vm",
        package,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "web_assets"),
    )
    shutil.copytree(root / "frontend/dist", package / "web_assets")
    (output / "skillforge-vm.cmd").write_text(
        '@echo off\n"%~dp0resources\\python\\python.exe" -I -X utf8 -m skillforge_vm.cli.main %*\n',
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(python / "python.exe"),
            "-I",
            "-c",
            "import skillforge_vm.cli.desktop, skillforge_vm.cli.main; "
            "from skillforge_vm.api.app import create_app; print('isolated backend imports OK')",
        ],
        cwd=output,
        check=True,
    )
    manifest = {
        "python": sys.version,
        "electron": json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))[
            "devDependencies"
        ]["electron"],
        "platform": sys.platform,
    }
    (output / "build-info.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"便携包：{output / '留痕.exe'}")
    print("构建成功不等于干净机器、签名、离线与全部平台验收。")


if __name__ == "__main__":
    main()
