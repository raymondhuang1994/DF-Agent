# DataLab 本地合成验收记录

测试日期：2026-11-16。环境：当前 Windows 桌面会话、PowerShell、AMD64。范围为实际本地 `data-lab` 0.3.0 的无图渠道汇总；没有读取业务数据、真实 df-mcp 来源或私有风格库。

## 结果

`data-lab.sum_table` 已实际运行通过。以 `channels.csv` 的五条记录按 `channel` 对 `revenue` 求和，明确使用人民币元：

| 渠道 | 记录数 | 收入（CNY 元） |
|---|---:|---:|
| direct | 2 | 175 |
| partner | 2 | 75 |
| other | 1 | 0 |
| 合计 | 5 | 250 |

`result.json`、`tables/by_group.csv` 与标准库 `csv`/`Decimal` 独立复算一致；`metric_definition` 和分组表格式均保留 `unit=currency`、`currency=CNY`。CLI 实际摘要为 `revenue（sum）＝CNY 250.00。`；`charts=[]` 符合本次无图要求。

- 自动检查共 33 项，`checks_status=passed`。
- 整体状态保留 `status=needs_review`，不改写为自动业务批准。
- 来源校验通过；总数、分组与周期分别独立复算。
- 两条结构化数值声明通过。
- 计算覆盖仍为 `partial`：通用画像、数值描述表及样本排除原因明细未全部独立重算。
- 自由叙述、业务解释、因果语言和视觉版式的自动覆盖为 `not_checked`。

## 实际运行环境

优先检查过已有解释器后，在独立任务目录新建 Python 3.12.14 虚拟环境，保留应用和系统原有环境。环境由本地 Skill 的 `scripts/bootstrap.py` 按其 `scripts/requirements.txt` 安装；没有复制或修改专业 Skill 的源文件。

| 依赖 | 测试版本 |
|---|---|
| pandas | 2.3.3 |
| numpy | 2.5.5 |
| matplotlib | 3.11.2 |
| openpyxl | 3.1.5 |
| python-docx | 1.2.0 |
| scipy | 1.18.1 |
| scikit-learn | 1.9.1 |
| tzdata | 2026.6 |
| PyYAML（技能验证的开发依赖） | 6.0.3 |

完整固定版本见 `tools/runtime_requirements.txt`，只含包名与版本，不含本机路径或凭据。PyYAML 是另加的开发依赖，不属于 DataLab 核心需求。安装完成后 `pip check` 退出 0，结果为 `No broken requirements found.`。

bootstrap 内部实际执行了 `doctor`：Python 版本受支持，核心包全部实际导入成功，时区库可用，`ready=true`，`import_errors={}`。可选 `pyarrow` 与 `plotly` 未安装；PATH 上未发现 LibreOffice 的 `soffice`。`doctor` 的建模、Word 等能力标志只表示运行时前置条件，不构成对应业务验收。

## 命令与目录约定

以下为已执行命令的路径别名形式。由当前会话检测结果填入 `$BasePython`、`$SkillRoot`、`$NewVenv`、`$Python` 与 `$ValidationRoot`；不依赖特定用户名。`$Python` 指新环境的 `Scripts/python.exe`。原始日志与结果留在本机独立验收树中。

```text
VALIDATION_ROOT/
  inputs/channels.csv
  inputs/product.md
  logs/analyze-help.txt
  logs/bootstrap-doctor.json
  logs/analyze-stdout.json
  logs/skill-source-before.json
  logs/smoke-summary.json
  logs/fixture-sanity.json
  verify_smoke.py
  results/sum-table-001/        # 由 analyze 创建；执行前不存在
    result.json
    checks.json
    report.html
    config.json
    tables/
    audit/
```

创建环境及额外开发依赖：

```powershell
& $BasePython -B (Join-Path $SkillRoot 'scripts/bootstrap.py') --venv $NewVenv
& $Python -B -m pip --isolated --require-virtualenv install --no-cache-dir --disable-pip-version-check PyYAML
& $Python -B -m pip freeze
& $Python -B -m pip check
```

上述 bootstrap 自带的 doctor 已通过，末尾 JSON 输出忠实记录在 `logs/bootstrap-doctor.json`；没有为相同环境重复运行 doctor。随后实际验证版本和 CLI 参数，再执行一次无图分析：

```powershell
& $Python -B (Join-Path $SkillRoot 'scripts/run.py') --version
& $Python -B (Join-Path $SkillRoot 'scripts/run.py') analyze --help
& $Python -B (Join-Path $SkillRoot 'scripts/run.py') analyze --input (Join-Path $ValidationRoot 'inputs/channels.csv') --metric revenue --group channel --date date --agg sum --unit currency --currency CNY --no-charts --out (Join-Path $ValidationRoot 'results/sum-table-001')
& $Python -B (Join-Path $ValidationRoot 'verify_smoke.py') --root $ValidationRoot --skill-root $SkillRoot
```

以上命令均退出 0。`analyze` 在本次执行中已调用独立验证器并生成 `checks.json`，没有对同一未修改结果另行重复调用 `validate` CLI。额外标准库检查重新读取合成 CSV，对账总数与分组，并检查单位、来源哈希、结果状态、空图表列表与源文件稳定性；其作用范围不包括视觉验收。

## 来源和文件保护证据

`channels.csv` 从交接基线逐字节复制，SHA-256 为：

```text
c3958fa59fd9f803455b9ef9701728ce0f3180073b7695802ab6a51190c70ca9
```

`result.json` 的来源哈希与原 CSV 一致。DataLab 文件审计为 `completed`，登记的原始输入状态为 `unchanged`，记录八个新产物。冒烟测试前后对选定的 12 个 Skill 指令、脚本及引用文件复核 SHA-256，均未变化。该项只说明所列文件，没有声称覆盖整个本地技能目录。

文件审计明确为 `protection=software_guards`、`os_read_only_enforced=false`。这不是操作系统级只读隔离证明。原始审计与结果可能含本机路径，留在本机；共享仓库只保留本去标识摘要及合成素材。

## 后续组合测试素材

`evals/fixtures/` 已提供：

- `channels.csv`、`product.md`：保留交接包原始合成附件。
- `products.csv`：三只虚构产品的完整合成名单及可比年度总费用率。
- `fund_flows.csv`：三只虚构产品的 2026-10 月度申购、赎回金额，单位 CNY 元。
- `synthetic_corpus.md`：明确合成全集、费用单位、净流入定义及来源定位约定。

素材独立算术检查通过：合成费用表各行分项之和等于总费用率，SYN-A 与 SYN-C 以 0.25% 并列最低；净流入为 SYN-A 900、SYN-B -150、SYN-C 300 元，总计 1,050 元。这些是合成素材的完整性检查，没有运行真实检索，也没有作为三技能集成通过记录。

## 未验收范围

图表、统计模型、Word、看板、真实 df-mcp 检索、跨技能真实数据传递、入口原生发现/安装、其他成员电脑及组织分发均不由本记录证明。此处仅确认当前机器所选 Skill 与独立 Python 环境下的无图合成渠道汇总能力。
