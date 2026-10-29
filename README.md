# 留痕

保存即留痕，比较见原文。本机技能版本管理器：自动记录快照，查看两版全文与行级差异，按需标记、恢复或撤销。产品显示名为“留痕”；仓库、命令和数据目录名称保持兼容。

## 首次准备（源码）

需要 Git、uv 和 Node.js 22.12+。在项目根目录执行一次：

```powershell
uv sync
npm --prefix frontend ci
npm --prefix desktop ci
```

## 日常启动与开发

| 场景 | 在项目根执行 | 数据与退出方式 |
| --- | --- | --- |
| 日常桌面 | `.\start-desktop.cmd` | 使用原默认数据根，与命令行共用；关闭到托盘，明确退出才停止自有服务 |
| 隔离桌面试用 | `.\test.cmd desktop` | 自动分配全新测试数据根，先构建界面；不混用日常历史 |
| 前端热更新开发 | `.\dev.cmd` | 在浏览器打开，数据为 `dist/dev/data`；Ctrl+C 停止本次前后端 |
| 浏览器兼容入口 | `.\start-web.cmd` | 使用默认数据根；关闭浏览器仍继续监听 |

桌面窗口标题只显示“留痕”。日常启动会按需构建界面；已有依赖无需反复安装。`dev.cmd` 是浏览器热更新入口，不是桌面热更新。

已构建的 Windows 便携包直接双击 **留痕.exe**，无需外装 Python/Node；同目录 `skillforge-vm.cmd` 调用本机服务。完整目录需一起保留。现有 wheel 则仍需 Python 3.11+ 和 pipx，见[用户使用指南](docs/用户使用指南.md)。

## 测试与隔离试用

统一入口：`test.cmd`，失败会返回非零退出码，遇到失败即停止后续步骤。

| 命令 | 执行内容 |
| --- | --- |
| `.\test.cmd` | 后端静态检查、完整后端回归、前端构建、桌面通信单测 |
| `.\test.cmd desktop` | 打开可手动操作的隔离桌面；从托盘或应用菜单退出后结束 |
| `.\test.cmd smoke` | 真实桌面自动验收：名称、全文、保存刷新、托盘和单实例 |
| `.\test.cmd experience` | 真实服务与命令行流程验收 |
| `.\test.cmd portable --bundle "dist\desktop\留痕"` | 验收指定的已有便携包 |
| `.\test.cmd --help` | 查看模式、环境准备和测试目录说明 |

测试入口复用现有脚本，不自动安装依赖、不自动删除历史证据、不默认打包或执行性能检查。桌面/便携测试每次创建新目录并打印位置，可重复执行；默认根为仓库同级 `Mytest/skillForge-testskills`。本机为 `D:\mycode\Mytest\skillForge-testskills`，可用 `SKILLFORGE_TEST_ROOT` 覆盖。**只放生成的测试技能，不要放真实技能。**

默认回归不等于真实桌面或便携包验收；本机通过不代表新机器、物理断网、签名或跨平台通过。底层命令仍可单独定位失败：

```powershell
uv run pytest
uv run ruff check .
npm --prefix frontend run build
npm --prefix desktop test
```

## 构建并验收便携包

每次使用新输出目录，保留旧包；以下 PowerShell 命令可连续执行：

```powershell
$packageDir = Join-Path "dist\desktop" ("留痕-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
npm --prefix frontend run build
uv run python scripts/build_desktop.py --output $packageDir
.\test.cmd portable --bundle $packageDir
```

目前提供 Windows 同架构便携包，尚无安装器、签名或自动更新。构建会复制当前已准备的 Python 环境及依赖，不能跳过首次准备。

## 常用命令行

默认桌面和命令行使用同一数据根；开发服务或自定义数据根须显式保持一致。

```powershell
uv run skillforge-vm diff
uv run skillforge-vm diff --context 5
uv run skillforge-vm diff --summary
```

文件名、用户正文、锚点名和技术标识保持原值，不做语义、聚类、风险或行为分析。详细操作见[用户使用指南](docs/用户使用指南.md)。
