# 三段合成集成验收

日期：2026-11-16。已实际运行本机 reader → DataLab → ETF 公共选例与三条草稿交接。结论仅适用于 **真实程序处理合成 local 来源**，不代表公司资料库、网络盘、VPN、SharePoint 或同事账户已经验收。

## 范围与执行方式

- 来源仅为项目 `evals/fixtures/` 的 `product.md`、`products.csv`、`fund_flows.csv`、`synthetic_corpus.md` 四份合成文件，复制到独立测试树的 `synthetic-reader/source/`。
- 索引基目录为同级 `synthetic-reader/state/`；`df-init plan` 实际生成其下独立 profile 与 state，核对 provider、root、config 和 state 均在批准树内后才 apply。
- plan、日志、派生表和结果都在 source 外。没有读取现有用户 profile、执行默认来源 probe、访问私库或调用网络资料。
- 使用独立项目 Python 环境。已安装技能仅作为读取/执行来源，没有覆盖原安装。操作隔离来自固定来源、独立状态与程序边界；当前宿主未提供 OS 级只读沙箱，不声称已获得强制进程隔离。

## 实际结果

| 阶段 | 实际动作 | 结果 |
|---|---|---|
| Reader 0.6.2 | plan → apply → status，查询同一最新 job | `local`，job `complete`，4/4 文件索引完成，`network_calls=false` |
| 全集与读取 | `list --paginate`，逐文件 inspect、固定 expected_version read | 清单恰好等于四文件白名单；完整读取 4、12、4、24 个 segment |
| 数据交接 | 四文件 export；检查返回文件处于独立 state 中并实际读取 JSONL | 四份导出均可读，记录导出哈希与版本；源文件前后哈希不变 |
| DataLab 0.3.0 | 从 reader 结构化导出重建三行 CSV，派生净流入后 `analyze --agg sum --group product_id --no-charts` | 实际 by_group 和总体数值与独立 Decimal 复算一致；自动检查 `passed` |
| ETF v2 | 读取本机 Skill/公共 reference，以显式 `--library` 指向入口公共合成例，再由 agent 草拟并核对 | 选择器实际返回 4 条 unrated 合成参考；交付恰好 3 条内部模拟评论，未读取私库 |

DataLab 原生 `validation.status` 保持 `needs_review`；其自动检查覆盖总体与分组复算、来源与结构化数值声明，不因此宣布所有自由叙述、图表、模型或 Word 已验收。本次没有要求图表。

## 计算与证据

口径由合成材料明确给定：`net_inflow = creation_amount - redemption_amount`，期间 2026-10，单位 CNY 元。派生使用 reader 导出中的 `segment.data.cells`，不以搜索摘要或原文件绕过交接。

| 产品 | 申购 | 赎回 | 实际净流入 | Reader 定位 |
|---|---:|---:|---:|---|
| SYN-A | 1,200 | 300 | 900 | fund_flows.csv，data，A2:G2 |
| SYN-B | 800 | 950 | -150 | fund_flows.csv，data，A3:G3 |
| SYN-C | 500 | 200 | 300 | fund_flows.csv，data，A4:G4 |
| 合计 | 2,500 | 1,450 | 1,050 | DataLab `metric.value`；各产品在 `by_group` |

负值被保留。三条草稿分别核对了 A 的净额、B 的净流出以及合计/C 的贡献，没有将申购额或资金流写成收益。文本保留内部模拟属性，未发布。

Reader inspect/read/export 使用的 `source_version` 与下列源文件 SHA-256 一致：

| 文件 | SHA-256 |
|---|---|
| product.md | `f9c9988d7b928fae1b6d0720aa59745752e1912aec42077cf6649a29fcfcd1db` |
| products.csv | `1e8ee31c5c3dfbe2df123efaa1e9b1ca9183b17ba39ae976608117b99906d936` |
| fund_flows.csv | `b1d9f59aa3b8b967a8abf8f17529a128ea25a4decea3ff6ce6f587187a5639c6` |
| synthetic_corpus.md | `d535904c50cb4165dd84d01cb1307e9a2ca1ab8583ceef70f17c3bf4cc177d60` |

本地完整证据在独立测试根 `synthetic-reader/`，不随发布包分发：

- `plan.json`、`logs/apply.json`、`logs/status.json`、`logs/job_status.json`、`logs/list.json`。
- `logs/inspect-*.json`、`logs/read-*.json`、`logs/export-*.json` 与各次参数/命令记录。
- `reader-evidence.json`：版本、覆盖、源及导出指纹与可读路径。
- `derived/derivation.json`、`derived/fund_flows_from_export.csv`：导出→派生过程和定位。
- `analysis/net-flows-001/result.json`、`checks.json`、`tables/by_group.csv`、审计记录；`analysis-verification.json` 单独核对实际结果。
- `logs/etf-public-selection.json`、`etf-handoff.json`、`comments.md`、`comment-review.json`、`final-evidence.json`。

## 复现与边界

`tools/test_synthetic_integration.py` 的路径均由参数提供，不写死用户名。运行 `--help` 查看参数；对新测试目录执行完整流程，必要时用 `--reader-only` 停在 reader 阶段。`--resume` 仅用于同一已准备测试树，会核对四文件仍与项目 fixture 完全一致，并复用已有成功证据，不重新跑已完成步骤。

脚本复现真实工具调用、计算和公共选例，并生成草稿交接。评论由读取专业流程的 agent 生成及核对；脚本不是语言模型或通用 Skill 调用接口，不宣称能够独立重现自然语言措辞。

合成 corpus 中还提及 `channels.csv`，它不在本次批准的四文件名单内，因此未复制或读取；本次完整覆盖结论只针对明确的四文件测试树。真实业务全集仍需另外定义和验证。

Reader 使用既有按需 broker 和原本的 60 秒空闲退出机制；没有新增常驻服务或终止其他连接。合成 local provider 的通过不能推广为远程资料可达、公司权限、真实检索质量或所有成员可用。
