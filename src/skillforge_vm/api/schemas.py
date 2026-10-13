"""M-10 路由请求模型。响应统一走 envelope，不单独定义响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, StrictBool


class InitRequest(BaseModel):
    path: str
    name: str | None = None


class SnapshotRequest(BaseModel):
    message: str | None = None


class RefRequest(BaseModel):
    name: str
    rev: str | None = None


class RestorePreviewRequest(BaseModel):
    rev: str


class RestoreApplyRequest(BaseModel):
    confirm: StrictBool
