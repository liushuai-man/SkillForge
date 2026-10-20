"""M-10 统一返回外壳、request_id 与错误映射（设计 §4.6 / 契约 §4.1、§4.2）。

成功：``{ok:true, data:..., error:null, request_id:"..."}``
失败：``{ok:false, data:null, error:{code,message,detail}, request_id:"..."}``
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.errors import OperationFailedError, SkillForgeVMError

logger = logging.getLogger(__name__)

_request_id: ContextVar[str] = ContextVar("skillforge_request_id", default="-")

# 错误码 → HTTP 状态（契约 §4.2）。未登记的已知错误按 500 处理。
ERROR_STATUS: dict[str, int] = {
    "invalid_skill_root": 400,
    "workspace_already_initialized": 409,
    "workspace_not_found": 404,
    "workspace_data_missing": 409,
    "object_store_not_writable": 507,
    "object_not_found": 409,
    "object_corrupted": 409,
    "invalid_request": 422,
    "ref_not_found": 404,
    "revision_not_found": 404,
    "snapshot_unstable": 409,
    "workspace_busy": 409,
    "operation_failed": 500,
}


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: str | None = None


def current_request_id() -> str:
    return _request_id.get()


def envelope_ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "request_id": current_request_id()}


def envelope_error(code: str, message: str, detail: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "detail": detail},
        "request_id": current_request_id(),
    }


def _status_for(code: str) -> int:
    return ERROR_STATUS.get(code, 500)


def register_error_handlers(app: FastAPI) -> None:
    """把业务错误与框架校验错误都收敛到统一外壳，避免泄漏两套 JSON。"""

    @app.exception_handler(SkillForgeVMError)
    async def _known(_request: Request, exc: SkillForgeVMError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc.code),
            content=envelope_error(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=envelope_error(
                "invalid_request", "请求参数校验失败", detail=str(exc.errors())
            ),
        )

    @app.exception_handler(Exception)
    async def _unknown(_request: Request, exc: Exception) -> JSONResponse:
        fallback = OperationFailedError("请求处理失败")
        rid = current_request_id()
        logger.exception("请求处理失败 request_id=%s", rid)
        return JSONResponse(
            status_code=500,
            content=envelope_error(fallback.code, fallback.message, detail=str(exc)),
        )


class RequestIdMiddleware:
    """为每个请求分配 request_id，并回写 ``X-Request-Id`` 响应头。"""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        rid = uuid.uuid4().hex
        token = _request_id.set(rid)

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            _request_id.reset(token)