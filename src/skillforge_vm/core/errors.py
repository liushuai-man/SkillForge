"""具体错误类型。

FR-08.4：错误必须是具体原因（如「工作区未初始化」「对象库不可写」），
而不是笼统的「内部错误」。
"""

from __future__ import annotations


class SkillForgeVMError(Exception):
    """所有版本管理器错误的基类，携带稳定的错误码。"""

    code = "error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class InvalidSkillRootError(SkillForgeVMError):
    code = "invalid_skill_root"


class WorkspaceAlreadyInitializedError(SkillForgeVMError):
    code = "workspace_already_initialized"


class WorkspaceNotFoundError(SkillForgeVMError):
    code = "workspace_not_found"


class WorkspaceDataMissingError(SkillForgeVMError):
    code = "workspace_data_missing"


class ObjectStoreNotWritableError(SkillForgeVMError):
    code = "object_store_not_writable"


class ObjectNotFoundError(SkillForgeVMError):
    code = "object_not_found"


class ObjectCorruptedError(SkillForgeVMError):
    code = "object_corrupted"


class SnapshotUnstableError(SkillForgeVMError):
    """工作区持续变化，本次无法捕获稳定内容；可重试（409）。"""

    code = "snapshot_unstable"


class InvalidRequestError(SkillForgeVMError):
    """参数类型、枚举、OID 语法或引用表达式无效（422）。"""

    code = "invalid_request"


class RefNotFoundError(SkillForgeVMError):
    """显式请求的命名引用不存在；不得回退成零基线（404）。"""

    code = "ref_not_found"


class RevisionNotFoundError(SkillForgeVMError):
    """显式请求的修订不存在（404）。"""

    code = "revision_not_found"
