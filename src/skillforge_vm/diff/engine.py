"""确定性的 L0～L3 对比，不读取数据库、不访问工作区磁盘。"""

from __future__ import annotations

import difflib
import json
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

import yaml

from ..core.types import ObjectType
from ..objectstore.objects import canonical_json
from ..objectstore.store import ObjectStore
from ..semantics import ChangeOp, SemanticChange, SemanticElement, SourceSpan
from ..semantics.extractor import extract_semantic_elements
from .models import DiffResult, Layer

ALGORITHM_REVISION = "diff-rules-4"
REPORT_SCHEMA_VERSION = "1"


def analysis_version(config: dict[str, Any]) -> str:
    fingerprint = sha256(canonical_json(config)).hexdigest()[:16]
    return f"{ALGORITHM_REVISION}+schema-{REPORT_SCHEMA_VERSION}+{fingerprint}"


def _span_key(span: SourceSpan | None) -> tuple[Any, ...]:
    if span is None:
        return ("", -1, -1, "")
    return (span.path, span.start_byte, span.end_byte, span.text)


def _change_id(
    path: str,
    kind: str,
    op: ChangeOp,
    before: SourceSpan | None,
    after: SourceSpan | None,
) -> str:
    payload = [path, kind, op.value, _span_key(before), _span_key(after)]
    return "u-" + sha256(canonical_json(payload)).hexdigest()[:20]


def _change(
    op: ChangeOp, before: SemanticElement | None, after: SemanticElement | None
) -> SemanticChange:
    exemplar = after or before
    assert exemplar is not None
    path = after.span.path if after is not None else before.span.path  # type: ignore[union-attr]
    return SemanticChange(
        id=_change_id(
            path,
            exemplar.kind.value,
            op,
            None if before is None else before.span,
            None if after is None else after.span,
        ),
        path=path,
        kind=exemplar.kind,
        op=op,
        before=None if before is None else before.span,
        after=None if after is None else after.span,
        rule_id=f"semantic.diff.{op.value}.v1",
    )


def _line_spans(path: str, data: bytes) -> list[SourceSpan]:
    spans = []
    offset = 0
    for raw_with_end in data.splitlines(keepends=True):
        raw = raw_with_end.rstrip(b"\r\n")
        end = offset + len(raw)
        spans.append(
            SourceSpan(
                path=path,
                start_byte=offset,
                end_byte=end,
                text=data[offset:end].decode("utf-8"),
            )
        )
        offset += len(raw_with_end)
    return spans


def _combined_span(path: str, spans: list[SourceSpan]) -> SourceSpan | None:
    if not spans:
        return None
    return SourceSpan(
        path=path,
        start_byte=spans[0].start_byte,
        end_byte=spans[-1].end_byte,
        text="\n".join(item.text for item in spans),
    )


def _text_hunks(
    before_path: str,
    before: bytes,
    after_path: str,
    after: bytes,
) -> list[dict[str, Any]]:
    left, right = _line_spans(before_path, before), _line_spans(after_path, after)
    matcher = difflib.SequenceMatcher(
        a=[item.text for item in left], b=[item.text for item in right], autojunk=False
    )
    hunks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(
            {
                "path": after_path if tag != "delete" else before_path,
                "op": {"insert": "add", "delete": "delete", "replace": "modify"}[tag],
                "before": (
                    None
                    if tag == "insert"
                    else _combined_span(before_path, left[i1:i2]).model_dump()
                ),
                "after": (
                    None
                    if tag == "delete"
                    else _combined_span(after_path, right[j1:j2]).model_dump()
                ),
            }
        )
    return hunks


def _validate_structure(path: str, data: bytes) -> str | None:
    suffix = PurePosixPath(path).suffix.casefold()
    try:
        if suffix == ".json":
            json.loads(data.decode("utf-8-sig"))
        elif suffix in {".yaml", ".yml"}:
            yaml.safe_load(data.decode("utf-8-sig"))
        elif suffix not in {".md", ".markdown"}:
            return "unsupported_file_type"
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
        return "parse_failed"
    return None


def _structure(path: str, data: bytes) -> list[dict[str, Any]]:
    nodes = []
    for span in _line_spans(path, data):
        stripped = span.text.lstrip("\ufeff ")
        if not stripped or stripped.startswith("<!--"):
            continue
        if stripped.startswith("#"):
            node_type = "heading"
        elif stripped.startswith(("- ", "* ", "+ ")) or stripped[:2].rstrip(".").isdigit():
            node_type = "list_item"
        elif ":" in stripped:
            node_type = "mapping_entry"
        elif stripped.startswith(("```", "~~~")):
            node_type = "code_fence"
        else:
            node_type = "paragraph"
        nodes.append({"node_type": node_type, "span": span.model_dump()})
    return nodes


def _semantic_diff(
    before: list[SemanticElement], after: list[SemanticElement]
) -> tuple[list[SemanticChange], list[dict[str, Any]]]:
    unmatched_before = set(range(len(before)))
    unmatched_after = set(range(len(after)))
    changes: list[SemanticChange] = []
    reviews: list[dict[str, Any]] = []

    # Match unchanged occurrences before fuzzy pairing, including repeated rules.
    exact: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, item in enumerate(after):
        exact[(item.kind, _span_key(item.span))].append(index)
    for index, item in enumerate(before):
        matches = exact.get((item.kind, _span_key(item.span)), [])
        if matches:
            unmatched_before.remove(index)
            unmatched_after.remove(matches.pop(0))

    left_keys = Counter((item.kind, item.normalized) for item in before)
    right_keys = Counter((item.kind, item.normalized) for item in after)
    right_lookup: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    for index, item in enumerate(after):
        right_lookup[(item.kind, item.normalized)].append(index)
    for left_index, item in enumerate(before):
        if left_index not in unmatched_before:
            continue
        key = (item.kind, item.normalized)
        if left_keys[key] != 1 or right_keys[key] != 1:
            continue
        right_index = right_lookup[key][0]
        unmatched_before.discard(left_index)
        unmatched_after.discard(right_index)
        target = after[right_index]
        if item.span.path != target.span.path or item.span.start_byte != target.span.start_byte:
            changes.append(_change(ChangeOp.MOVE, item, target))

    candidates = []
    for left_index in unmatched_before:
        for right_index in unmatched_after:
            left, right = before[left_index], after[right_index]
            if left.kind != right.kind:
                continue
            ratio = difflib.SequenceMatcher(
                a=left.normalized, b=right.normalized, autojunk=False
            ).ratio()
            candidates.append((ratio, left_index, right_index))
    for ratio, left_index, right_index in sorted(candidates, reverse=True):
        if left_index not in unmatched_before or right_index not in unmatched_after:
            continue
        left, right = before[left_index], after[right_index]
        if left.normalized == right.normalized:
            changes.append(_change(ChangeOp.MOVE, left, right))
            unmatched_before.remove(left_index)
            unmatched_after.remove(right_index)
        elif left.span.path == right.span.path and ratio >= 0.3:
            changes.append(_change(ChangeOp.MODIFY, left, right))
            unmatched_before.remove(left_index)
            unmatched_after.remove(right_index)
        elif left.span.path != right.span.path and ratio >= 0.75:
            reviews.append(
                {
                    "unit": None,
                    "path": right.span.path,
                    "reason_code": "ambiguous_move",
                    "before": left.span.model_dump(),
                    "after": right.span.model_dump(),
                }
            )

    changes.extend(_change(ChangeOp.DELETE, before[index], None) for index in unmatched_before)
    changes.extend(_change(ChangeOp.ADD, None, after[index]) for index in unmatched_after)
    changes.sort(key=lambda item: (item.path, item.kind.value, _span_key(item.after), item.id))
    reviews.sort(key=lambda item: (item["path"], item["reason_code"]))
    return changes, reviews


class DiffEngine:
    def __init__(self, store: ObjectStore, *, max_text_bytes: int) -> None:
        self._store = store
        self._max_text_bytes = max_text_bytes

    def _blob(self, oid: str) -> bytes:
        kind, body = self._store.read(oid)
        if kind is not ObjectType.BLOB:
            raise ValueError(f"路径索引指向非 blob 对象：{oid}")
        return body

    def compare(
        self,
        base_files: dict[str, tuple[str, str]],
        head_files: dict[str, tuple[str, str]],
        *,
        layer: Layer = Layer.L3,
    ) -> DiffResult:
        left_only = set(base_files) - set(head_files)
        right_only = set(head_files) - set(base_files)
        changed = {
            path
            for path in set(base_files) & set(head_files)
            if base_files[path] != head_files[path]
        }
        moves: list[tuple[str, str]] = []
        left_by_oid: dict[str, list[str]] = defaultdict(list)
        right_by_oid: dict[str, list[str]] = defaultdict(list)
        for path in left_only:
            left_by_oid[base_files[path][0]].append(path)
        for path in right_only:
            right_by_oid[head_files[path][0]].append(path)
        for oid in sorted(set(left_by_oid) & set(right_by_oid)):
            if len(left_by_oid[oid]) == len(right_by_oid[oid]) == 1:
                old, new = left_by_oid[oid][0], right_by_oid[oid][0]
                moves.append((old, new))
                left_only.remove(old)
                right_only.remove(new)

        metadata = []
        for old, new in moves:
            metadata.append({"path": new, "op": "move", "before_path": old})
        metadata.extend({"path": path, "op": "delete"} for path in left_only)
        metadata.extend({"path": path, "op": "add"} for path in right_only)
        metadata.extend({"path": path, "op": "modify"} for path in changed)
        metadata.sort(key=lambda item: (item["path"], item["op"]))

        text_hunks: list[dict[str, Any]] = []
        structure_nodes: list[dict[str, Any]] = []
        before_elements: list[SemanticElement] = []
        after_elements: list[SemanticElement] = []
        degraded: list[dict[str, str]] = []
        pairs = [(path, path) for path in sorted(changed)] + sorted(moves)
        pairs += [(path, None) for path in sorted(left_only)]
        pairs += [(None, path) for path in sorted(right_only)]
        for before_path, after_path in pairs:
            before_data = b"" if before_path is None else self._blob(base_files[before_path][0])
            after_data = b"" if after_path is None else self._blob(head_files[after_path][0])
            display_path = after_path or before_path
            assert display_path is not None
            if layer.depth == 0:
                continue
            bodies = [body for body in (before_data, after_data) if body]
            if any(len(body) > self._max_text_bytes for body in bodies):
                degraded.append(
                    {
                        "path": display_path,
                        "requested_layer": layer.value,
                        "available_layer": "L0",
                        "reason_code": "text_limit_exceeded",
                    }
                )
                continue
            try:
                for body in bodies:
                    body.decode("utf-8")
                    if b"\x00" in body:
                        raise UnicodeDecodeError("utf-8", body, 0, 1, "binary NUL")
            except UnicodeDecodeError:
                degraded.append(
                    {
                        "path": display_path,
                        "requested_layer": layer.value,
                        "available_layer": "L0",
                        "reason_code": "unsupported_encoding",
                    }
                )
                continue
            text_hunks.extend(
                _text_hunks(
                    before_path or display_path,
                    before_data,
                    after_path or display_path,
                    after_data,
                )
            )
            if layer.depth < 2:
                continue
            reason = (
                _validate_structure(before_path, before_data) if before_path is not None else None
            ) or (_validate_structure(after_path, after_data) if after_path is not None else None)
            if reason:
                degraded.append(
                    {
                        "path": display_path,
                        "requested_layer": layer.value,
                        "available_layer": "L1",
                        "reason_code": reason,
                    }
                )
                continue
            before_nodes = [] if before_path is None else _structure(before_path, before_data)
            after_nodes = [] if after_path is None else _structure(after_path, after_data)
            if before_nodes != after_nodes:
                structure_nodes.append(
                    {
                        "path": display_path,
                        "op": (
                            "add"
                            if before_path is None
                            else "delete"
                            if after_path is None
                            else "modify"
                        ),
                        "before": before_nodes,
                        "after": after_nodes,
                    }
                )
            if layer.depth < 3:
                continue
            if before_path is not None:
                before_elements.extend(extract_semantic_elements(before_path, before_data))
            if after_path is not None:
                after_elements.extend(extract_semantic_elements(after_path, after_data))

        semantic, needs_review = (
            _semantic_diff(before_elements, after_elements) if layer.depth >= 3 else ([], [])
        )
        return DiffResult(
            layer=layer,
            metadata_files=metadata,
            text_hunks=text_hunks,
            structure_nodes=structure_nodes,
            semantic_units=semantic,
            needs_review=needs_review,
            degraded=sorted(degraded, key=lambda item: (item["path"], item["reason_code"])),
        )
