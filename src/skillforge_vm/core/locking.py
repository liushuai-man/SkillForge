"""数据根生命周期独占锁；进程退出由操作系统释放，不删除锁文件。"""

from __future__ import annotations

import errno
import os
import threading
from collections import deque
from pathlib import Path
from typing import BinaryIO

from .errors import WorkspaceBusyError


class SerialGate:
    """按排队次序进入写通道；同一线程可重入（tag 内捕获快照）。"""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._waiters: deque[object] = deque()
        self._owner: int | None = None
        self._depth = 0

    def __enter__(self):
        owner = threading.get_ident()
        with self._condition:
            if self._owner == owner:
                self._depth += 1
                return self
            ticket = object()
            self._waiters.append(ticket)
            try:
                while self._owner is not None or self._waiters[0] is not ticket:
                    self._condition.wait()
            except BaseException:
                self._waiters.remove(ticket)
                self._condition.notify_all()
                raise
            self._waiters.popleft()
            self._owner = owner
            self._depth = 1
            return self

    def __exit__(self, *exc):
        with self._condition:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._condition.notify_all()


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
