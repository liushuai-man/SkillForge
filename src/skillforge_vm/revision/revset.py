"""M-04 最小 revset 解析器（§7.4）。

MVP 只接受：`@`、`last`、完整 Revision ID、`<ref>`、`<rev-or-ref>~N`。
`A..B` 区间表达式为后续项，**不**在 MVP 里伪装成两端 diff。
每个表达式都解析为固定的已提交 Revision ID；HTTP 与 CLI 使用同一个入口。
"""

from __future__ import annotations

from ..core.errors import InvalidRequestError, RevisionNotFoundError
from .identity import is_revision_id
from .store import RevisionStore


def resolve_revset(
    spec: str,
    *,
    store: RevisionStore,
    ws_id: str,
    current: str | None = None,
) -> str:
    """把 revset 表达式解析为已提交的 ``rev_id``。

    ``current`` 是本次写队列入口稳定扫描后捕获到的已提交修订，用于解析 `@`。
    显式空串、未知引用、越界、区间表达式都明确报错，绝不回退成零基线。
    """
    text = spec.strip()
    if not text:
        raise InvalidRequestError("引用表达式为空", detail=spec)
    if ".." in text:
        raise InvalidRequestError("区间表达式 A..B 尚未支持", detail=spec)

    base_text, sep, count_text = text.partition("~")
    if sep:
        if "~" in count_text or not count_text.isdigit():
            raise InvalidRequestError(f"非法的 ~N 表达式：{spec}", detail=spec)
        steps = int(count_text)
    else:
        steps = 0

    rev_id = _resolve_base(base_text, store=store, ws_id=ws_id, current=current)
    for _ in range(steps):
        revision = store.get(ws_id, rev_id)
        if revision.parent_rev_id is None:
            raise RevisionNotFoundError(f"~{steps} 越界：{rev_id} 没有更早的父修订", detail=spec)
        rev_id = revision.parent_rev_id
    return rev_id


def _resolve_base(
    text: str,
    *,
    store: RevisionStore,
    ws_id: str,
    current: str | None,
) -> str:
    if text == "@":
        if current is None:
            raise InvalidRequestError("当前没有已捕获的修订可用于 @", detail=text)
        return current
    if text == "last":
        head = store.head(ws_id)
        if head is None:
            raise RevisionNotFoundError("工作区还没有任何修订", detail=text)
        return head.rev_id
    if is_revision_id(text):
        return store.get(ws_id, text).rev_id
    return store.get_ref(ws_id, text).rev_id
