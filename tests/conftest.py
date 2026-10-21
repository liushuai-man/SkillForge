"""共享测试夹具：构造一个已纳管的临时 Skill 工作区。

只用测试专用临时目录与独立数据根，绝不在真实用户 Skill 上操作。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillforge_vm.workspace.manager import WorkspaceHandle, WorkspaceManager


@pytest.fixture()
def skill_dir(tmp_path: Path) -> Path:
    skill = tmp_path / "demo-skill"
    (skill / "sub").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (skill / "sub" / "config.yaml").write_text("a: 1\n", encoding="utf-8")
    return skill


@pytest.fixture()
def workspace(tmp_path: Path, skill_dir: Path) -> WorkspaceHandle:
    manager = WorkspaceManager(data_root=tmp_path / "data")
    return manager.init(skill_dir).workspace
