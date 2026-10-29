"""Real-process ownership and shutdown checks for the desktop's local backend."""

import json
import os
import queue
import site
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx


def python_module(module):
    bootstrap = (
        "import site,runpy; "
        f"[site.addsitedir(p) for p in {site.getsitepackages()!r}]; "
        f"runpy.run_module({module!r},run_name='__main__',alter_sys=True)"
    )
    return [getattr(sys, "_base_executable", sys.executable), "-I", "-c", bootstrap]


def start_supervisor(root: Path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    log = (root.parent / f"{root.name}.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [*python_module("skillforge_vm.cli.desktop"), "--data-root", str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        env=env,
        text=True,
        encoding="utf-8",
    )
    messages = queue.Queue()

    def read():
        for line in process.stdout:
            if line.startswith("SKILLFORGE_DESKTOP "):
                messages.put(json.loads(line.removeprefix("SKILLFORGE_DESKTOP ")))

    threading.Thread(target=read, daemon=True).start()
    return process, messages, log


def finish(process):
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise


def test_owned_service_stops_on_parent_pipe_eof_and_can_restart(tmp_path):
    root = tmp_path / "owned"
    process, messages, log = start_supervisor(root)
    try:
        ready = messages.get(timeout=45)
        assert ready["owned"] is True
        with httpx.Client(trust_env=False) as client:
            assert client.get(ready["base_url"] + "/api/health").json()["ok"]
            assert "text/html" in client.get(ready["base_url"]).headers["content-type"]
            # Same discovery and HTTP endpoint used by the CLI, no second database.
            result = subprocess.run(
                [*python_module("skillforge_vm.cli.main"), "--data-root", str(root), "workspaces"],
                capture_output=True,
                timeout=15,
            )
            assert result.returncode == 0, result.stderr
            skill = tmp_path / "sample"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# Desktop test\n", encoding="utf-8")
            response = client.post(ready["base_url"] + "/api/workspaces", json={"path": str(skill)})
            ws = response.json()["data"]["workspace"]["workspace_id"]
            # Keep a real SSE consumer open while requesting shutdown.
            with client.stream("GET", ready["base_url"] + f"/api/workspaces/{ws}/events") as stream:
                assert stream.status_code == 200
                finish(process)
        assert process.returncode == 0
        assert not (root / "runtime.json").exists()
    finally:
        finish(process)
        log.close()
    restarted, messages, log = start_supervisor(root)
    try:
        assert messages.get(timeout=45)["owned"] is True
    finally:
        finish(restarted)
        log.close()


def test_reused_service_survives_desktop_exit(tmp_path):
    root = tmp_path / "shared"
    owner, messages, log = start_supervisor(root)
    reused = None
    reused_log = None
    try:
        first = messages.get(timeout=45)
        reused, messages, reused_log = start_supervisor(root)
        second = messages.get(timeout=45)
        assert second == {"base_url": first["base_url"], "owned": False}
        finish(reused)
        assert reused.returncode == 0
        assert owner.poll() is None
        with httpx.Client(trust_env=False) as client:
            assert client.get(first["base_url"] + "/api/health").json()["ok"]
    finally:
        if reused is not None:
            finish(reused)
            reused_log.close()
        finish(owner)
        log.close()


def test_parent_disappears_during_startup_without_leaving_service(tmp_path):
    root = tmp_path / "cancelled"
    process, _messages, log = start_supervisor(root)
    try:
        finish(process)
        assert process.returncode == 0
        time.sleep(0.1)
        assert not (root / "runtime.json").exists()
    finally:
        finish(process)
        log.close()
