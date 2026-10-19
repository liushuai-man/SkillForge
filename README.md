# SkillForge

Agent Skill 的版本管理与版本对比内核（SkillForge 版本管理器 / SkillForge VM）。

**保存即快照，比较即结论** —— 用户只负责改，版本、快照、差异、对比全部自动完成。

设计文档见 [docs/](docs/)：

- [SkillForge 版本管理器设计文档](docs/SkillForge%20版本管理器设计文档.md)
- [SkillForge 版本管理器分工与交付计划](docs/SkillForge%20版本管理器分工与交付计划.md)
- [SkillForge 版本管理器实现契约与验收](docs/SkillForge%20版本管理器实现契约与验收.md)
- [Codex Skill 版本测试指南](docs/Codex%20Skill%20版本测试指南.md)

设计文档描述目标能力，不代表功能已经实现。开始开发前先读 [AGENTS.md](AGENTS.md)，按任务查阅对应契约和验收用例；MVP 范围以设计文档 §8.1 为准。

首次使用请先读 [用户使用指南](docs/用户使用指南.md)：安装与启动、Web 操作、自动快照、stable/tested 基线和完整示例。当前交付验证与限制见 [交付检查记录](docs/交付检查记录.md)。

## Agent 协作规则

共享规则维护在根目录 [AGENTS.md](AGENTS.md)，前端局部规则见 [frontend/AGENTS.md](frontend/AGENTS.md)；从根目录修改前端时也需先读局部规则。个人覆盖使用可选的 `AGENTS.LOCAL.md`（已忽略，不提交）。领域术语维护在根目录 [CONTEXT.md](CONTEXT.md)。

仓库当前没有随项目提交的 `SKILL.md` 技能；用户环境中的技能（如 `project-agent-init`）不是项目依赖，也不保证其他开发者已安装。规则文件提供行为指引，不能代替测试或 CI 的执行结果。

## 开发环境

本仓库使用 [uv](https://docs.astral.sh/uv/) 管理 Python 3.12 与后端依赖。

```bash
uv sync                 # 创建 .venv 并安装后端依赖
uv run pytest           # 运行测试
uv run ruff check .      # 后端静态检查
uv run ruff format <本次修改的Python文件>  # 只格式化指定文件

cd frontend
npm ci                  # 按 package-lock.json 安装依赖
npm run dev             # 前端开发
npm run typecheck       # TypeScript 检查
npm run build           # 类型检查并构建前端
```

命令入口和配置已按 `pyproject.toml`、`frontend/package.json` 与锁文件核对；实际执行是否通过，以每次任务的验证记录为准。前端没有单独的 test、lint 或 format 脚本。

## 快速开始（本机服务 + CLI）

CLI 是服务的客户端（不直连数据库）：先启动服务，再用业务命令操作。

```bash
uv run skillforge-vm --data-root <数据目录> start   # 启动本机服务（默认 127.0.0.1:8756）
uv run skillforge-vm --data-root <数据目录> init <Skill目录>               # 纳管一个 Skill
uv run skillforge-vm status                         # 是否有未纳管改动
uv run skillforge-vm snapshot --message "改标题"     # 手动快照
uv run skillforge-vm tag tested                     # 打锚点
uv run skillforge-vm log                            # 修订时间线
uv run skillforge-vm ops                            # 操作日志
```

- 自定义数据目录时，每个命令均传全局 `--data-root <数据目录>`（放在子命令前），或统一设置 `SKILLFORGE_VM_DATA_ROOT`；以下省略目录的命令使用默认数据根。
- 服务端口被占用时自动改用系统分配端口，并把实际地址写入数据根的 `runtime.json`；后续命令据此复用同一服务，也可用 `--url` 或环境变量 `SKILLFORGE_VM_URL` 覆盖。
- HTTP 接口见 `http://127.0.0.1:8756/api/docs`；统一返回外壳为 `{ok, data, error, request_id}`。
- **当前已实现**：工作区纳管、文件监听与快照、修订/变更/引用、操作日志、L0～L3 静态对比与规范报告、Baseline、基础 Web 对比/历史、本机服务与 CLI。
- **受控恢复已实现**：`skillforge-vm restore tested` 先保护当前内容、预览清单并确认，再恢复整个 Skill；`skillforge-vm undo` 撤销最近一次恢复（包括撤销撤销）。恢复后有新改动时拒绝盲目覆盖；中断后 `status` 显示计划，可 `restore --resume PLAN` 继续，自动化须显式 `--yes`。请先保存并暂停编辑器写入；未保存缓冲区无法保护。部分文件恢复、文件/目录类型转换、撤销锚点暂不支持。
- **尚未实现**：Codex/Agent 行为执行与自动评测、跨机器工作区导入导出、区间对比与独立报告导出；M-13 仍只有类型契约，报告的 `behavior` 为 `null`。

> 包含预构建前端、运行时免 Node 的候选安装包已通过 Windows 本机干净虚拟环境安装与运行验证；pipx 实装、跨平台与完整 G3 尚未签收，见交付检查记录。

## 在 Codex 中测试 Skill 版本

仓库级 Skill 推荐放在 `<项目>/.codex/skills/<skill-name>/`，SkillForge 只纳管这个 Skill 目录；固定测试用例放在相邻的 `<项目>/evals/`，避免测试记录进入 Skill 快照。测试不同版本时，先 `restore <ref>`，再新建 Codex 任务并用同一批显式、隐式和负向用例复测。完整步骤、跨电脑交付限制与结果模板见 [Codex Skill 版本测试指南](docs/Codex%20Skill%20版本测试指南.md)。

SkillForge 当前不运行 Codex，也不自动评分；只复制项目文件只包含当前 Skill 内容，不包含作者电脑上的 Revision、锚点和对象库。

## 构建与验证安装包

想一次验证当前 A 线体验，在项目根目录运行：

```powershell
uv run --no-sync python scripts/check_experience.py
```

脚本自动启动随机端口的真实服务、CLI 纳管测试 Skill，检查自动快照、相同内容五次保存不新增修订/Op、锚点固定，以及停止服务后修改再重启补获、恢复预览后取消、确认恢复、重复计划幂等、撤销及撤销撤销，共 9 项，包含默认 Baseline→Working 报告与 CLI diff。无需另开终端或手动编辑。每次新建独立目录，结果及服务/CLI 日志保留在 `dist/experience-check/run-*/`；失败退出码为 1，后续依赖步骤标记未运行。仅操作生成的测试 Skill，不接触现有用户目录。Windows 使用真实解释器避免 uv 启动器 PID 差异；停止测试服务使用终止进程，不等同 Ctrl+C 优雅退出验收。真实浏览器界面与安装包验收不计入此脚本通过项；恢复中途强杀和路径冲突由 pytest 单独覆盖。

开发机先运行 `uv run python scripts/build_release.py`（使用现有 Node 依赖与离线 Python 构建缓存），生成包含前端资源的 `dist/skillforge_vm-0.1.0-py3-none-any.whl`。终端用户可用 `pipx install <wheel路径>` 安装，运行时不需要 Node。

运行 `uv run python scripts/verify_release.py <wheel路径>` 检查离线缓存安装与服务；缓存不足时会明确失败。可显式追加 `--reuse-installed-deps` 仅验证包运行，此结果不算干净环境依赖安装通过。当前候选包已完成本机干净虚拟环境安装及无 Node 运行验证；真实浏览器验证与未测平台边界见交付检查记录，不因此宣称完整 G3 通过。
