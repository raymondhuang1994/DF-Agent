# DF Agent 本机能力检测与证据合并

检测器只读取明确技能根目录的一层子目录、`SKILL.md` 和代码中列出的公共资源。每根最多 256 个直接条目、每文件最多 2 MB、最多 16 个根；超过限制会保留覆盖缺口。不会递归搜索、跟随符号链接或 Windows 重解析点、查找私库、读取凭据、运行专业技能脚本、连接资料库或修复环境。

需要已有 Python 3.11+，检测器本身只用标准库。`-PythonPath` 是用于依赖检测的实际解释器；省略时 PowerShell 枚举 PATH 中全部匹配的 Python，先过滤 Windows Store 应用别名，再选择已有解释器，找不到就报告缺项。程序不会下载安装解释器。依赖探测只读取包元数据，不导入第三方库；实际加载和功能由烟雾测试确认。

## 采集

以下变量由调用者填写，根目录与输出目录必须来自本次任务允许的范围：

```powershell
& ./scripts/doctor.ps1 -Roots $ApprovedSkillRoots -OutputPath $NewReportPath -PythonPath $TaskPython -EnvironmentPath $ObservedEnvironmentJson -SessionId 'local-pilot-session-01'
```

仅安装入口插件时，使用插件内 `skills/df-agent/scripts/doctor.ps1`，无需仓库根包装器。多个根在 PowerShell 中传入字符串数组。脚本用参数数组传递路径，不使用命令字符串求值；中文、空格和通配符字符按字面路径处理。输出必须位于技能根之外，且文件名未存在；每次生成新报告，保留上一份。

Python 等价入口：

```text
python -X utf8 -B plugins/df-agent/skills/df-agent/scripts/doctor.py scan --roots ROOT_PATH_1 ROOT_PATH_2 --output NEW_REPORT_PATH --python TASK_PYTHON --environment OBSERVED_ENVIRONMENT_JSON --session-id local-pilot-session-01
```

`config/environment.example.json` 是当前会话观察的字段模板，未知值保持 `unknown`。实际执行环境和本次文件访问由检测器填写。`--session-id` 由验收者为本轮会话设置，换电脑、会话或权限范围时更换；默认 `unspecified` 只允许静态报告，不能合入宿主/任务通过结论。

`ROOT_1`、`ROOT_2` 依照去重后的根参数顺序产生。报告中只有别名和相对位置；实际根路径由调用者在仓库外记录。`--bindings` / `-BindingsPath` 接收 `config/bindings.example.json` 的结构；绑定是选择输入，检测器不会创建或修改用户安装。无显式绑定时优先唯一的宿主已观察来源，其次标记唯一候选；多份来源未解决时 `execution_ready` 保持未知。目录名不同但 `name` 相同的副本会被分别记录，不按文件修改时间选版本。

报告将已确认绑定保存在 `source_bindings.preferred_sources`。`merge-evidence` 省略 `--bindings` 时沿用该绑定，不会改选另一个自动发现的副本；显式提供新绑定才改变选择，并在 `binding_history` 记录时间及前后映射。显式空映射表示取消绑定。重新执行全新的 `scan` 没有旧报告输入，应继续提供已确认的绑定文件。

## 报告含义

为兼容已有报告，内部 schema 标识继续使用 `team-advisor-capabilities/1`（产品显示名为 DF Agent；见 [改名与兼容说明](RENAME_0.4.0.md)）。核心检查项为：文件、宿主发现、资源、依赖、烟雾测试五层，各为 `passed` / `failed` / `not_checked` / `not_applicable` / `unknown`。只有完整必要检查通过，具体任务才为 `execution_ready=true`。`false` 表示已观察的必要条件失败；没有证据时为 `null`。本脚本不会自行把 `host_discovery` 或 `smoke_test` 设为通过。

当前任务范围：

| task_profile | 检测范围 |
|---|---|
| `data-lab.sum_table` | CSV 无图汇总所需公共资源、pandas/numpy/tzdata |
| `data-lab.chart` | 图表资源、数值库和 matplotlib |
| `data-lab.model` | 建模资源、数值库、scipy/scikit-learn |
| `data-lab.word` | Word 资源、数值库和 python-docx；PDF/视觉检查另验 |
| `df-mcp.lookup` | 资料流程的公共资源；真实 reader/来源依赖仍待验证 |
| `etf-comment-drafts-v2.draft` | 公共参考草稿，不要求 Python 或私库；选例器为可选路径 |

Python 包版本与安装 Skill 的公开 `requirements.txt` 比较；可解析数字版本范围之外的约束（如 `~=`、markers、extras、直接 URL）保持未知，不回退到默认范围判定通过。同一包的重复约束合并检查。`-r` / `-c` 引用不自动跟随，其约束保持待核验。报告不回显可能携带令牌的未知约束全文。缺少 matplotlib 不使 CSV 汇总失败。包元数据通过不证明二进制可加载。ETF 草稿的依赖可标记有理由的 `not_applicable`，其他必要检查不能用这一状态跳过。

项目扩展字段 `source_selection` 保存来源选择，`coverage_limitations` 保存扫描缺口。`observation_context` 保存本轮 `session_id`、机器与显式根组合的不可逆 `scope_fingerprint`、解释器及其探测结果的 `runtime_fingerprint`。这些用于一致性核对，不是权限凭据、平台 API 或可信签名。

## 合入真实观察

先取得静态报告，再由当前会话观察者准备证据 JSON。直接复制报告的 `environment` 和 `observation_context`；为每个实测任务复制其完整 `source_fingerprint`，不能只复制 SKILL.md 哈希。示意结构：

```json
{
  "environment": {},
  "observation_context": {},
  "observed_at": "2026-11-16T09:00:00+08:00",
  "skills": [
    {
      "source_ref": "ROOT_1/data-lab/SKILL.md",
      "task_profile": "data-lab.sum_table",
      "source_fingerprint": {},
      "checks": {
        "host_discovery": {"status": "passed", "evidence": ["当前会话技能目录列出该来源；观察记录 HOST-01。"]},
        "smoke_test": {"status": "passed", "evidence": ["合成 CSV 汇总和单位核验通过；记录 SUM-01。"]}
      }
    }
  ]
}
```

空对象只是本页占位说明，实际证据必须复制报告内完整对象。证据只允许合入 `host_discovery`、`dependencies`、`smoke_test`，不能覆盖文件检测。真实依赖失败不能被外部“通过”标签覆盖。DF 的 `dependencies=passed` 需要获准来源上的实际 reader 状态证据；仅看到脚本或进程不够。文件流程另写 `access_mode: explicit_file_playbook`，不能因此把原生发现改为通过。

时间填写实际观察时间。合并为每个检查项保存 `observed_at`；默认采用证据批次时间，也可在检查项内明确更早的观察时间。已有检查只接受同刻相同状态或更晚的观察；较旧的通过不能覆盖较新的失败，同刻矛盾也会拒绝。不同检查项独立比较，因此首次烟雾测试可以早于静态报告或另一项宿主观察。检查时间不能晚于其证据批次，未来超过本机当前 UTC 60 秒的观察会拒绝。旧版已合入宿主/烟雾测试结果但缺少逐项时间的报告需重新观察；纯静态旧报告仍可合并。

```text
python -X utf8 -B plugins/df-agent/skills/df-agent/scripts/doctor.py merge-evidence --report REPORT_PATH --evidence OBSERVED_EVIDENCE_PATH --roots ROOT_PATH_1 --python TASK_PYTHON --output NEW_MERGED_REPORT_PATH
```

合并前会重新读显式根、公共资源和解释器元数据。来源、候选集合、范围、会话、环境或运行时不一致时拒绝沿用；应重新采集受影响的观察。`scan --host-evidence` / `-HostEvidencePath` 也支持同一契约，用于同轮、同范围、来源和依赖未变时的重复采集。准备证据不等于执行测试；工具只能检查一致性，不能证明观察者文字真实。

日志/证据只使用测试编号、别名和结果摘要。共享报告会拒绝个人绝对路径；不要放业务正文、私库案例、凭据或连接令牌。

```text
python -X utf8 -B plugins/df-agent/skills/df-agent/scripts/doctor.py validate --report REPORT_PATH
```

`validate` 仅检查结构和内部一致性，不重新访问来源。成功生成含失败项的检测报告退出码仍为 0；检测器自身出错退出码为 2。源文件保护来自参数边界、链接检查和新建输出约束，不宣称提供 OS 级沙箱或阻止其他进程并发修改文件。
