"""M-12 命令行客户端：地址解析优先级、端口回退、阻塞命令的明确失败。"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from skillforge_vm.cli.client import (
    default_base_url,
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


@pytest.mark.parametrize("command", ["diff", "undo"])
def test_blocked_commands_exit_nonzero(command: str) -> None:
    result = CliRunner().invoke(app, [command])
    assert result.exit_code == 1


def test_fail_raises_exit_one() -> None:
    with pytest.raises(typer.Exit) as info:
        _fail("boom")
    assert info.value.exit_code == 1