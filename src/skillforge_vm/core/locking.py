"""数据根生命周期独占锁；进程退出由操作系统释放，不删除锁文件。"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO

from .errors import WorkspaceBusyError


class DataRootLock:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root.resolve() / ".writer.lock"
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise WorkspaceBusyError(
                    "数据根已被其他服务占用", detail=str(self.path.parent)
                ) from exc
            raise
        self._file = stream

    def release(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
