# 首次配置与跨会话复用

用户说“初始化 DF Agent”或首次调用所需能力时使用。Windows 新安装默认状态位置为 `%LOCALAPPDATA%\DF-Agent`；PowerShell 接口允许 `-StateDir` 指定其他位置，Python 接口要求显式 `--state-dir`。只检查明确选中的本地状态，不搜索其他应用的配置、聊天或业务来源。保存配置需要 `setup` 写入范围，保存计划/报告另需 `output` 写入范围，详见 [文件访问](access.md)。用户已有明确设置范围和授权时可以直接完成；`plan`/`apply` 是可审阅和防过期机制，不要求每次重新询问权限。

改名前已配置的电脑保持兼容：未提供 `-StateDir` 时，优先使用 `DF-Agent\setup.local.json`；它不存在而旧目录 `%LOCALAPPDATA%\TeamAdvisor\setup.local.json` 存在时，直接沿用旧目录中的配置。两处都没有配置则选择新的 `DF-Agent` 目录；两处都有配置则新目录优先。明确的 `-StateDir` 始终优先。这个选择只判断两份专用配置是否存在，不合并、迁移、重置配置或读取记忆正文。后续记忆和反馈应沿用返回的实际 `state_dir`，不要仅因改名创建第二份数据。原有配置的 schema 标识保持兼容；名称变化不改变数据格式。

本文件中的 `roots`、`preferred_sources` 是**技能安装来源**；不是公司资料库 profile。入口不保存第二份资料源目录，也不把技能设置 `unchanged` 当成 reader 或业务验收通过。资料范围与接入信息由 df-mcp 管理。

## 日常入口

入口的 `scripts/setup.ps1 -Action Status` 默认只向 stdout 返回结果，会读取保存的解释器和技能根，在新进程重新执行公共文件检测，不要求用户记住路径或命令。没有配置则返回 `not_configured`，助手从当前宿主已提供的技能目录和真实运行环境选出待配置值；缺少会影响选择的信息才询问。

`status` 的 `unchanged` 仅表示配置指纹未变化。仍按 `capabilities.skills` 的具体任务和五层检查决定能做什么；文件存在不等于宿主已发现，也不等于连接、分析或草稿已经通过。输出含本机路径，应作为本地私有状态处理，不上传 GitHub 或直接向同事转发。

## 首次配置

下面由助手根据已经明确的本机目录执行，用户不必自己填写命令。`$entrySetup` 是本 skill 的 `scripts/setup.ps1`，其余变量均为本轮已选定的真实路径；需要保存时，计划文件选已授权输出目录中的新 `*.local.json`，须在插件、仓库、技能根及托管状态目录之外。省略 `-OutputPath` 的 Plan 只返回完整计划 JSON，不写文件。

```powershell
& $entrySetup -Action Plan -StateDir $stateDir -Roots $approvedRoots -PythonPath $chosenPython -OutputPath $newPlan -TaskId $taskId -WriteRoot $outputRoot -AllowOperation output
& $entrySetup -Action Apply -StateDir $stateDir -PlanPath $newPlan -PythonPath $chosenPython -TaskId $taskId -WriteRoot $stateDir -AllowOperation setup
& $entrySetup -Action Status -StateDir $stateDir -SessionId $currentSession
```

计划列出根目录、运行时、具体来源和公共指纹，应用前再次核对；如果期间源文件、依赖版本或已保存配置有变化，拒绝应用，创建新计划。应用仅原子写入 `setup.local.json`，不安装依赖、不修改专业技能、不启动资料 reader、不连接业务来源。

只有一份可读来源时固定该来源；某专业技能未安装不会阻止保存其他能力。同名存在多份，或指定绑定已失效时，应选择实际来源后提供现有 doctor 格式的 `-BindingsPath`：

```json
{
  "preferred_sources": {
    "etf-comment-drafts-v2": "ROOT_1/selected-copy/SKILL.md"
  }
}
```

`ROOT_1` 等别名严格对应本次 `-Roots` 的顺序，不能任意改根后沿用别名。已选来源的真实路径是相应根目录加别名后的相对路径。专业技能使用者仍须读取被选来源的完整 `SKILL.md`。

## 变化与恢复

后续 Status 返回 `changed` 时，`changed_components` 区分运行时、来源、选择或扫描覆盖变化。保留原设置，重读受影响的来源并按任务复核；确认新环境后重新 Plan / Apply，修订号递增。另一个副本出现不会取代已有绑定。没有变化也不继承上次的宿主发现或任务成功证据。

若保存的 Python 已不存在，明确提供 `-PythonPath` 作为本次检查或修复的启动解释器；Status 仍报告原保存运行时的失效，Plan / Apply 才更新设置。锁文件 `.setup.lock` 防止同时写入；进程异常后可能残留，先确认相应进程不在运行并取得该锁文件的清理授权再移除，不自动抢占。文件原子替换保护配置完整性，不是跨用户隔离或加密。

Python 等价接口：

```text
setup.py plan --state-dir PATH --roots ROOT ... --python PYTHON [--bindings BINDINGS.json]
setup.py --task-id TASK --write-root OUTPUT_ROOT --allow-operation output plan --state-dir PATH --roots ROOT ... --python PYTHON --output NEW_PLAN.local.json
setup.py --task-id TASK --write-root PATH --allow-operation setup apply --state-dir PATH --plan NEW_PLAN.local.json
setup.py status --state-dir PATH [--session-id ID]
```

Status 如需 `--output`，同样必须在子命令前传入 `output` 授权参数。其他原始资料源还须传 `--document-root`（PowerShell 为 `-DocumentRoot`）；默认 N 盘文档库始终保护。

Status 返回的 `capabilities` 是标准 doctor 报告；当前会话提供宿主和任务证据后，按 [来源与能力](sources-and-capabilities.md) 的证据接口继续，不把本地设置当作新访问权限。个人/项目记忆和反馈可分别使用同一状态目录下的 `memory/`、`feedback/` 子目录；本脚本不读取或创建它们。
