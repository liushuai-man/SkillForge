"""SHA-256 工具（M-03 内容寻址）。

选型：抗碰撞、长度可控，不用 MD5 / SHA-1。
"""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes) -> str:
    """返回内容的 SHA-256 十六进制摘要，用作对象 ID。"""
    return hashlib.sha256(data).hexdigest()