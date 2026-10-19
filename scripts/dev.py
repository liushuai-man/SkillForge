"""Start the development API and Vite together; stop owned processes on exit."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import site
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from process_job import ProcessJob
from test_support import test_root

from skillforge_vm.cli.client import CliError, read_runtime_base_url
from skillforge_vm.cli.gui import _local_url


def ready(url: str) -> bool:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            url, timeout=1
        ) as response:
            if response.status != 200:
                return False
            if url.endswith("/api/health"):
                body = json.load(response)
                return (
                    isinstance(body, dict)
                    and body.get("ok") is True
                    and isinstance(body.get("data"), dict)
                    and body.get("data", {}).get("status") == "ok"
                )
            return True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        if process.poll() is None:
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="verify startup, then stop")
    parser.add_argument("--port", type=int, default=5173)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    frontend = project / "frontend"
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        raise SystemExit("开发启动需要 Node.js/npm，请先安装。")
    marker = frontend / "node_modules" / ".package-lock.json"
    if (
        not marker.is_file()
        or marker.stat().st_mtime_ns < (frontend / "package-lock.json").stat().st_mtime_ns
    ):
        subprocess.run([npm, "ci"], cwd=frontend, check=True)
    output = project / "dist" / "dev"
    output.mkdir(parents=True, exist_ok=True)
    data = output / "data"
    runtime = data / "runtime.json"
    existing = read_runtime_base_url(data_root=data)
    if existing and ready(_local_url(existing) + "/api/health"):
        raise RuntimeError(
            f"开发数据根已有服务运行：{existing}。请在原开发窗口按 Ctrl+C 停止后再启动；"
            f"数据目录：{data}（不会自动终止其他服务）。"
        )
    env = dict(os.environ)
    env.pop("SKILLFORGE_VM_URL", None)
    env["SKILLFORGE_VM_DATA_ROOT"] = str(data)
    env["SKILLFORGE_TEST_ROOT"] = str(test_root())
    env["PYTHONIOENCODING"] = "utf-8"
    bootstrap = (
        "import site, runpy; "
        f"[site.addsitedir(p) for p in {site.getsitepackages()!r}]; "
        "runpy.run_module('skillforge_vm.cli.main', run_name='__main__')"
    )
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    processes: list[subprocess.Popen] = []
    job = ProcessJob()
    try:
        with (output / "service.log").open("a", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [
                    getattr(sys, "_base_executable", sys.executable),
                    "-c",
                    bootstrap,
                    "start",
                    "--port",
                    "0",
                ],
                cwd=project,
                env=env,
                stdout=log,
                stderr=log,
                **group,
            )
            processes.append(backend)
            job.add(backend.pid)
            deadline = time.monotonic() + 30
            base = ""
            while time.monotonic() < deadline:
                if backend.poll() is not None:
                    message = (output / "service.log").read_text(encoding="utf-8", errors="replace")
                    reason = (
                        "开发数据根已被其他服务占用"
                        if "WorkspaceBusyError" in message
                        else message[-2000:].strip()
                    )
                    raise RuntimeError(
                        f"开发服务启动失败：{reason}\n日志：{output / 'service.log'}"
                    )
                try:
                    recorded = json.loads(runtime.read_text(encoding="utf-8"))
                    if recorded["pid"] == backend.pid and ready(
                        recorded["base_url"] + "/api/health"
                    ):
                        base = recorded["base_url"]
                        break
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.1)
            if not base:
                raise RuntimeError("等待开发服务启动超时")
            env["SKILLFORGE_DEV_API_URL"] = base
            page = f"http://127.0.0.1:{args.port}"
            if ready(page):
                raise RuntimeError(
                    f"前端端口 {args.port} 已占用，请关闭旧开发进程或使用 --port 指定其他端口"
                )
            web = subprocess.Popen(
                [
                    node,
                    str(frontend / "node_modules" / "vite" / "bin" / "vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                    "--strictPort",
                    *([] if args.no_browser or args.check else ["--open"]),
                ],
                cwd=frontend,
                env=env,
                **group,
            )
            processes.append(web)
            job.add(web.pid)
            deadline = time.monotonic() + 30
            while not ready(page + "/api/health"):
                if web.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("开发前端启动失败，请检查上方错误与端口占用")
                time.sleep(0.1)
            print(
                f"页面：{page}\nAPI：{base}\n测试 Skill：{env['SKILLFORGE_TEST_ROOT']}", flush=True
            )
            print("按 Ctrl+C 停止前后端。后端代码修改后重新运行此命令。", flush=True)
            if args.check:
                return
            while all(process.poll() is None for process in processes):
                time.sleep(0.3)
            raise RuntimeError("开发进程已退出")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            for process in reversed(processes):
                try:
                    stop(process)
                except (OSError, subprocess.SubprocessError) as exc:
                    print(f"进程 {process.pid} 清理异常：{exc}", file=sys.stderr)
        finally:
            job.close()


if __name__ == "__main__":
    try:
        main()
    except (CliError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"启动失败：{exc}") from None
