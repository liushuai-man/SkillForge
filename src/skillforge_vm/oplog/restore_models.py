"""受控恢复 v1 的公开计划与提交上下文（契约 §2.4）。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FileState(BaseModel):
    model_config = ConfigDict(frozen=True)
    oid: str
    mode: str


class RestorePlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    plan_id: str
    before_rev: str
    target_rev: str
    action: Literal["restore", "undo_restore"]
    config_hash: str
    root_identity: tuple[int, int]
    before: dict[str, FileState]
    after: dict[str, FileState]
    before_dirs: list[str]
    after_dirs: list[str]

    def changes(self) -> list[dict[str, str]]:
        result = []
        for path in sorted(self.before.keys() | self.after.keys()):
            if self.before.get(path) == self.after.get(path):
                continue
            action = (
                "add"
                if path not in self.before
                else "delete"
                if path not in self.after
                else "modify"
            )
            result.append({"path": path, "action": action})
        for path in sorted(set(self.before_dirs) - set(self.after_dirs)):
            result.append({"path": path, "action": "rmdir"})
        for path in sorted(set(self.after_dirs) - set(self.before_dirs)):
            result.append({"path": path, "action": "mkdir"})
        return result


class RestoreCommit(BaseModel):
    plan_id: str
    before_rev: str
    target_rev: str
    target_tree: str
    action: Literal["restore", "undo_restore"]
