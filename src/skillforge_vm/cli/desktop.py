"""Electron's private stdio supervisor; never opens an external browser."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from ..core.config import Settings
from .client import CliError, read_runtime_base_url
from .gui import _has_web, _local_url, _prepare_assets, _ready
from .service import run_service


def watch_process(pid: int, stop: threading.Event) -> None:
    """Watch a stable OS process handle even if descendants retain pipe handles."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            stop.set()  # Parent disappeared or cannot be watched: never leave a writer.
            return
        try:
            while not stop.is_set():
                result = kernel.WaitForSingleObject(handle, 200)
                if result != 0x00000102:  # WAIT_TIMEOUT
                    stop.set()
                    break
        finally:
            kernel.CloseHandle(handle)
    else:
        while not stop.wait(0.2):
            if os.getppid() != pid:
                stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    stop = threading.Event()

    def watch_parent() -> None:
        # EOF also arrives when Electron crashes. No detached service is spawned.
        # A buffered read in a daemon thread can hold CPython's stdin lock at exit
        # when the process watchdog fires before EOF. Use the raw OS descriptor.
        os.read(sys.stdin.fileno(), 1)
        stop.set()

    threading.Thread(target=watch_parent, daemon=True).start()
    if args.parent_pid is not None:
        if args.parent_pid <= 0:
            parser.error("parent-pid must be positive")
        threading.Thread(target=watch_process, args=(args.parent_pid, stop), daemon=True).start()

    def announce(base: str, *, owned: bool) -> None:
        print("SKILLFORGE_DESKTOP " + json.dumps({"base_url": base, "owned": owned}), flush=True)

    try:
        _prepare_assets()
        if stop.is_set():
            return
        root = args.data_root or Settings().data_root
        existing = read_runtime_base_url(data_root=root)
        if existing and _ready(_local_url(existing)):
            base = _local_url(existing)
            if not _has_web(base):
                raise CliError("已有服务缺少网页资源，请先停止旧服务再打开客户端。")
            announce(base, owned=False)
            stop.wait()
        else:
            run_service(root, on_ready=lambda base: announce(base, owned=True), stop=stop)
    except (CliError, OSError) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
