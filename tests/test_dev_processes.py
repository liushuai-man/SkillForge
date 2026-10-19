"""Regression for losing a development console while its backend owns the data lock."""

from __future__ import annotations

import ctypes
import json
import os
import site
import subprocess
import sys
from pathlib import Path

import pytest

from skillforge_vm.core.locking import DataRootLock


def test_signal_failure_still_terminates_owned_child(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from dev import stop

    class DetachedChild:
        pid = 123
        terminated = False

        def poll(self):
            return None

        def send_signal(self, _signal):
            raise OSError("console already closed")

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert self.terminated
            return 0

    child = DetachedChild()
    if os.name != "nt":
        monkeypatch.setattr(os, "killpg", lambda *_: (_ for _ in ()).throw(OSError()))
    stop(child)
    assert child.terminated


@pytest.mark.skipif(os.name != "nt", reason="Windows console/job lifecycle")
def test_losing_launcher_kills_children_and_releases_data_lock(tmp_path):
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project / "scripts"), str(project / "src"), *site.getsitepackages()]
    )
    locker = """
import json, subprocess, sys, time
from pathlib import Path
from skillforge_vm.core.locking import DataRootLock
lock = DataRootLock(Path(sys.argv[1]))
lock.acquire()
grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
print(json.dumps([__import__('os').getpid(), grandchild.pid]), flush=True)
time.sleep(60)
"""
    manager = tmp_path / "manager.py"
    manager.write_text(
        "import subprocess, sys, time\nfrom process_job import ProcessJob\n"
        "job = ProcessJob()\n"
        f"child = subprocess.Popen([sys.executable, '-u', '-c', {locker!r}, {str(tmp_path)!r}], "
        "stdout=subprocess.PIPE, text=True)\n"
        "job.add(child.pid)\nprint(child.stdout.readline(), flush=True)\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [getattr(sys, "_base_executable", sys.executable), "-u", str(manager)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handles = []
    try:
        line = process.stdout.readline()
        assert line.strip(), process.stderr.read()
        for pid in json.loads(line):
            handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            assert handle, ctypes.get_last_error()
            handles.append(handle)
        # No Python finally/atexit can run: only the OS closes the job handle.
        process.kill()
        process.wait(timeout=5)
        for handle in handles:
            assert kernel.WaitForSingleObject(handle, 5000) == 0
        lock = DataRootLock(tmp_path)
        lock.acquire()
        lock.release()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for handle in handles:
            kernel.CloseHandle(handle)
