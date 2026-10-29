"""Electron's private stdio supervisor; never opens an external browser."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from ..core.config import Settings
from .client import CliError, read_runtime_base_url
from .gui import _has_web, _local_url, _prepare_assets, _ready
from .service import run_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    stop = threading.Event()

    def watch_parent() -> None:
        # EOF also arrives when Electron crashes. No detached service is spawned.
        sys.stdin.buffer.read(1)
        stop.set()

    threading.Thread(target=watch_parent, daemon=True).start()

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
