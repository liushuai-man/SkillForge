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