# SkillForge 版本管理器（SkillForge VM）— Agent Brief

> 团队公共 agent 上下文。本项目是从 SkillForge 主平台**抽离**出来的「版本管理器」，
> 一句话定位：**保存即快照，比较即结论**——用户只负责改，版本、快照、差异、对比全部自动完成。

---

## ⚠️ 最高优先级（每次任务前必做）

### 1. 先读 `AGENTS.LOCAL.md`（如存在）

[`AGENTS.LOCAL.md`](./AGENTS.LOCAL.md) 是个人本地覆盖（git ignore），**冲突时以 LOCAL 为准**；不存在则跳过。

### 2. 改代码 = 改文档

任何代码改动**必须同步更新关联文档**。两份文档都在 `docs/`：

| 改了什么 | 必须更新 |
|---|---|
| `src/skillforge_vm/{module}/**` 业务代码 | 设计文档 §3.2 对应 `M-xx` 模块明细 |
| `db/schema.py` 表结构 / 字段 | 设计文档 §4.5 数据模型（DDL 与字段必须一致） |
| 对象库存储格式（哈希 / 压缩 / 目录布局 / tree 编码） | 设计文档 §4.3 对象存储与去重 |
| HTTP 路由 / 统一返回外壳 / 事件流 | 设计文档 §4.6 接口设计 |
| 新增或更换依赖 | 设计文档 §5.1 选型总表 + §5.3 明确不引入 |
| 模块分层 / 依赖方向 | 设计文档 §4.1 分层架构 + §3.3 模块依赖约束 |
| 语义单元类型（role / constraint …） | 设计文档 §3.2 `M-06`（8 类内置单元） |
| 性能、可复现、依赖等非功能约束 | 设计文档 §2.4 NFR + §4.8 性能与容量目标 |
| 范围 / 排期 / 验收标准变化 | 分工与交付计划对应周次与验收表 |

**自查**：commit diff 有代码 + 无文档 → 检查是否漏改。
**新增文档**：放进 `docs/`，并在本文件「文档组织」段落登记。

### 3. 并行调度 sub agent

**首要目的**：用独立 context 隔离搜索 / 大文件读取 / 长日志，保护主上下文；其次才是提速。

独立、职责不重叠的子任务**单条消息内**派发多个 `Agent` 并行；写操作用 `isolation: worktree`；主线负责汇总与一致性校验。**不嵌套**（sub agent 内不再派 sub agent）。**worktree 用完即清**（`git worktree remove` + 删临时分支）。

**串行 / 不派**：任务琐碎（token 不划算）/ 有数据依赖 / 同资源无隔离 / 需全局一致性 / 涉及对象库格式或接口契约的改动。

### 4. 对齐唯一验收标准与三条铁律

**总验收（唯一标准）**：

> 在一台机器上改一次 Skill → **不做任何版本操作** → 看到一份可读、可复现的语义级对比报告 → 可打锚点 → 可撤销。**全程零仪式。**

**三条减负铁律**（每次做取舍时按此排序）：

**文件优先于界面 · 规则优先于模型 · 复用优先于自研。**

---

> 以下为参考资料。**冲突时服从上面的最高优先级。**

## 项目概述

Python 3.11+ 后端 + Vite/React 前端的**单机、单用户**版本管理服务（NFR-09「轻依赖」是硬约束）。

| 用途 | 选型 |
|---|---|
| 后端语言 / 环境 | Python 3.11+（uv 托管 3.12）|
| 网络服务 | FastAPI + uvicorn |
| 数据校验 | Pydantic（一套模型同时管配置 / 报文 / 报告）|
| 元数据存储 | SQLite（WAL 模式）|
| 对象库 | **自研**内容寻址 + zlib（SHA-256，两级目录），不内嵌 Git |
| 文件监听 | watchfiles（自带抖动合并）|
| 结构化解析 | tree-sitter（Markdown / YAML / JSON）|
| 文本 diff | 自研行级 + 词级高亮 |
| 前端 | Vite + React + TypeScript + **CodeMirror 6 MergeView** |
| 命令行 | Typer / Click（**只是服务客户端，不直连数据库**）|
| 发布 | pipx + 预构建前端产物（终端用户**免装 Node**）|

## 模块与分工

| 工作线 | 负责模块 |
|---|---|
| **A｜存储内核线** | M-01 工作区 · M-02 监听快照 · M-03 对象库 · M-04 修订引用 · M-09 操作日志 · M-10 接口层 · M-12 CLI |
| **B｜对比呈现线** | M-05 分层对比 · M-06 语义抽取 · M-07 聚类降噪 · M-08 报告结论 · M-11 对比界面 · M-13 行为适配器（**仅接口**）|

- 动对方线的模块前**先沟通**；接口契约在第 1 周冻结，之后变更需双方确认。
- **M-05 是唯一允许同时接触对象库与解析器的模块**（§3.3）；其余模块只走公开接口。
- M-13 **只定义契约，零实现**（FR-09.1）。

## 目录结构

```
SkillForge/
├── pyproject.toml / uv.lock / .python-version
├── README.md / AGENTS.md / AGENTS.LOCAL.md（可选，gitignore）
├── docs/                          # 设计文档 + 分工与交付计划
├── src/skillforge_vm/             # 后端包（src 布局）
│   ├── core/                      # 错误类型、哈希、常量、全局配置
│   ├── db/                        # SQLite 连接与全量表结构（§4.5）
│   ├── workspace/                 # M-01 工作区管理
│   ├── watcher/                   # M-02 改动监听与快照
│   ├── objectstore/               # M-03 对象库与去重
│   ├── revision/                  # M-04 修订与引用（revset）
│   ├── diff/                      # M-05 分层对比引擎（L0~L3）
│   ├── semantics/                 # M-06 语义抽取器
│   ├── cluster/                   # M-07 聚类与降噪
│   ├── report/                    # M-08 报告与结论
│   ├── oplog/                     # M-09 操作日志与撤销
│   ├── adapters/                  # M-13 行为对比适配器（预留）
│   ├── api/                       # M-10 接口层
│   └── cli/                       # M-12 命令行客户端
├── tests/                         # pytest
├── scripts/
└── frontend/                      # M-11 对比界面
    ├── package.json / tsconfig.json / vite.config.ts / index.html
    └── src/{main.tsx, App.tsx, views/, components/, styles/, lib/}
```

## 命令清单

```bash
uv sync                      # 创建 .venv 并安装后端依赖
uv run pytest                # 后端测试
uv run ruff check .          # 静态检查
uv run ruff format .         # 格式化

cd frontend
npm install
npm run dev                  # 前端开发（/api 代理到 127.0.0.1:8756）
npm run build                # 构建到 frontend/dist（打包时内置产物）
```

> uv 若为「按用户安装」，需确保 `%USERPROFILE%\.local\bin`（Windows）/ `~/.local/bin`（Unix）在 PATH 中。

## 文档组织

`docs/` 下：

| 文件 | 内容 | 何时更新 |
|---|---|---|
| `SkillForge 版本管理器设计文档.md` | 产品定义 / 需求 / 模块 / 架构 / 技术栈 / 关键决策 | 产品、技术契约变化 |
| `SkillForge 版本管理器分工与交付计划.md` | 两人分工、每周任务、双方验收标准 | 范围 / 排期变化 |

设计文档内部章节定位：§2.4 NFR、§3.2 模块明细、§4.3 对象存储、§4.5 数据模型、§4.6 接口设计、§5.1 选型。

## 边界规则

### ✅ 可自主做

- 编辑 `src/skillforge_vm/**` 业务代码，补 `tests/**`
- 跑 `uv run pytest` / `ruff` / 前端 `npm run build`
- 在 `docs/` 起草设计补遗

### ⚠️ 先问

- 改 SQLite 表结构 / 对象库存储格式（影响既有数据与可复现）
- 引入新外部依赖（**NFR-09 轻依赖**）
- 改 `pyproject.toml` / `vite.config.ts` / 模块分层与依赖方向
- 跨线改动（A ↔ B 的模块）或改接口契约
- 改设计文档中的**设计原则 / 验收标准**

### 🚫 绝不

- `git push --force` 到 main
- 跳 hook（`--no-verify`）
- **往用户 Skill 目录写文件**（FR-01.3 / NFR-12：默认数据落独立数据目录）
- 跨层直读数据库，或让上层绕过公开接口（NFR-11）
- 引入 Redis / Celery / 消息队列 / 外部数据库 / 向量库（NFR-09 / §5.3）
- 把用户 Skill 内容**默认**发往远端（NFR-07：断网可用，数据不出本机）
- **自研 diff 渲染组件**（§6.5：复用 CodeMirror / Monaco / diff2html）
- 用大模型做差异分析（§5.2；模型只允许用于「聚类标签」这一个出口，且可关闭）

## 操作前必读

- **改某模块**：设计文档 §3.1 模块总览 + §3.2 该 `M-xx` 明细，以及分工计划中对应周次
- **改对象库 / 快照链路**：§4.3 对象存储与去重、§4.1 分层架构（**快照执行器必须串行**，否则破坏可复现）
- **改数据模型**：§4.5（表与字段必须与 DDL 一致）
- **加解析器 / 语义抽取器**：§3.2 `M-06`（8 类内置单元）+ NFR-10（**不改调度、存储与接口**）
- **改接口 / CLI**：§4.6（统一返回外壳、具体错误码）
- **改报告结构**：§4.5 报告 JSON 骨架 + §7.7 缓存与可复现

## 关键约束速查（写代码时对照）

| 约束 | 要求 | 出处 |
|---|---|---|
| 零写入 | 内容不变 → 不进对象库、不建 Revision | NFR-01 / EDGE-02 |
| 可复现 | 同 `(base, head, layer, algo_version)` → 报告逐字节相同；列表排序必须确定 | NFR-04 / FR-03.10 |
| 不入侵 | 默认不修改用户仓库任何文件，不装 Git 钩子 | NFR-12 |
| 降级不阻断 | 解析失败回退 L1，不报错、不影响其余文件 | FR-03.6 / NFR-06 |
| 具体错误 | 错误是具体原因（`工作区未初始化` / `对象库不可写`），禁止「内部错误」 | FR-08.4 |
| 数据不出本机 | 断网仍可完成快照与全部静态对比 | NFR-07 |
| 去重有效 | 10000 次快照，对象库增长与净变化同阶 | NFR-03 |

---

# Development Guide

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.