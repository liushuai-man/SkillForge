"""全局配置。

数据根目录默认落在用户级独立目录（FR-01.3：不入侵用户仓库）。
可用环境变量 SKILLFORGE_VM_DATA_ROOT 覆盖。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_root() -> Path:
    """各平台的默认数据根目录。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return root / "skillforge-vm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SKILLFORGE_VM_",
        env_file=".env",
        extra="ignore",
    )

    data_root: Path = Field(default_factory=default_data_root)