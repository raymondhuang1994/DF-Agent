# 来源选择与能力证据

## 固定本轮使用的来源

选择顺序：用户本轮明确且可访问的来源 → 团队已确认的本机绑定 → 当前宿主唯一且符合目录条目的候选。仅凭同名或修改时间不能判定同一版本/最新版。仍有多个候选时，保留候选信息并询问必要的来源选择；不混用一份指令和另一份脚本。

`native_skill` 表示当前宿主目录已实际显示这个来源，执行者再读取其完整指令与资源。仅从用户指定文件夹读到技能，记为 `explicit_file_playbook`；可在获准诊断中验证流程，但不能把它写成原生发现通过。正式采用文件流程模式需要明确试点决定。

使用真实 Skill 目录解析所有相对资源。确认必需公共资源留在获准根目录内，不跟随链接扩大范围。记录版本；没有可靠版本时写未知，并用 SHA-256 固定此次 `SKILL.md` 与已使用的公共资源。不要遍历私库、环境密钥或业务资料来补指纹。

本机根目录绑定、完整日志留在独立本地测试位置。共享报告使用 `ROOT_1/data-lab/SKILL.md` 一类别名，不写入用户名、业务正文或凭据。宿主、执行模式、权限、配置或来源指纹改变时，只重验受影响的能力。

## 五层报告

项目报告的 `schema_version` 为 `team-advisor-capabilities/1`。一条记录针对一个 `skill_id`、`source_ref`、`access_mode` 与 `task_profile`。首批任务 ID 为 `data-lab.sum_table`、`data-lab.chart`、`data-lab.model`、`data-lab.word`、`df-mcp.lookup`、`etf-comment-drafts-v2.draft`。汇总通过不能代表模型、Word 或动态图表通过。

| 检查 | 可接受证据 | 尚不能证明 |
|---|---|---|
| `filesystem` | 明确根目录下的文件存在，元数据可解析 | 宿主已发现 |
| `host_discovery` | 当前会话实际技能目录显示所选来源 | 脚本能运行 |
| `resource_access` | 完整技能与本任务必要公共资源实际可读 | 运行依赖齐全 |
| `dependencies` | 本任务解释器、库或真实工具/连接的检查结果 | 业务结果正确 |
| `smoke_test` | 实际运行合成任务并核对结果 | 其他任务或机器通过 |

状态仅用 `passed`、`failed`、`not_checked`、`not_applicable`、`unknown`。每项保留证据摘要；`not_applicable` 必须有任务相关理由。宿主没有提供完整目录时是未知，不能据此宣称未安装。

`execution_ready`：必要检查与实际烟雾测试通过为 `true`；已证实的必要阻断为 `false`；尚未检查、来源歧义或证据不足且无已知阻断为 `null`。原生模式还要求 `host_discovery=passed`。将确认的必要阻断写入 `blockers`，模拟、覆盖范围和歧义写入 `limitations`。保留 `tested_at`/`checked_at` 的实际带时区时间，不借用另一会话的通过状态。

## 使用检测器

[入口检测器](../scripts/doctor.py) 位于本 Skill 的 `scripts/doctor.py`，不依赖源码项目外的包装脚本。它接收显式路径，不运行专业技能的业务脚本，不初始化 reader。PowerShell 示例中的变量均应先设为当前实际获准路径：

```powershell
& $chosenPython -X utf8 -B $doctorPy scan --roots $approvedSkillRoots --output $newReportPath --python $chosenPython
```

`scan` 可附 `--host-evidence` 或 `--bindings`。宿主证据必须来自当前会话实际观察，绑定必须是已确认的来源选择。使用 `validate` 检查报告，使用 `merge-evidence` 合并实际测试证据前先查看该版本 `--help` 及输入格式；合并只记录已经发生的测试，不执行测试。不能因文件扫描成功而伪造宿主发现。省略解释器或宿主证据时保留未测状态；输出报告不授予权限。

检测器负责文件/解释器层事实；专业依赖、工具状态和真实结果在对应会话按任务补充。不要把结构检查器、手工构造报告或测试桩当成业务执行证据。

插件清单与 marketplace 随版本 0.4.0 提供。文件存在、JSON 可解析和本地检查通过均不证明 GitHub 导入或成员安装成功。首次绑定与后续变化检查见 [首次设置](setup.md)。
