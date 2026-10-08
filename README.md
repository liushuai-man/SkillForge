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

服务与 CLI 的目标使用流程见设计文档 §4.6 / §4.7；入口实现并通过安装验收后，再将可执行的用户启动步骤登记在此。
