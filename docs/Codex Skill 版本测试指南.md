# Codex Skill 版本测试指南

> 当前工具只记录版本和展示文件/行级差异；本指南中的人工行为复测为可选外部活动，不是管理器功能或交付门槛。

本文说明如何把 SkillForge VM 管理的 Skill 放在 Codex 项目中，并用同一组任务测试不同版本。它是人工行为验收流程，不改变产品边界：SkillForge VM 负责文件快照、静态对比和受控恢复；Codex 负责加载 Skill 并执行任务；测试人员负责判断行为结果。

## 1. 适用范围与限制

- 推荐测试仓库级 Skill：`<项目>/.codex/skills/<skill-name>/SKILL.md`。
- SkillForge 只纳管 `<skill-name>` 目录，不纳管整个项目。
- 测试用例和结果放在 `<项目>/evals/`，不要放入被纳管的 Skill 目录，否则测试记录本身也会成为 Skill 版本的一部分。
- Codex 同一时刻只测试磁盘上的当前 Skill 内容。SkillForge 不向 Codex 注册多个可并行选择的历史版本。
- 为避免旧任务已经加载旧指令，每次恢复版本后都新建 Codex 任务，再执行测试。
- 当前 MVP 不运行 Codex、不自动评分，也不保存行为结果到规范报告；报告中的 `behavior` 固定为 `null`。

OpenAI 官方建议先显式触发 Skill，再用显式触发、隐式触发和不应触发的负向用例组成固定测试集。参见 [Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills)。

## 2. 项目布局

```text
my-project/
├─ .codex/
│  └─ skills/
│     └─ my-skill/
│        ├─ SKILL.md
│        ├─ references/
│        ├─ scripts/
│        └─ assets/
└─ evals/
   ├─ my-skill-cases.md
   └─ results/
      ├─ tested-v1.md
      └─ candidate-v2.md
```

`SKILL.md` 的 YAML front matter 中应有稳定的 `name` 和明确的 `description`。版本之间不要随意更改 `name`，否则无法用同一个 `$skill-name` 做对照测试。

## 3. 首次纳管与建立已知良好版本

先启动服务，再纳管 Skill 目录：

```powershell
skillforge-vm start
```

另开一个 PowerShell：

```powershell
skillforge-vm init "D:\my-project\.codex\skills\my-skill"
skillforge-vm status
```

在 Codex 中打开 `D:\my-project`，新建任务并显式调用：

```text
请使用 $my-skill 完成：<固定测试任务>
```

初始版本通过后再打锚点：

```powershell
skillforge-vm tag tested-v1
```

命名锚点供显式选择，默认仍比较最新与父修订。未经验证的候选版本不要命名为 `tested-*`。

## 4. 修改后的单版本验收

1. 使用 Codex 或编辑器修改 Skill，并保存所有文件。
2. 等待监听完成，然后检查静态变化：

   ```powershell
   skillforge-vm status
   skillforge-vm log
   skillforge-vm diff
   ```

3. 新建 Codex 任务，确认 `/skills` 中能发现目标 Skill。
4. 先用 `$my-skill` 显式触发，再依次运行固定用例。
5. 把模型、权限、输入、输出和判定写入 `evals/results/candidate-v2.md`。
6. 全部通过后再建立锚点：

   ```powershell
   skillforge-vm tag tested-v2
   ```

最低测试集：

| 类型 | 目的 | 最低要求 |
| --- | --- | --- |
| 显式触发 | 验证 Skill 可被直接调用 | 提示词包含 `$my-skill` |
| 隐式触发 | 验证 `name` / `description` 路由有效 | 不写 Skill 名但命中目标场景 |
| 负向用例 | 防止过度触发 | 相邻但不属于该 Skill 的任务 |
| 正常结果 | 验证主要工作流 | 检查产物、步骤和输出约束 |
| 失败路径 | 验证缺输入或环境失败 | 错误具体，不伪造成功 |

## 5. 同一台电脑上的 V1 / V2 对照测试

每次恢复都会先展示文件变化并要求确认。恢复前保存编辑器缓冲区，并暂停其他程序写入 Skill 目录。

测试 V1：

```powershell
skillforge-vm restore tested-v1
```

确认恢复后，新建 Codex 任务，运行完整固定测试集，将结果记录为 `tested-v1.md`。

测试 V2：

```powershell
skillforge-vm restore tested-v2
```

再次新建 Codex 任务，保持以下条件一致后运行同一测试集：

- Codex 模型及推理设置；
- 项目目录与权限；
- 输入文件和测试提示词；
- 联网状态及外部工具可用性；
- 结果判定标准。

不要在一次旧对话中连续测试两个版本；上下文差异会污染对照结果。恢复操作本身会生成新的 Revision，但原锚点仍指向被测试的不可变内容。

## 6. 交给另一台电脑测试

只复制项目文件夹时，对方只能获得当前 Skill 内容，不能获得作者电脑上的 Revision、锚点、报告和对象库。当前 MVP 没有工作区导出/导入或跨机器路径迁移功能，因此不得把“复制项目”描述为“带历史交付”。

当前可选流程：

### 6.1 只验收候选版本

交付以下内容：

- 当前项目文件；
- SkillForge VM 安装包；
- `evals/my-skill-cases.md`；
- 预期结果与测试环境说明。

测试人员在自己的电脑上重新执行 `init`，形成新的本地工作区，然后在 Codex 中测试当前候选版本。

### 6.2 必须对照多个历史版本

在正式导出/导入功能完成前，由作者分别恢复已验证锚点，并为每个锚点制作只读测试副本，例如 `my-skill-tested-v1.zip` 和 `my-skill-tested-v2.zip`。测试人员每次只把一个版本放入项目的同一 `.codex/skills/my-skill/` 路径，重开 Codex 任务并运行同一测试集。

这些测试副本是行为测试输入，不是 SkillForge 历史数据库。不要复制单独的 `meta.sqlite3`：没有对应的 `objects/` 和有效路径配置，历史不完整。

## 7. 结果记录模板

```markdown
# my-skill / tested-v2

- Skill ref：tested-v2
- Revision：<rev_id>
- Codex 模型与设置：<model / reasoning>
- 项目路径：<path>
- 测试时间：<time>

| 用例 | 是否触发 | 结果 | 证据/产物 | 结论 |
| --- | --- | --- | --- | --- |
| explicit-01 | 是 | ... | ... | 通过/失败 |
| implicit-01 | 是 | ... | ... | 通过/失败 |
| negative-01 | 否 | ... | ... | 通过/失败 |

## 总结

- 通过数：
- 失败数：
- 相对上一版本的改善：
- 回归：
- 是否可标记为 tested：
```

## 8. 完成判定

一次有效的 Codex 版本测试至少满足：

- 被测版本可由不可变锚点或明确的候选 Revision 定位；
- SkillForge 静态报告已保存，且能说明文件层面的变化；
- 每个版本都在新 Codex 任务中运行同一测试集；
- 触发、结果、失败和环境条件均有记录；
- 只有通过验收的版本才创建 `tested-*` 锚点；
- 行为结果不冒充 SkillForge 规范报告的一部分。
