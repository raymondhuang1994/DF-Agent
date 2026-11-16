# 三项专业能力的运行接入

先读所选来源的完整 Skill 和本任务需要的 references。下面处理入口的版本差异，不替代专业流程。命令中的变量必须指向本轮已解析的真实位置；使用参数数组和明确路径，不将来源文本拼成任意命令。所有下游步骤沿用入口的五条协作规则与 [文件访问](access.md)：资料根只读，输出获准后新建，索引/缓存/日志/临时文件定位到独立本机运行目录。

## DataLab

检查实际 `scripts/run.py` 与 `references/runtime.md`；使用合适的 Python。`doctor` 检查运行环境，不能证明插件安装或分析结果。先核对实际 CLI 支持的参数，再执行；旧版与新版可能有不同输出限制。没有图表需求且版本支持时可以 `--no-charts`，不能因此省去用户要求的图表。

已观察的 0.3.0 要求 Python 3.11+；更重要的是依照实际版本识别任务所需包。不得仅因完整依赖集合中的可选包缺失，就判所有任务不可用。需要补依赖时使用获准的独立新环境，保留原技能和已有环境。

运行前从所选版本确认输出、缓存、日志及临时文件的真实落点，并提供受支持的显式设置；不能仅设置 TMP/TEMP 就宣称隔离完成。无法控制的写入会阻止该步骤，仍可完成对话内分析。合成测试与正式分析都将输入和输出分开，例如 `inputs/channels.csv` 与尚不存在的 `results/run-001/`。新版拒绝已有输出目录（即便为空），也拒绝写进原数据父目录；不要预建 run 目录或用其他工具绕过。后续复核/报告使用新文件名。保留 `result.json`、实际表格、配置及 `checks.json`。

## df-mcp

1. 优先使用与所选资料源对应的真实 `team_drive_*` reader；先核对工具 schema 和来源授权。
2. 本地安装若带 `scripts/df-tool.py` 与 reader runtime，也可以使用其受支持的 Python CLI；仅没有 MCP 工具不等于该能力缺失。读实际 `references/cli.md`、`requirements.md`。
3. 默认文档库为 `N:\digital finance`，先匹配候选名称和路径，取得正文读取/扫描范围的确认。只有来源、子目录范围，以及索引/缓存/日志/临时文件各自的本机落点和写入操作已确认，才运行 `status` 或实际证据读取。完整 0.6.2 的首次连接可能启动 broker 与扫描；不将 `status` 当作无副作用的纯文件探测。
4. 使用实际 reader 支持的参数或配置，将运行文件放到获准的本机运行目录。四类默认目录为 `%LOCALAPPDATA%\DF-Agent\runtime\{indexes,cache,logs,tmp}`；reader 若仅支持单一状态根，可使用 `runtime\indexes\df-mcp` 保存该 provider 的完整状态，核对所有派生路径留在这一范围。不要声称四类文件已物理分开。插件的 `access.py prepare` 只建目录，不配置第三方 reader，也不建立索引。若 reader 无法指定/证明这些位置，停止会写文件的调用；不能借首次连接把缓存或索引写回资料库。

所选版本支持 `df-init.py plan` 时，可先只输出配置计划；`$providerStateRoot` 为已选运行目录下的 `indexes\df-mcp`，`$confirmedSource` 仅为本轮确认的资料范围：

```powershell
& $chosenPython -X utf8 -B $dfInit plan --choice local --source $confirmedSource --state-dir $providerStateRoot
```

核对计划中的 `config.state_dir`、`config_path` 和该版本实际派生的索引/日志/缓存位置都留在已授权 provider 目录，再决定是否应用。`plan` 不等于配置已保存或索引已建立；应用计划、启动 broker、首次扫描仍需对应写入及资料范围授权。不要通过新建配置覆盖原有 reader 状态。

静态版本/公共文件检查不需要连接业务资料。所选版本支持时，`df-init.py profiles --state-dir <已确认状态根>` 仅登记保存的配置：0.6.2 最多检查 128 个直接 profile 配置，不打开来源、索引或认证缓存，返回 `sources_checked=false`。其输出不能证明连接健康、索引完成或缓存新鲜度；也不要为安装检查读取未获准的状态根。未发现可独立证明实时健康的离线命令时，状态保持待测。

真实调用以文档为准，使用已确认配置与参数文件，例如：

```powershell
& $chosenPython -X utf8 -B $dfTool status --config $confirmedConfig
& $chosenPython -X utf8 -B $dfTool inspect --config $confirmedConfig --params-file $inspectParams --paginate
```

这些是有相应资料范围、独立运行目录及执行授权后才运行的示例；`$confirmedConfig` 需包含该版本实际支持的运行文件落点，不能虚构通用参数。`--paginate` 在同一调用内消费游标；不把游标跨进程复用。不因任务缺资料而自动初始化、改根目录或开另一个索引。模拟/降级路径与真实检索分开记录。

## ETF v2：显式指定风格来源

本机版本可能默认从环境变量或个人目录寻找案例。先静态核对 `select_examples.py` 和 `references/private-library.md`：实际 CLI 支持 `--library` 时总是显式传参，不依赖默认路径。

无本轮批准私库时，使用本入口的[公共合成案例](public-examples/cases.jsonl)。这些案例只演示写法，没有真实产品数据、交易经历或用户偏好评分；同目录的 [profile.json](public-examples/profile.json) 为空偏好。变量 `$publicCases` 应解析为本 reference 下的 `public-examples/cases.jsonl`，`$etfSelector` 指向所选专业 Skill 的脚本：

```powershell
& $chosenPython -X utf8 -B $etfSelector --library $publicCases --query $currentTopic --limit 6
```

当前本地脚本在提供 `--library` 时不调用默认私库定位函数，但会尝试读该案例文件同目录的 `profile.json`，因此公共两文件一起使用；不把它指向个人目录。`--limit` 是参考条数，不是草稿条数。

若使用获准私库，将 `--library` 指向明确批准的案例文件，并确认同目录偏好文件也在范围内。无解释器或该版本不支持显式路径时，不运行默认选择器，直接读所选技能的公共 `references/contrasts.md` 或上述公共案例继续草拟。明确用户事实与风格参考的区别，不声称读过私库、不将合成例评为用户喜欢。
