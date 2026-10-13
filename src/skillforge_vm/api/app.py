"""M-10 接口层：FastAPI 应用工厂与路由表（设计 §4.6 / 契约 §4）。

只注册**已有真实实现**的路由。diff / range-diff / reports / behavior-diff 依赖 M-05/M-08（B 线）
或预留契约，尚未实现，故不注册，避免出现「占位成功响应」。undo / restore 受 TBD-08/TBD-09
阻塞（见契约 §2.3），同样不注册。
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from sse_starlette.sse import EventSourceResponse

from ..workspace.manager import WorkspaceManager
from .envelope import RequestIdMiddleware, envelope_ok, register_error_handlers
from .schemas import InitRequest, RefRequest, SnapshotRequest
from .service import WorkspaceService


def _default_version() -> str:
    return os.environ.get("SKILLFORGE_VM_TOOL_VERSION", "0.1.0")


def create_app(
    manager: WorkspaceManager | None = None,
    *,
    service: WorkspaceService | None = None,
) -> FastAPI:
    """构造接口层应用；可注入自建 manager / service 以便测试与嵌入。"""
    service = service or WorkspaceService(manager)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await asyncio.to_thread(service.start)
            yield
        finally:
            await asyncio.to_thread(service.stop)

    app = FastAPI(
        title="SkillForge VM",
        version=_default_version(),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, Any]:
        return envelope_ok({"status": "ok"})

    # ---- 工作区 ----

    @router.post("/workspaces")
    def create_workspace(payload: InitRequest) -> dict[str, Any]:
        return envelope_ok(service.init(payload.path, payload.name))

    @router.get("/workspaces")
    def list_workspaces() -> dict[str, Any]:
        return envelope_ok(service.list_workspaces())

    @router.get("/workspaces/{ws_id}")
    def get_workspace(ws_id: str) -> dict[str, Any]:
        return envelope_ok(service.get_workspace(ws_id))

    @router.get("/workspaces/{ws_id}/status")
    def workspace_status(ws_id: str) -> dict[str, Any]:
        return envelope_ok(service.status(ws_id))

    # ---- 快照 ----

    @router.post("/workspaces/{ws_id}/snapshots")
    def create_snapshot(ws_id: str, payload: SnapshotRequest) -> dict[str, Any]:
        return envelope_ok(service.snapshot(ws_id, payload.message))

    # ---- 修订 / 变更 ----

    @router.get("/workspaces/{ws_id}/revisions")
    def list_revisions(
        ws_id: str,
        limit: int | None = Query(default=None, ge=1, le=1000),
        max_seq: int | None = Query(default=None, ge=1),
    ) -> dict[str, Any]:
        return envelope_ok(service.list_revisions(ws_id, limit=limit, max_seq=max_seq))

    @router.get("/workspaces/{ws_id}/revisions/{rev}")
    def get_revision(ws_id: str, rev: str) -> dict[str, Any]:
        return envelope_ok(service.get_revision(ws_id, rev))

    @router.get("/workspaces/{ws_id}/changes")
    def list_changes(ws_id: str) -> dict[str, Any]:
        return envelope_ok(service.list_changes(ws_id))

    # ---- 引用 / 锚点 ----

    @router.post("/workspaces/{ws_id}/refs")
    def set_ref(ws_id: str, payload: RefRequest) -> dict[str, Any]:
        return envelope_ok(service.set_ref(ws_id, payload.name, payload.rev))

    @router.get("/workspaces/{ws_id}/refs")
    def list_refs(ws_id: str) -> dict[str, Any]:
        return envelope_ok(service.list_refs(ws_id))

    # ---- 操作日志 ----

    @router.get("/workspaces/{ws_id}/ops")
    def list_ops(
        ws_id: str, limit: int | None = Query(default=None, ge=1, le=1000)
    ) -> dict[str, Any]:
        return envelope_ok(service.list_ops(ws_id, limit=limit))

    # ---- 事件流（SSE） ----

    @router.get("/workspaces/{ws_id}/events")
    async def events(ws_id: str, request: Request) -> EventSourceResponse:
        service.get_workspace(ws_id)  # 未知工作区尽早失败
        queue = service.bus.subscribe()

        async def _generate() -> Any:
            try:
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "stream/ready", "workspace_id": ws_id}, ensure_ascii=False
                    ),
                }
                while True:
                    event = await queue.get()
                    if event.get("workspace_id") != ws_id:
                        continue
                    yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}
            finally:
                service.bus.unsubscribe(queue)

        return EventSourceResponse(_generate())

    app.include_router(router)
    return app
