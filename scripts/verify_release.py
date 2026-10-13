"""离线安装 wheel 到临时虚拟环境，移除 Node PATH，验证真实 HTTP/CLI。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import site
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument(
        "--reuse-installed-deps",
        action="store_true",
        help="仅验证wheel运行，复用当前环境依赖；不算干净环境依赖安装通过",
    )
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("验证需要已安装的 uv 和离线依赖缓存")
    with tempfile.TemporaryDirectory(prefix="skillforge-installed-") as tmp:
        root = Path(tmp)
        venv = root / "venv"
        subprocess.run([uv, "venv", "--offline", str(venv)], check=True)
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--offline",
                "--python",
                str(python),
                *(["--no-deps"] if args.reuse_installed_deps else []),
                str(wheel),
            ],
            check=True,
        )
        env = dict(os.environ)
        env["PATH"] = ""
        env["PYTHONPATH"] = (
            os.pathsep.join(site.getsitepackages()) if args.reuse_installed_deps else ""
        )
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("SKILLFORGE_VM_URL", None)
        env["SKILLFORGE_VM_DATA_ROOT"] = str(root / "data")
        subprocess.run(
            [str(python), "-c", "import shutil; assert shutil.which('node') is None"],
            cwd=root,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-c",
                "import skillforge_vm; from pathlib import Path; "
                f"assert Path(skillforge_vm.__file__).is_relative_to(Path({str(venv)!r}))",
            ],
            cwd=root,
            env=env,
            check=True,
        )
        with (root / "service.log").open("w", encoding="utf-8") as log:
            service = subprocess.Popen(
                [str(python), "-m", "skillforge_vm.cli.main", "start", "--port", "0"],
                cwd=root,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                runtime = root / "data" / "runtime.json"
                for _ in range(200):
                    if runtime.is_file():
                        break
                    if service.poll() is not None:
                        raise RuntimeError((root / "service.log").read_text(encoding="utf-8"))
                    time.sleep(0.05)
                base = json.loads(runtime.read_text(encoding="utf-8"))["base_url"]
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def get(path):
                    with opener.open(base + path, timeout=5) as response:
                        return response.read()

                assert json.loads(get("/api/health"))["ok"]
                html = get("/").decode("utf-8")
                for asset in re.findall(r'(?:src|href)="(/assets/[^"?#]+)', html):
                    assert get(asset)
                skill = root / "skill"
                skill.mkdir()
                (skill / "SKILL.md").write_bytes(b"# before")
                subprocess.run(
                    [str(python), "-m", "skillforge_vm.cli.main", "init", str(skill)],
                    cwd=root,
                    env=env,
                    check=True,
                    timeout=15,
                )
                ws = json.loads(get("/api/workspaces"))["data"][0]["workspace_id"]
                time.sleep(0.7)
                (skill / "SKILL.md").write_bytes(b"# after")
                for _ in range(100):
                    status = json.loads(get(f"/api/workspaces/{ws}/status"))["data"]
                    if status["head_seq"] == 2:
                        break
                    time.sleep(0.05)
                assert status["head_seq"] == 2 and not status["has_pending_changes"]
                subprocess.run(
                    [str(python), "-m", "skillforge_vm.cli.main", "tag", "tested"],
                    cwd=root,
                    env=env,
                    check=True,
                    timeout=15,
                )
                for command, expected, seq in (
                    (["restore", "@~1", "--yes"], b"# before", 3),
                    (["undo", "--yes"], b"# after", 4),
                ):
                    subprocess.run(
                        [str(python), "-m", "skillforge_vm.cli.main", *command],
                        cwd=root,
                        env=env,
                        check=True,
                        timeout=15,
                    )
                    assert (skill / "SKILL.md").read_bytes() == expected
                    status = json.loads(get(f"/api/workspaces/{ws}/status"))["data"]
                    assert status["head_seq"] == seq and status["pending_restore"] is None
                print("PASS: wheel 安装、无 Node PATH、网页资源、CLI、自动快照、锚点、恢复与撤销")
                if args.reuse_installed_deps:
                    print("LIMITATION: 复用现有依赖，干净环境依赖安装未验证")
            finally:
                if service.poll() is None:
                    service.kill()
                service.wait(timeout=10)


if __name__ == "__main__":
    main()
