"""本机 Windows 目录选择；不遍历或改写所选目录。"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Request

from ..core.errors import InvalidRequestError, OperationFailedError, WorkspaceBusyError

_picker_lock = threading.Lock()
_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'SkillForge - Select Skill folder'
$dialog.ShowNewFolderButton = $false
try {
    $path = $null
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        $path = $dialog.SelectedPath
    }
    @{path=$path} | ConvertTo-Json -Compress
} finally {
    $dialog.Dispose()
    $owner.Dispose()
}
"""


def require_local_request(request: Request) -> None:
    """防止远端请求、跨站表单及 DNS rebinding 唤起本机窗口。"""

    def loopback(host: str | None) -> bool:
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host or "").is_loopback
        except ValueError:
            return False

    origin = request.headers.get("origin")
    try:
        origin_host = urlsplit(origin).hostname if origin else None
    except ValueError as exc:
        raise InvalidRequestError("目录选择请求的来源无效") from exc
    if (
        not request.client
        or not loopback(request.client.host)
        or not loopback(request.url.hostname)
        or request.headers.get("sec-fetch-site") == "cross-site"
        or (origin and not loopback(origin_host))
        or request.headers.get("content-type", "").split(";")[0].strip() != "application/json"
    ):
        raise InvalidRequestError("目录选择仅允许本机页面以 JSON 请求调用")


def select_directory() -> str | None:
    if os.name != "nt":
        raise OperationFailedError("当前目录选择窗口仅支持 Windows，请手动输入目录路径")
    if not _picker_lock.acquire(blocking=False):
        raise WorkspaceBusyError("已有目录选择窗口，请先完成或取消")
    try:
        powershell = (
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-STA",
                "-EncodedCommand",
                base64.b64encode(_SCRIPT.encode("utf-16-le")).decode("ascii"),
            ],
            capture_output=True,
            encoding="utf-8-sig",
            timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise OperationFailedError("无法打开系统目录选择窗口，请手动输入路径")
        path = json.loads(result.stdout)["path"]
        if path is not None and (
            not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_dir()
        ):
            raise OperationFailedError("目录选择结果不是有效的本机目录，请重试")
        return path
    except subprocess.TimeoutExpired as exc:
        raise OperationFailedError("目录选择等待超时，请重新打开或手动输入路径") from exc
    except (OSError, ValueError, KeyError) as exc:
        raise OperationFailedError("系统目录选择失败，请重试或手动输入路径") from exc
    finally:
        _picker_lock.release()
