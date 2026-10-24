# SkillForge

本机 Skill 版本管理器：保存文件后自动记录快照，通过网页左右全文或终端 Git 风格 diff 看清改动，随时标记和恢复版本。

## 安装

源码开发需要 Git、uv、Node.js/npm。在 PowerShell 中执行：

```powershell
git clone https://github.com/liushuai-man/SkillForge.git
cd SkillForge
uv sync
```

已有安装包时，安装 Python 3.11+ 和 pipx 后执行（无需 Node）：

```powershell
pipx install "安装包路径\skillforge_vm-0.1.0-py3-none-any.whl"
```

## 启动和快速打开

开发环境在项目根目录执行一个命令：

```powershell
.\dev.cmd
```

自动准备前端依赖、启动前后端并打开 `http://127.0.0.1:5173/`。前端修改支持热更新；后端修改后按 Ctrl+C 停止并重新运行。关闭该命令会停止本次启动的前后端。开发数据保存在 `dist\dev\data`。

同一开发环境只启动一次；再次运行会提示已有服务地址，请先在原终端按 Ctrl+C。启动失败的具体原因保存在 `dist\dev\service.log`。

日常使用源码版本，可双击 `start-web.cmd`；它按需构建网页并打开本机服务，关闭浏览器后仍继续监听。安装包用户执行：

```powershell
skillforge-vm gui
```

## 测试

在项目根目录执行：

```powershell
uv run pytest
uv run ruff check .
npm --prefix frontend run build
```

真实服务与终端流程检查：

```powershell
uv run python scripts/check_experience.py
```

本机测试 Skill 统一放在 `D:\mycode\Mytest\skillForge-testskills`，各次运行使用独立子目录；不要将真实 Skill 放入测试临时目录。其他机器默认使用仓库同级的 `Mytest\skillForge-testskills`，可通过 `SKILLFORGE_TEST_ROOT` 指定位置。

## 更新

源码版本：先在开发终端按 Ctrl+C 停止，再在项目根目录执行：

```powershell
git pull
uv sync
.\dev.cmd
```

安装包版本：停止旧服务，使用新 wheel 重新安装，再打开：

```powershell
pipx install --force "新安装包路径\skillforge_vm-0.1.0-py3-none-any.whl"
skillforge-vm gui
```

详细功能操作见 [用户使用指南](docs/用户使用指南.md)。

## 看改了哪里

网页直接选择旧版/新版，点左侧文件查看完整对齐正文；F7/Shift+F7跳转变化。终端：

```powershell
skillforge-vm diff
skillforge-vm diff tested @ --file SKILL.md
skillforge-vm diff --context 5
skillforge-vm diff --summary
```

不做语义、聚类、风险或行为分析。保存自动记录，恢复始终先预览确认。
