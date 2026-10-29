"""留痕测试入口：回归、隔离桌面试用与真实流程验收。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_support import test_root

ROOT = Path(__file__).resolve().parents[1]


def python_command(target: str, *, module: bool = False) -> list[str]:
    # Keep uv's active environment, including its executable and installed dependencies.
    return [sys.executable, "-X", "utf8", *(["-m", target] if module else [target])]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="首次准备：uv sync；npm --prefix frontend ci；npm --prefix desktop ci。"
        "测试根由 SKILLFORGE_TEST_ROOT 覆盖；每次桌面/便携测试自动分配新目录。"
        "不使用真实技能；本机通过不等于新机器、断网或跨平台通过。",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="check",
        choices=("check", "desktop", "smoke", "experience", "portable"),
        help="check=自动回归；desktop=隔离桌面手动试用；smoke=桌面自动验收；"
        "experience=真实服务/命令行；portable=便携包验收",
    )
    parser.add_argument("--bundle", type=Path, help="portable 模式的便携包目录")
    args = parser.parse_args()
    if args.mode == "portable" and args.bundle is None:
        parser.error("portable 模式需要 --bundle 指定便携包目录")
    if args.mode != "portable" and args.bundle is not None:
        parser.error("--bundle 仅用于 portable 模式")
    npm = shutil.which("npm")
    if args.mode in {"check", "desktop", "smoke"}:
        if not npm or not (ROOT / "frontend/node_modules").is_dir():
            parser.error("缺少 Node.js/npm 或前端依赖，请先执行 npm --prefix frontend ci")
        if not (ROOT / "desktop/node_modules/electron").is_dir():
            parser.error("缺少桌面依赖，请先执行 npm --prefix desktop ci")
    executable = (
        ROOT
        / "desktop/node_modules/electron/dist"
        / ("electron.exe" if os.name == "nt" else "electron")
    )
    if args.mode == "desktop" and not executable.is_file():
        parser.error("缺少 Electron 运行包，请重新执行 npm --prefix desktop ci")
    if args.mode == "portable":
        args.bundle = args.bundle.resolve()
        if not any((args.bundle / name).is_file() for name in ("留痕.exe", "SkillForge-VM.exe")):
            parser.error("便携包目录中没有留痕.exe（或历史 SkillForge-VM.exe）")
    env = {**os.environ, "SKILLFORGE_TEST_ROOT": str(test_root()), "PYTHONIOENCODING": "utf-8"}

    def run(command: list[str]) -> None:
        subprocess.run(command, cwd=ROOT, env=env, check=True)

    if args.mode == "check":
        for title, command in (
            ("后端静态检查", [*python_command("ruff", module=True), "check", "."]),
            ("后端回归", [*python_command("pytest", module=True), "-q"]),
            ("前端构建", [npm, "--prefix", "frontend", "run", "build"]),
            ("桌面通信单测", [npm, "--prefix", "desktop", "test"]),
        ):
            print(f"正在执行：{title}", flush=True)
            run(command)
    elif args.mode == "experience":
        run(python_command(str(ROOT / "scripts/check_experience.py")))
    else:
        parent = Path(tempfile.mkdtemp(prefix=f"{args.mode}-", dir=test_root()))
        data = parent / "data"  # Must remain absent until smoke/portable starts.
        print(f"本次独立测试目录：{parent}", flush=True)
        if args.mode == "portable":
            run(
                [
                    *python_command(str(ROOT / "scripts/verify_desktop.py")),
                    str(args.bundle),
                    "--data-root",
                    str(data),
                ]
            )
        else:
            run([npm, "--prefix", "frontend", "run", "build"])
            if args.mode == "desktop":
                print("关闭窗口进入托盘；从应用菜单或托盘选择退出后结束本次试用。", flush=True)
                run([str(executable), str(ROOT / "desktop"), "--data-root", str(data)])
            else:
                run([npm, "--prefix", "desktop", "run", "smoke", "--", "--data-root", str(data)])
    print("本次检查已完成。" if args.mode != "desktop" else "本次桌面试用已结束。", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"检查失败，退出码：{exc.returncode}。请查看上方具体诊断。", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
