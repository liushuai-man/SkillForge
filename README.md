# SkillForge

Agent Skill 的版本管理与版本对比内核（SkillForge 版本管理器 / SkillForge VM）。

**保存即快照，比较即结论** —— 用户只负责改，版本、快照、差异、对比全部自动完成。

设计文档见 [docs/](docs/)：

- [SkillForge 版本管理器设计文档](docs/SkillForge%20版本管理器设计文档.md)
- [SkillForge 版本管理器分工与交付计划](docs/SkillForge%20版本管理器分工与交付计划.md)
- [SkillForge 版本管理器实现契约与验收](docs/SkillForge%20版本管理器实现契约与验收.md)

设计文档描述目标能力，不代表功能已经实现。开始开发前先读 [AGENTS.md](AGENTS.md)，按任务查阅对应契约和验收用例；MVP 范围以设计文档 §8.1 为准。

## 开发环境

本仓库使用 [uv](https://docs.astral.sh/uv/) 管理 Python 3.12 与后端依赖。

```bash
uv sync                 # 创建 .venv 并安装后端依赖
uv run pytest           # 运行测试

cd frontend && npm install && npm run dev   # 前端开发
```

## 快速开始（本机服务 + CLI）

CLI 是服务的客户端（不直连数据库）：先启动服务，再用业务命令操作。

```bash
uv run skillforge-vm start --data-root <数据目录>   # 启动本机服务（默认 127.0.0.1:8756）
uv run skillforge-vm init <Skill目录>               # 纳管一个 Skill
uv run skillforge-vm status                         # 是否有未纳管改动
uv run skillforge-vm snapshot --message "改标题"     # 手动快照
uv run skillforge-vm tag tested                     # 打锚点
uv run skillforge-vm log                            # 修订时间线
uv run skillforge-vm ops                            # 操作日志
```

- 服务端口被占用时自动改用系统分配端口，并把实际地址写入数据根的 `runtime.json`；后续命令据此复用同一服务，也可用 `--url` 或环境变量 `SKILLFORGE_VM_URL` 覆盖。
- HTTP 接口见 `http://127.0.0.1:8756/api/docs`；统一返回外壳为 `{ok, data, error, request_id}`。
- **当前已实现**：工作区纳管、文件监听与快照、修订/变更/引用、操作日志（记录）、本机服务与 CLI。
- **尚未实现**：语义/文本对比与报告（B 线 M-05~M-08）、对比界面（M-11）、`undo/restore`（受 TBD-08/TBD-09 阻塞）。`diff` 与 `undo` 命令会以非零退出并说明原因，不返回伪成功。

> 安装包（pipx + 预构建前端、终端用户免 Node）与跨平台验证尚未完成，见设计 §4.7 与实现契约 §6。
