"""M-04 修订与引用：公共接口。

对外只暴露这里导出的模型与入口；其他模块不直查 ``revision`` / ``change`` / ``ref`` 表。
"""

from __future__ import annotations

from .identity import is_revision_id, new_change_id, revision_meta_payload
from .models import Change, Ref, Revision
from .revset import resolve_revset
from .store import RevisionStore

__all__ = [
    "Change",
    "Ref",
    "Revision",
    "RevisionStore",
    "is_revision_id",
    "new_change_id",
    "resolve_revset",
    "revision_meta_payload",
]
