"""把 M-05 结果组装成逐字节可复现的规范报告。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from ..cluster import cluster_changes
from ..db.connection import transaction
from ..diff import DiffEngine, Layer, analysis_version
from ..objectstore.objects import canonical_json
from ..objectstore.store import ObjectStore
from ..revision.models import Revision


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _risk(
    units: list[dict[str, Any]],
    degraded: list[dict],
    reviews: list[dict],
    *,
    semantic_requested: bool,
) -> dict:
    items = []
    for unit in units:
        kind, op = unit["kind"], unit["op"]
        if op == "delete" and kind in {"constraint", "capability", "tool", "output_format"}:
            level, rule, reason = "high", "risk.breaking_delete.v1", "删除关键语义要求"
        elif op == "modify" and kind in {
            "constraint",
            "workflow",
            "output_format",
            "parameter",
        }:
            level, rule, reason = "medium", "risk.behavior_modify.v1", "修改可能影响既有行为"
        else:
            level, rule, reason = "low", "risk.non_breaking_change.v1", "未命中破坏性规则"
        items.append(
            {
                "rule_id": rule,
                "level": level,
                "unit": unit["id"],
                "before": unit["before"],
                "after": unit["after"],
                "reason": reason,
            }
        )
    counts = {level: 0 for level in ("high", "medium", "low", "unknown")}
    for item in items:
        counts[item["level"]] += 1
    if not semantic_requested:
        counts["unknown"] += 1
    if degraded or reviews:
        counts["unknown"] += len(degraded) + len(reviews)
    if counts["high"]:
        level = "high"
    elif counts["unknown"]:
        level = "unknown"
    elif counts["medium"]:
        level = "medium"
    else:
        level = "low"
    return {"level": level, "counts": counts, "items": items}


def _layer_status(requested: Layer, depth: int, degraded: list[dict[str, str]]) -> str:
    if requested.depth < depth:
        return "not_requested"
    if any(int(item["available_layer"][1]) < depth for item in degraded):
        return "degraded"
    return "computed"


def _summary(files: int, changes: int | None, clusters: int, risk: str, reviews: int) -> str:
    if not files:
        return "当前版本与基线没有变化。"
    suffix = f"，其中 {reviews} 项需要确认" if reviews else ""
    semantic = "语义层未计算" if changes is None else f"已识别 {changes} 处语义变化"
    risk_label = {"high": "高", "medium": "中", "low": "低", "unknown": "未知"}[risk]
    return f"检测到 {files} 个文件变化，{semantic}，归为 {clusters} 组，{risk_label}风险{suffix}。"


def build_report(
    conn: sqlite3.Connection,
    object_store: ObjectStore,
    *,
    ws_id: str,
    base: Revision | None,
    head: Revision,
    base_files: dict[str, tuple[str, str]],
    head_files: dict[str, tuple[str, str]],
    layer: Layer,
    analysis_config: dict[str, Any],
    max_text_bytes: int,
) -> tuple[dict[str, Any], bool]:
    algo = analysis_version(analysis_config)
    identity = [None if base is None else base.rev_id, head.rev_id, layer.value, algo]
    digest = sha256(canonical_json(identity)).hexdigest()
    report_id = f"RPT-{digest}"
    cached = conn.execute(
        "SELECT payload_json FROM report WHERE report_id = ?", (report_id,)
    ).fetchone()
    if cached is not None:
        return json.loads(cached["payload_json"]), False

    result = DiffEngine(object_store, max_text_bytes=max_text_bytes).compare(
        base_files, head_files, layer=layer
    )
    units = [item.model_dump(mode="json") for item in result.semantic_units]
    clusters = cluster_changes(result.semantic_units)
    risk = _risk(
        units,
        result.degraded,
        result.needs_review,
        semantic_requested=layer is Layer.L3,
    )
    payload = {
        "schema_version": "1",
        "report_id": report_id,
        "algo_version": algo,
        "layer": layer.value,
        "base": {"rev": None if base is None else base.rev_id},
        "head": {"rev": head.rev_id, "change_id": head.change_id},
        "overview": {
            "files": len(result.metadata_files),
            "changes": len(units) if layer is Layer.L3 else None,
            "clusters": len(clusters),
            "risk": risk["level"],
            "risk_counts": risk["counts"],
            "needs_review": len(result.needs_review),
        },
        "summary": _summary(
            len(result.metadata_files),
            len(units) if layer is Layer.L3 else None,
            len(clusters),
            risk["level"],
            len(result.needs_review),
        ),
        "clusters": clusters,
        "risk": risk,
        "layers": {
            "metadata": {"status": "computed", "files": result.metadata_files},
            "text": {
                "status": _layer_status(layer, 1, result.degraded),
                "hunks": result.text_hunks,
            },
            "structure": {
                "status": _layer_status(layer, 2, result.degraded),
                "nodes": result.structure_nodes,
            },
            "semantic": {
                "status": _layer_status(layer, 3, result.degraded),
                "units": units,
            },
        },
        "needs_review": result.needs_review,
        "degraded": result.degraded,
        "behavior": None,
    }
    encoded = canonical_json(payload).decode("utf-8")
    with transaction(conn):
        conn.execute(
            """
            INSERT OR IGNORE INTO diff_cache
                (cache_key, layer, algo_version, result_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (digest, layer.value, algo, encoded, _now_iso()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO report
                (report_id, ws_id, base_rev, head_rev, algo_version, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                ws_id,
                None if base is None else base.rev_id,
                head.rev_id,
                algo,
                encoded,
                _now_iso(),
            ),
        )
    return json.loads(encoded), True
