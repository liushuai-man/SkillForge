"""一键执行 A 线体验流程；使用独立测试目录、真实服务和 CLI，保留诊断记录。"""

from __future__ import annotations

import json
import os
import site
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from test_support import test_root


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class ExperienceCheck:
    def __init__(self) -> None:
        output = test_root() / "experience-check"
        output.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="run-", dir=output))
        self.skill = self.root / "skill"
        self.skill.mkdir()
        self.file = self.skill / "SKILL.md"
        self.data = self.root / "data"
        self.env = dict(os.environ)
        self.env.pop("SKILLFORGE_VM_URL", None)
        self.env["SKILLFORGE_VM_DATA_ROOT"] = str(self.data)
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.process: subprocess.Popen | None = None
        self.log = None
        self.starts = 0
        self.base_url = ""
        self.ws = ""
        self.steps: list[dict[str, str]] = []
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # uv 的 Windows venv python 可能是二级启动器；直接运行真实解释器，
        # 加载当前环境 site-packages，使 Popen PID 就是服务 PID且能可靠终止。
        bootstrap = (
            "import site, runpy; "
            f"[site.addsitedir(p) for p in {site.getsitepackages()!r}]; "
            "runpy.run_module('skillforge_vm.cli.main', run_name='__main__')"
        )
        self.python = [getattr(sys, "_base_executable", sys.executable), "-c", bootstrap]

    def cli(self, *args: str, input_text: str | None = None) -> str:
        command = [*self.python, *args]
        result = subprocess.run(
            command,
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            input=input_text,
        )
        with (self.root / "cli.log").open("a", encoding="utf-8") as log:
            log.write(f"$ {' '.join(args)}\n{result.stdout}{result.stderr}\n")
        require(result.returncode == 0, f"CLI {' '.join(args)} 失败：{result.stderr}")
        return result.stdout

    def get(self, path: str):
        with self.opener.open(self.base_url + "/api" + path, timeout=3) as response:
            body = json.load(response)
        require(body.get("ok") is True, f"接口失败：{body}")
        return body["data"]

    def start(self) -> None:
        self.starts += 1
        self.log = (self.root / f"service-{self.starts}.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [*self.python, "start", "--port", "0"],
            cwd=self.root,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "服务提前退出，请查看 service 日志")
            try:
                runtime = json.loads((self.data / "runtime.json").read_text(encoding="utf-8"))
                # 重启不能误用前一进程留下的地址。
                if runtime["pid"] == self.process.pid:
                    self.base_url = runtime["base_url"]
                    self.get("/health")
                    return
            except (OSError, ValueError, KeyError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        raise RuntimeError("服务 20 秒内未就绪")

    def stop(self) -> None:
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
            finally:
                self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def status(self):
        return self.get(f"/workspaces/{self.ws}/status")

    def revision(self, ref: str):
        return self.get(f"/workspaces/{self.ws}/revisions/{ref}")

    def wait_seq(self, expected: int) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = self.status()
            require(status["head_seq"] <= expected, f"出现额外修订：{status}")
            if status["head_seq"] == expected and not status["has_pending_changes"]:
                return
            time.sleep(0.1)
        raise RuntimeError(f"保存后未自动收敛到 seq={expected}，最后状态：{status}")

    def setup(self) -> None:
        self.file.write_bytes("# 演示 Skill\n用中文回答。\n".encode())
        self.start()
        self.cli("init", str(self.skill))
        rows = self.get("/workspaces")
        require(len(rows) == 1, "测试数据根应只有一个工作区")
        self.ws = rows[0]["workspace_id"]
        self.wait_seq(1)
        self.cli("status")
        self.cli("log")
        time.sleep(0.8)  # 让原生监听就绪，避免只验证启动扫描。

    def automatic_save(self) -> None:
        self.file.write_bytes("# 演示 Skill\n用中文回答，并提供一个例子。\n".encode())
        self.wait_seq(2)
        require(self.revision("last")["trigger"] == "watch", "新修订不是监听产生")
        self.cli("status")
        self.cli("log")

    def unchanged_save(self) -> None:
        before = self.get(f"/workspaces/{self.ws}/ops")
        content = self.file.read_bytes()
        for _ in range(5):
            self.file.write_bytes(content)
            time.sleep(0.1)
        # 跨过静默窗口和兜底扫描，不能在尚未处理事件时提前判成功。
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            require(self.status()["head_seq"] == 2, "同内容保存产生了新修订")
            time.sleep(0.1)
        require(self.get(f"/workspaces/{self.ws}/ops") == before, "同内容保存新增了操作日志")

    def anchor(self) -> None:
        self.cli("tag", "tested")
        self.anchor_id = self.revision("tested")["rev_id"]
        require(self.status()["baseline_revision"] == self.anchor_id, "锚点没有推进 Baseline")
        self.anchor_bytes = self.file.read_bytes()
        self.cli("show", "tested")
        self.file.write_bytes("# 演示 Skill\n回答不要超过三段。\n".encode())
        self.wait_seq(3)
        require(self.revision("tested")["rev_id"] == self.anchor_id, "保存移动了锚点")
        require(self.revision("last")["rev_id"] != self.anchor_id, "最新修订没有推进")

    def semantic_diff(self) -> None:
        output = self.cli("diff")
        require("报告：RPT-" in output, "CLI diff 没有返回规范报告")
        report = self.get(f"/workspaces/{self.ws}/diff")
        require(report["base"]["rev"] == self.anchor_id, "默认报告没有使用上一个修订")
        require(report["head"]["rev"] == self.revision("last")["rev_id"], "报告不是当前修订")
        require(
            report["base"]["rev"] == self.revision("last")["parent_rev_id"],
            "默认报告未比较上一个修订",
        )
        require(report["layers"]["semantic"]["status"] == "computed", "L3 没有完成")
        require(report["overview"]["changes"] >= 1, "语义变化未被识别")
        require(report["report_id"] in output, "终端与 API 的报告 ID 不一致")
        require("UTF-8 bytes [" in output, "终端没有展示原文证据位置")
        require("- 用中文回答，并提供一个例子。" in output, "终端缺少修改前原文")
        require("+ 回答不要超过三段。" in output, "终端缺少修改后原文")
        require("UTF-8 bytes" not in self.cli("diff", "--summary"), "简短模式未生效")

    def restart(self) -> None:
        previous = self.get(f"/workspaces/{self.ws}/revisions")
        previous_ops = self.get(f"/workspaces/{self.ws}/ops")
        self.stop()
        self.file.write_bytes("# 演示 Skill\n这是停机期间保存的修改。\n".encode())
        self.start()
        self.wait_seq(4)
        current = self.get(f"/workspaces/{self.ws}/revisions")
        require(len(current) == 4, "重启后修订数量错误")
        require(all(row in current for row in previous), "重启丢失了旧修订")
        require(self.revision("tested")["rev_id"] == self.anchor_id, "重启丢失或移动锚点")
        ops = self.get(f"/workspaces/{self.ws}/ops")
        require(all(row in ops for row in previous_ops), "重启丢失操作日志")
        require(len(ops) == len(previous_ops) + 1, "补获修改没有恰好记录一次操作")
        for command in ("status", "log", "ops"):
            self.cli(command)
        self.cli("show", "tested")

    def restore_cancel(self) -> None:
        self.before_restore_bytes = self.file.read_bytes()
        output = self.cli("restore", "tested", input_text="n\n")
        require("已取消" in output, "取消恢复未得到明确响应")
        require(self.file.read_bytes() == self.before_restore_bytes, "取消恢复改写了文件")
        require(self.status()["head_seq"] == 4, "取消恢复产生了修订")
        require(self.status()["pending_restore"] is None, "取消恢复留下 pending")

    def restore_confirm(self) -> None:
        self.cli("restore", "tested", "--yes")
        self.wait_seq(5)
        require(self.file.read_bytes() == self.anchor_bytes, "恢复未回写锚点原始字节")
        require(
            self.revision("last")["root_tree_oid"] == self.revision("tested")["root_tree_oid"],
            "恢复后的树与目标不符",
        )
        require(self.revision("tested")["rev_id"] == self.anchor_id, "恢复移动了锚点")
        ops = self.get(f"/workspaces/{self.ws}/ops")
        done = [op for op in ops if op["kind"] == "restore.done"]
        require(len(done) == 1, "恢复完成日志数量错误")
        self.completed_plan = json.loads(done[0]["payload_json"])["plan_id"]
        self.cli("restore", "--resume", self.completed_plan, "--yes")
        require(self.get(f"/workspaces/{self.ws}/ops") == ops, "重复计划生成了操作日志")
        self.wait_seq(5)

    def undo_restore(self) -> None:
        self.cli("undo", "--yes")
        self.wait_seq(6)
        require(self.file.read_bytes() == self.before_restore_bytes, "撤销没有恢复操作前内容")
        # 历史已完成计划即使在后续修订后重试也不能再次覆盖当前文件。
        ops = self.get(f"/workspaces/{self.ws}/ops")
        self.cli("restore", "--resume", self.completed_plan, "--yes")
        require(self.get(f"/workspaces/{self.ws}/ops") == ops, "旧计划重试修改了历史")
        require(self.file.read_bytes() == self.before_restore_bytes, "旧计划重试覆盖了撤销后的内容")
        self.wait_seq(6)
        self.cli("undo", "--yes")
        self.wait_seq(7)
        require(self.file.read_bytes() == self.anchor_bytes, "撤销撤销没有回到目标内容")
        require(self.status()["pending_restore"] is None, "恢复结束后 pending 未清除")
        require(self.revision("tested")["rev_id"] == self.anchor_id, "撤销移动了锚点")

    def run(self) -> int:
        checks = [
            ("服务启动、CLI 纳管及初始修订", self.setup),
            ("保存自动生成 watch 修订（未调用手动 snapshot）", self.automatic_save),
            ("同内容保存五次不新增修订或操作日志", self.unchanged_save),
            ("打锚点后继续保存，锚点保持不变", self.anchor),
            ("默认上一个修订到最新修订的语义报告与 CLI diff", self.semantic_diff),
            ("终止服务、停机修改、重启补获及历史保留", self.restart),
            ("恢复预览后取消，文件与修订保持不变", self.restore_cancel),
            ("确认恢复锚点原文、重复计划幂等、锚点不移动", self.restore_confirm),
            ("撤销恢复及撤销撤销、历史保留", self.undo_restore),
        ]
        print(f"测试目录与日志：{self.root}", flush=True)
        failed = False
        try:
            for name, action in checks:
                if failed:
                    self.steps.append({"name": name, "status": "not_run"})
                    print(f"[未运行] {name}", flush=True)
                    continue
                try:
                    action()
                except Exception as exc:
                    failed = True
                    self.steps.append({"name": name, "status": "failed", "error": str(exc)})
                    print(f"[失败] {name}：{exc}", flush=True)
                else:
                    self.steps.append({"name": name, "status": "passed"})
                    print(f"[通过] {name}", flush=True)
        finally:
            self.stop()
            report = {
                "steps": self.steps,
                "passed": not failed and len(self.steps) == len(checks),
                "not_covered": [
                    "真实浏览器点击与视觉验收",
                    "恢复中途强杀与路径冲突（由 pytest 覆盖）",
                    "安装包、平台矩阵及完整产品验收",
                    "Ctrl+C 优雅退出",
                ],
            }
            (self.root / "result.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print("[未覆盖] 真实浏览器点击、安装与平台验收；本次终止进程不等于 Ctrl+C 退出。")
        result = "失败" if failed else f"全部 {len(checks)} 项通过"
        print(f"结果：{result}；详情：{self.root / 'result.json'}")
        return int(failed)


if __name__ == "__main__":
    raise SystemExit(ExperienceCheck().run())
