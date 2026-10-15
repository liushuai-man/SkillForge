"""M-12 命令行客户端：地址解析优先级、端口回退、阻塞命令的明确失败。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import typer
from typer.testing import CliRunner

from skillforge_vm.cli.client import (
    default_base_url,
    read_runtime_base_url,
    remove_runtime,
    resolve_base_url,
    write_runtime,
)
from skillforge_vm.cli.main import _bind_socket, _fail, app


def test_resolve_base_url_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILLFORGE_VM_URL", raising=False)
    assert resolve_base_url(None, data_root=tmp_path) == default_base_url()

    write_runtime("http://127.0.0.1:9001", data_root=tmp_path)
    assert resolve_base_url(None, data_root=tmp_path) == "http://127.0.0.1:9001"

    monkeypatch.setenv("SKILLFORGE_VM_URL", "http://127.0.0.1:9100")
    assert resolve_base_url(None, data_root=tmp_path) == "http://127.0.0.1:9100"

    assert resolve_base_url("http://127.0.0.1:9200/", data_root=tmp_path) == "http://127.0.0.1:9200"


def test_bind_socket_falls_back_when_preferred_taken() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    taken = holder.getsockname()[1]
    sock = _bind_socket("127.0.0.1", taken)
    try:
        assert sock.getsockname()[1] != taken
    finally:
        sock.close()
        holder.close()


def test_cli_help_lists_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "start" in result.output
    assert "init" in result.output


def test_diff_prints_report_summary(monkeypatch) -> None:
    from skillforge_vm.cli import main as cli

    report = {
        "summary": "检测到 1 处变化。",
        "overview": {
            "files": 1,
            "changes": 1,
            "clusters": 1,
            "risk": "low",
            "needs_review": 0,
        },
        "clusters": [{"label": "约束规则变化", "units": ["u-1"]}],
        "report_id": "RPT-test",
    }

    def get(self, path, **params):
        if path == "/api/workspaces":
            return [{"workspace_id": "w"}]
        assert params["layer"] == "L3"
        return report

    monkeypatch.setattr(cli.VmClient, "get", get)
    result = CliRunner().invoke(app, ["diff"])
    assert result.exit_code == 0, result.output
    assert "检测到 1 处变化" in result.output
    assert "RPT-test" in result.output


@pytest.mark.parametrize("command", [["restore", "tested"], ["undo"], ["restore", "--resume", "p"]])
@pytest.mark.parametrize("answer", ["n\n", "y\n"])
def test_restore_cli_confirmation(monkeypatch, command, answer):
    from skillforge_vm.cli import main as cli

    calls = []
    plan = {
        "no_change": False,
        "plan_id": "p",
        "before_rev": "b",
        "target_rev": "a",
        "changes": [{"path": "a.md", "action": "modify"}],
    }

    def get(self, path):
        return [{"workspace_id": "w"}] if path == "/api/workspaces" else plan

    def post(self, path, payload):
        calls.append((path, payload))
        if path.endswith("/apply"):
            return {"created": True, "revision": {"rev_id": "c", "seq": 3}}
        return plan

    monkeypatch.setattr(cli.VmClient, "get", get)
    monkeypatch.setattr(cli.VmClient, "post", post)
    result = CliRunner().invoke(app, command, input=answer)
    assert result.exit_code == 0, result.output
    assert "a.md" in result.output
    applies = [call for call in calls if call[0].endswith("/apply")]
    assert applies == (
        [("/api/workspaces/w/restore/plans/p/apply", {"confirm": True})] if answer == "y\n" else []
    )
    assert ("恢复完成" if answer == "y\n" else "未回写") in result.output


def test_fail_raises_exit_one() -> None:
    with pytest.raises(typer.Exit) as info:
        _fail("boom")
    assert info.value.exit_code == 1


@pytest.mark.parametrize("raw", ["[]", "null", "1", "{", '{"base_url":"invalid"}'])
def test_malformed_runtime_is_ignored(tmp_path: Path, raw: str) -> None:
    (tmp_path / "runtime.json").write_text(raw, encoding="utf-8")
    assert read_runtime_base_url(data_root=tmp_path) is None


def test_runtime_cleanup_only_removes_owner(tmp_path: Path) -> None:
    path = write_runtime("http://127.0.0.1:9001", data_root=tmp_path)
    remove_runtime("http://127.0.0.1:9002", data_root=tmp_path)
    assert path.exists()
    remove_runtime("http://127.0.0.1:9001", data_root=tmp_path)
    assert not path.exists()


def test_global_data_root_is_used_for_business_commands(tmp_path: Path, monkeypatch) -> None:
    from skillforge_vm.cli import main as cli

    monkeypatch.delenv("SKILLFORGE_VM_URL", raising=False)
    write_runtime("http://127.0.0.1:9009", data_root=tmp_path)
    seen = []
    monkeypatch.setattr(cli.VmClient, "get", lambda self, path: seen.append(self.base_url) or [])
    result = CliRunner().invoke(app, ["--data-root", str(tmp_path), "workspaces"])
    assert result.exit_code == 0
    assert seen == ["http://127.0.0.1:9009"]


def test_real_cli_service_discovers_fallback_port_and_snapshots(tmp_path: Path) -> None:
    root = tmp_path / "data"
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "a.md").write_bytes(b"before")
    env = dict(os.environ)
    env.pop("SKILLFORGE_VM_URL", None)
    with socket.socket() as holder, (tmp_path / "server.log").open("w") as log:
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "skillforge_vm.cli.main",
                "--data-root",
                str(root),
                "start",
                "--port",
                str(port),
            ],
            stdout=log,
            stderr=log,
            env=env,
        )
        try:
            deadline = time.monotonic() + 15
            url = None
            while time.monotonic() < deadline:
                url = read_runtime_base_url(data_root=root)
                if url:
                    break
                assert process.poll() is None
                time.sleep(0.05)
            assert url and not url.endswith(f":{port}")
            with httpx.Client(base_url=url, trust_env=False) as client:
                assert client.get("/api/health").json()["ok"]
                command = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "skillforge_vm.cli.main",
                        "--data-root",
                        str(root),
                        "init",
                        str(skill),
                    ],
                    capture_output=True,
                    timeout=15,
                    env=env,
                )
                assert command.returncode == 0, command.stderr
                ws = client.get("/api/workspaces").json()["data"][0]["workspace_id"]
                time.sleep(0.7)
                (skill / "a.md").write_bytes(b"after")
                for _ in range(100):
                    status = client.get(f"/api/workspaces/{ws}/status").json()["data"]
                    if status["head_seq"] == 2:
                        break
                    time.sleep(0.05)
                assert status["head_seq"] == 2
                assert not status["has_pending_changes"]
        finally:
            process.kill()
            process.wait(timeout=10)
