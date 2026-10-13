"""M-12 命令行客户端：只调用本地服务，绝不直连数据库（设计 §4.6）。

业务命令与服务完全等价；服务未启动时给出明确的启动提示。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..core.config import Settings

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8756
RUNTIME_FILENAME = "runtime.json"


class CliError(Exception):
    """命令行可读的失败：服务不可达或服务返回业务错误。"""


def default_base_url() -> str:
    return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"


def runtime_file(data_root: Path | None = None) -> Path:
    root = data_root if data_root is not None else Settings().data_root
    return Path(root) / RUNTIME_FILENAME


def write_runtime(base_url: str, *, data_root: Path | None = None) -> Path:
    """记录本次 `start` 实际选择的端口，供后续 CLI 复用同一服务。"""
    path = runtime_file(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"base_url": base_url, "pid": os.getpid()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def read_runtime_base_url(*, data_root: Path | None = None) -> str | None:
    path = runtime_file(data_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    base_url = payload.get("base_url")
    return base_url if isinstance(base_url, str) and base_url else None


def resolve_base_url(explicit: str | None, *, data_root: Path | None = None) -> str:
    """优先级：显式参数 > 环境变量 > 运行时文件 > 默认端口。"""
    if explicit:
        return explicit.rstrip("/")
    env = os.environ.get("SKILLFORGE_VM_URL")
    if env:
        return env.rstrip("/")
    recorded = read_runtime_base_url(data_root=data_root)
    if recorded:
        return recorded.rstrip("/")
    return default_base_url()


def host_port_of(base_url: str) -> tuple[str, int]:
    parsed = urlparse(base_url)
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    return host, port


class VmClient:
    """一个极薄的 HTTP 客户端，负责外壳校验与错误转译。"""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # 只访问本机服务：不读取代理/环境配置，避免被本机代理劫持成不可解析响应。
        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout, trust_env=False
            ) as client:
                response = client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CliError(
                f"无法连接服务 {self._base_url}（先运行 `skillforge-vm start`）：{exc}"
            ) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise CliError(f"服务返回了无法解析的响应（HTTP {response.status_code}）") from exc
        if not isinstance(body, dict) or "ok" not in body:
            raise CliError(f"服务返回了非统一外壳的响应（HTTP {response.status_code}）")
        if not body["ok"]:
            error = body.get("error") or {}
            detail = error.get("detail")
            suffix = f"（{detail}）" if detail else ""
            raise CliError(f"[{error.get('code')}] {error.get('message')}{suffix}")
        return body.get("data")

    def get(self, path: str, **params: Any) -> Any:
        cleaned = {key: value for key, value in params.items() if value is not None}
        return self._request("GET", path, params=cleaned or None)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, json=payload or {})