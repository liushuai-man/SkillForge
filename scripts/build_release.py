"""构建包含预构建网页的 wheel；在临时 staging 中打包，不改源包目录。"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-frontend-build", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("构建需要已安装的 uv")
    if not args.skip_frontend_build:
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit("发布构建需要 Node/npm；终端用户运行时不需要")
        subprocess.run([npm, "run", "build"], cwd=root / "frontend", check=True)
    frontend = root / "frontend" / "dist"
    if not (frontend / "index.html").is_file():
        raise SystemExit("缺少 frontend/dist/index.html，请先构建前端")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="skillforge-release-") as tmp:
        staging = Path(tmp)
        for name in ("pyproject.toml", "README.md"):
            shutil.copy2(root / name, staging / name)
        shutil.copytree(
            root / "src",
            staging / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "web_assets"),
        )
        shutil.copytree(frontend, staging / "src" / "skillforge_vm" / "web_assets")
        wheel_dir = staging / "wheel"
        subprocess.run(
            [uv, "build", "--wheel", "--offline", "--out-dir", str(wheel_dir)],
            cwd=staging,
            check=True,
        )
        (wheel,) = wheel_dir.glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            prefix = "skillforge_vm/web_assets/"
            html = archive.read(prefix + "index.html").decode("utf-8")
            assets = re.findall(r'(?:src|href)="(/assets/[^"?#]+)', html)
            if not assets:
                raise SystemExit("前端入口没有构建资源引用，拒绝交付")
            for asset in assets:
                archive.getinfo(prefix + asset.lstrip("/"))
        target = output / wheel.name
        shutil.copy2(wheel, target)
        shutil.copy2(root / "start-web.cmd", output / "start-web.cmd")
        print(f"已验证 wheel 中的网页入口及资源：{target}")
        print("注意：打包成功不替代全文对齐、CLI、恢复和安装环境验收。")


if __name__ == "__main__":
    main()
