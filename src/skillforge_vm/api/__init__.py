"""M-10 接口层。"""

from __future__ import annotations

from .app import create_app
from .events import EVENT_SNAPSHOT_CREATED, EventBus
from .service import WorkspaceService

__all__ = ["EVENT_SNAPSHOT_CREATED", "EventBus", "WorkspaceService", "create_app"]