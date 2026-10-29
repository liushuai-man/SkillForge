"""Exercise a Windows portable desktop without external Python/Node on PATH."""

from __future__ import annotations

import _winapi
import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--data-root", required=True, type=Path, help="new isolated test directory")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    data = args.data_root.resolve()
    if data.exists():
        raise SystemExit(f"验证目录必须不存在：{data}")
    data.mkdir(parents=True)
    skill = data / "generated-skill"
    skill.mkdir()
    file = skill / "SKILL.md"
    file.write_text("# portable\nfirst\n", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
        "PYTHONHOME": str(data / "missing"),
        "PYTHONPATH": str(data / "missing"),
        "PYTHONIOENCODING": "utf-8",
    }
    process = subprocess.Popen(
        [str(bundle / "SkillForge-VM.exe"), "--data-root", str(data)], cwd=bundle, env=env
    )
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(url, body=None):
        req = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with http.open(req, timeout=3) as response:
            return json.load(response)

    def stop():
        handle = None
        if (data / "runtime.json").exists():
            pid = json.loads((data / "runtime.json").read_text())["pid"]
            try:
                handle = _winapi.OpenProcess(0x00100000, False, pid)
            except OSError:
                pass
        if process.poll() is None:
            process.kill()  # Deliberate parent crash, not graceful app.quit.
            process.wait(timeout=5)
        if handle is not None:
            try:
                assert _winapi.WaitForSingleObject(handle, 10000) == _winapi.WAIT_OBJECT_0, (
                    "桌面崩溃后后端进程仍存活"
                )
            finally:
                _winapi.CloseHandle(handle)

    try:
        deadline = time.monotonic() + 45
        while not (data / "runtime.json").exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"桌面启动失败：{process.returncode}")
            time.sleep(0.1)
        base = json.loads((data / "runtime.json").read_text())["base_url"]
        assert request(base + "/api/health")["ok"]
        ws = request(base + "/api/workspaces", {"path": str(skill)})["data"]["workspace"][
            "workspace_id"
        ]
        file.write_text("# portable\nsecond\n", encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                comparison = request(f"{base}/api/workspaces/{ws}/compare")
            except urllib.error.HTTPError as exc:
                error = json.load(exc)
                if exc.code == 409 and error.get("error", {}).get("code") == "snapshot_unstable":
                    time.sleep(0.1)  # Existing contract: wait for save to be committed.
                    continue
                raise
            if "second" in json.dumps(comparison) and "first" in json.dumps(comparison):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("保存未生成比较结果")
        cli = subprocess.run(
            [
                str(bundle / "resources/python/python.exe"),
                "-I",
                "-X",
                "utf8",
                "-m",
                "skillforge_vm.cli.main",
                "--data-root",
                str(data),
                "diff",
            ],
            cwd=bundle,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        assert cli.returncode == 0, cli.stderr
        assert "-first" in cli.stdout and "+second" in cli.stdout, cli.stdout
        duplicate = subprocess.run(
            [str(bundle / "SkillForge-VM.exe"), "--data-root", str(data)],
            cwd=bundle,
            env=env,
            timeout=10,
        )
        assert duplicate.returncode == 0
        old_pid = json.loads((data / "runtime.json").read_text())["pid"]
        stop()
        # OS job cleanup may kill the whole tree before Python can remove runtime.
        # Check actual process death above, then require recovery with preserved history.
        process = subprocess.Popen(
            [str(bundle / "SkillForge-VM.exe"), "--data-root", str(data)], cwd=bundle, env=env
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if (data / "runtime.json").exists():
                runtime = json.loads((data / "runtime.json").read_text())
                if runtime["pid"] != old_pid:
                    base = runtime["base_url"]
                    break
            if process.poll() is not None:
                raise RuntimeError("强杀后重启失败")
            time.sleep(0.1)
        else:
            raise AssertionError("强杀后未发布新 runtime")
        recovered = request(f"{base}/api/workspaces/{ws}/compare")
        assert recovered["data"] == comparison["data"], "重启后的版本和 patch 不一致"
        stop()
        evidence = {
            "ok": True,
            "bundle": str(bundle),
            "checks": [
                "portable startup",
                "no external Python/Node PATH",
                "poisoned Python env ignored",
                "save/snapshot",
                "CLI patch",
                "duplicate launch",
                "parent crash cleanup",
                "restart preserves versions and patch",
            ],
        }
        (data / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence))
    finally:
        stop()


if __name__ == "__main__":
    main()
