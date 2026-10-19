"""A 线固定保存序列与捕获耗时；只在新建临时 Skill / 数据目录运行。"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import statistics
import tempfile
import time
from pathlib import Path

from test_support import test_root

from skillforge_vm.api.service import WorkspaceService
from skillforge_vm.db.connection import connect
from skillforge_vm.objectstore.store import ObjectStore
from skillforge_vm.watcher.engine import SnapshotEngine
from skillforge_vm.workspace.manager import WorkspaceManager


def summary(values):
    ordered = sorted(values)
    return {
        "count": len(values),
        "p50_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[math.ceil(len(values) * 0.95) - 1], 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saves", type=int, default=10000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.saves < 30:
        parser.error("至少 30 次保存")
    result = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cache": "同进程，OS缓存未清空；无报告缓存",
        "physical_medium": "未识别",
        "allocated_bytes": None,
        "seed": 20261013,
    }
    with tempfile.TemporaryDirectory(prefix="skillforge-benchmark-", dir=test_root()) as tmp:
        root = Path(tmp)
        result["volume"] = root.drive or "/"
        skill = root / "skill"
        skill.mkdir()
        file = skill / "a.md"
        file.write_bytes(b"A" * 1024)
        manager = WorkspaceManager(data_root=root / "data")
        handle = manager.init(skill).workspace
        engine = SnapshotEngine(handle)
        timings = {"unchanged": [], "historical": [], "unique": []}
        created = {name: 0 for name in timings}
        for i in range(args.saves):
            if i % 3 == 0:
                name = "unchanged"
            elif i % 3 == 1:
                name = "historical"
                file.write_bytes((b"A" if i % 2 else b"B") * 1024)
            else:
                name = "unique"
                file.write_bytes(str(i).encode().ljust(1024, b"x"))
            start = time.perf_counter()
            capture = engine.capture()
            timings[name].append((time.perf_counter() - start) * 1000)
            created[name] += int(capture.created)
        result["sequence"] = {
            "saves": args.saves,
            "files": 1,
            "bytes": 1024,
            "created": created,
            "timing": {k: summary(v) for k, v in timings.items()},
        }
        objects = [p for p in handle.paths.objects_dir.rglob("*") if p.is_file()]
        result["sequence"]["unique_objects"] = len(objects)
        result["sequence"]["compressed_bytes"] = sum(p.stat().st_size for p in objects)
        conn = connect(handle.paths.db_file)
        try:
            result["sequence"]["revisions"] = conn.execute(
                "SELECT COUNT(*) FROM revision"
            ).fetchone()[0]
            result["sequence"]["indexed_objects"] = conn.execute(
                "SELECT COUNT(*) FROM object"
            ).fetchone()[0]
        finally:
            conn.close()
        result["sequence"]["database_bytes"] = handle.paths.db_file.stat().st_size
        assert created["unchanged"] == 0
        assert len(objects) == result["sequence"]["indexed_objects"]
        rng = random.Random(20261013)
        captures, status_times = [], []
        service = WorkspaceService(manager)
        before_bytes = sum(p.stat().st_size for p in objects)
        for _ in range(30):
            file.write_bytes(rng.randbytes(1024 * 1024))
            start = time.perf_counter()
            service.status(handle.workspace_id)
            status_times.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            assert engine.capture().created
            captures.append((time.perf_counter() - start) * 1000)
        after_bytes = sum(
            p.stat().st_size for p in handle.paths.objects_dir.rglob("*") if p.is_file()
        )
        result["unique_1mib"] = {
            "files": 1,
            "bytes": 1024 * 1024,
            "capture_including_scan": summary(captures),
            "readonly_status": summary(status_times),
            "compressed_growth_bytes": after_bytes - before_bytes,
            "note": "全量捕获含扫描，比纯写入计时范围更大；30次不同随机完整blob，不代表行级增量",
        }
        store = ObjectStore(handle.paths.objects_dir)
        assert store.read(store.write_blob(file.read_bytes()).oid)[1] == file.read_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
