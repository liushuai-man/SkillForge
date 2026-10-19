"""Shared location for generated development and acceptance Skills."""

from __future__ import annotations

import os
from pathlib import Path


def test_root() -> Path:
    default = Path(__file__).resolve().parents[2] / "Mytest" / "skillForge-testskills"
    root = Path(os.environ.get("SKILLFORGE_TEST_ROOT", default)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root
