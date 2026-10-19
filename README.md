# SkillForge

本机 Skill 版本管理器：**修改文件并保存，自动记录快照，在网页或终端查看版本差异。** 支持命名基线、恢复旧版本和撤销恢复。

## 1. 打开可视化界面

Windows 用户在项目根目录双击 **`start-web.cmd`**。首次会准备现有依赖、构建网页并启动本机服务，随后打开浏览器。源码方式需要 uv、Node.js/npm；之后前端没有变化时直接使用已有构建。

也可在项目根目录执行 `uv run skillforge-vm gui`。页面中点击“添加目录”，粘贴 Skill 目录的绝对路径并点击“纳管此目录”，后续操作全部可以在页面完成。关闭浏览器不会停止后台监听；再次打开启动器会复用同一数据根的服务。启动日志在数据目录的 `gui-launch.log`。

## 2. 使用可视化界面

网页与终端共用同一份本机数据，可以任选一种或交替使用。

| 要做什么 | 页面操作 |
| --- | --- |
| 纳管和切换 Skill | “添加目录”填写绝对路径；右上角选择工作区，核对监听目录 |
| 查看状态、手动快照 | “工作区管理”显示当前版本和磁盘状态；“手动快照”填写可选说明后记录 |
| 查看最新变化 | 保存文件后自动更新报告；失败会保留旧结果并明确标记 |
| 查看修改前后 | 展开语义证据，或切换“原文差异”选择变更文件 |
| 指定两个版本及层级 | “指定版本比较”填写锚点、修订 ID 或 `@~1`，选择 L0～L3；留空使用默认端点 |
| 查看历史 | 历史翻页、勾选两点比较，或点击“与当前比较”；新版本点击“查看最新历史” |
| 建立基线 | 输入锚点名称，可指定目标修订；目标留空会先捕获当前磁盘内容 |
| 查看修订、日志 | “修订与续作”查询元数据；“操作日志”查看与翻页，详情可展开 |
| 恢复、撤销恢复 | “恢复到这里”或“撤销最近一次恢复”，核对清单后确认回写；取消不回写 |
| 继续中断恢复 | 状态区“查看并继续恢复”，或在“修订与续作”输入计划 ID，核对后确认 |
| 切换主题 | 右上角选择浅色、深色或跟随系统；浏览器保存偏好，跟随系统会实时响应系统配色 |

界面采用黑白灰及蓝金点缀，原文 diff 保留常用红删绿增。原文是**只读变更片段**，修订详情是元数据，均不是完整快照文件浏览器。ZIP 请先解压。

## 3. 使用终端

以下命令以 Windows PowerShell 为例，在项目根目录执行。需要安装 **uv**；使用源码网页还需要 **Node.js / npm**。仓库使用 Python 3.12，`uv sync` 负责准备 Python 环境和依赖。

### 终端 A：启动服务

```powershell
uv sync
uv run skillforge-vm start
```

保持这个终端运行。服务默认地址为 `http://127.0.0.1:8756`，日志会显示实际地址和数据目录。**网页和业务命令都依赖此服务。**

### 终端 B：纳管 Skill

另开终端，进入同一项目根目录，将示例路径换成你的 Skill 目录：

```powershell
uv run skillforge-vm init "D:\skills\example" --name example
uv run skillforge-vm workspaces
```

纳管会保存第一个版本，之后自动监听这个目录。用编辑器修改其中的 `SKILL.md` 并保存，就会自动产生新快照，无需手动提交。相同内容反复保存不会生成空版本。

之后可以使用下列命令，也可运行 `uv run skillforge-vm gui` 打开同一份数据的网页。

### 前端开发（可选）

仅在需要热更新时，另开终端启动前端：

保持服务运行，另开终端，从项目根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

打开 Vite 输出的地址，通常为 **http://localhost:5173/**。`npm ci` 首次使用或依赖变化后执行即可，以后只需 `npm run dev`。

此方式用于前端热更新开发。日常使用直接双击启动器即可。`/api/docs` 是接口调试页。开发代理固定连接 `127.0.0.1:8756`；若后端选择了其他端口，需核对代理目标。

### 常用命令

保持服务运行，在项目根目录的另一个终端执行：

| 命令 | 作用 |
| --- | --- |
| `uv run skillforge-vm workspaces` | 列出纳管目录和工作区 ID |
| `uv run skillforge-vm status` | 查看当前版本、未捕获改动和未完成恢复计划 |
| `uv run skillforge-vm log` | 查看版本历史 |
| `uv run skillforge-vm diff` | 查看默认基线与当前版本的变化结论 |
| `uv run skillforge-vm tag tested` | 给当前内容打锚点，并设为默认基线 |
| `uv run skillforge-vm diff --base tested --head "@"` | 比较指定锚点与当前版本 |
| `uv run skillforge-vm snapshot --message "调整约束"` | 手动捕获一次快照，日常保存无需执行 |
| `uv run skillforge-vm show tested` | 查看修订元数据 JSON，不是文件全文 |
| `uv run skillforge-vm restore tested` | 预览清单并确认后恢复整个 Skill |
| `uv run skillforge-vm undo` | 撤销最近一次恢复；再次执行会撤销上次撤销 |
| `uv run skillforge-vm ops` | 查看操作日志 |

存在多个工作区时，对业务命令指定工作区 ID，例如 `uv run skillforge-vm diff --ws "工作区ID"`。参数帮助可用 `uv run skillforge-vm diff --help` 等命令查看。

### 一次完整流程

```powershell
# 将当前内容设为参考版本
uv run skillforge-vm tag tested

# 在编辑器修改并保存 SKILL.md，等待自动快照后查看
uv run skillforge-vm status
uv run skillforge-vm log
uv run skillforge-vm diff

# 如需回到参考版本：核对预览清单，再确认
uv run skillforge-vm restore tested

# 如需撤销刚才的恢复
uv run skillforge-vm undo
```

`tested`、`stable` 只是自定义名字，不会自动运行测试。最近创建或移动的命名锚点成为默认基线，后续保存不移动它；没有基线时默认与空树比较全部纳管内容。

## 4. 使用安装包（无需 Node）

拿到 `.whl` 安装包后，先准备 Python 3.11+ 和 pipx，将下面路径替换为实际文件：

```powershell
pipx install "C:\Downloads\skillforge_vm-0.1.0-py3-none-any.whl"
skillforge-vm gui
```

网页中直接“添加目录”即可。发布目录附带 `start-web.cmd`，安装后也可双击它启动。若使用纯终端，执行 `skillforge-vm start` 并保持终端运行，再在另一个终端纳管目录：

```powershell
skillforge-vm init "D:\skills\example" --name example
```

安装包自带网页，**直接打开服务日志里的地址**（默认 `http://127.0.0.1:8756/`），不需要运行 npm。终端操作与第 3 节相同，去掉命令开头的 `uv run` 即可。安装依赖需要网络或已有缓存，wheel 不包含全部依赖。

## 5. 数据与恢复须知

- 快照和历史保存在服务日志显示的数据目录。复制 Skill 文件夹不包含历史，保留历史也要保留数据目录。
- 自定义数据目录时，服务和每条业务命令都使用同一全局参数，放在子命令前，例如 `uv run skillforge-vm --data-root "D:\SkillForgeData" start` 和 `uv run skillforge-vm --data-root "D:\SkillForgeData" status`。数据目录必须在 Skill 目录之外。
- ZIP 需先解压，再纳管解压目录；更新 ZIP 不会自动同步。编辑器里未保存的内容不会进入快照。
- 恢复前保存编辑器缓冲区并暂停编辑。恢复会回写整个 Skill，需核对清单并确认；取消不会回写。恢复后的新编辑会阻止盲目撤销。
- 恢复中断时，在网页状态区点击“查看并继续恢复”；终端也可执行 `status` 后按计划 ID 运行 `restore --resume "计划ID"`。不支持部分文件恢复、文件/目录类型转换或撤销锚点。

当前可用于 Windows 本机试用。完整快照正文浏览、ZIP 同步、测试证据关联、行为执行和自动评分尚未实现；跨平台及完整交付验证边界见下方记录。

## 更多文档

- [详细用户指南](docs/用户使用指南.md)
- [当前交付检查与验证范围](docs/交付检查记录.md)
- [在 Codex 中人工测试 Skill 版本](docs/Codex%20Skill%20版本测试指南.md)
- [设计文档](docs/SkillForge%20版本管理器设计文档.md) · [实现契约与验收](docs/SkillForge%20版本管理器实现契约与验收.md) · [分工计划](docs/SkillForge%20版本管理器分工与交付计划.md)
- 参与开发前阅读 [AGENTS.md](AGENTS.md)；前端规则见 [frontend/AGENTS.md](frontend/AGENTS.md)。
