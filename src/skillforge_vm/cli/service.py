"""Shared local server runner for CLI and the desktop supervisor."""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path
from threading import Event

import uvicorn

from ..api.app import create_app
from ..workspace.manager import WorkspaceManager
from .client import CliError, remove_runtime, write_runtime


def bind_socket(host: str, preferred: int) -> socket.socket:
    import os

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, preferred))
    except OSError:
        sock.bind((host, 0))
    return sock


def run_service(
    data_root: Path,
    host: str = "127.0.0.1",
    port: int = 8756,
    *,
    on_ready: Callable[[str], None],
    stop: Event | None = None,
) -> None:
    sock = bind_socket(host, port)
    actual_port = sock.getsockname()[1]
    base_url = f"http://{host}:{actual_port}"

    class LocalServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                write_runtime(base_url, data_root=data_root)
                on_ready(base_url)

        async def on_tick(self, counter):
            if stop is not None and stop.is_set():
                # SSE's graceful drain watches this flag as well as uvicorn.
                self.should_exit = True
            return await super().on_tick(counter)

        async def shutdown(self, sockets=None):
            remove_runtime(base_url, data_root=data_root)
            await super().shutdown(sockets=sockets)

    try:
        if stop is not None and stop.is_set():
            return
        server = LocalServer(
            uvicorn.Config(
                create_app(WorkspaceManager(data_root=data_root)),
                host=host,
                port=actual_port,
                log_level="info",
            )
        )
        server.run(sockets=[sock])
        if not server.started:
            raise CliError("服务启动失败，请检查数据根占用及配置诊断")
    finally:
        sock.close()
