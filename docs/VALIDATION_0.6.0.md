# DF Agent 0.6.0 验证记录

本轮修改明确 Router/Advisor 与 df-mcp、DataLab 的分工，补齐 reader 包完整性和输入格式依赖检测。以下为当前源码在本机执行的合成与结构检查；历史版本的测试记录保持原样。

| 检查 | 结果 | 证明范围 |
|---|---|---|
| 完整 `unittest` 回归 | 132 项，131 通过、1 跳过 | 原有访问、配置、记忆、反馈、包装和检测功能的合成回归；跳过项不计通过 |
| 新增检测回归，含最后的两层 PowerShell 参数复验 | 15 项全部通过 | 核心/vendor 改动、缺失、未列运行代码、越界清单、缺清单、CSV/TSV/XLSX 依赖、跨格式证据拒绝和旧调用签名 |
| `skill-creator` 的 `quick_validate.py` | 通过 | 技能元数据和结构，不代表业务行为通过 |
| `tools/check_package.py` | 通过 | 0.6.0 清单一致、公共文件指纹、链接和发布边界；未发布或验证远端导入 |
| `git diff --check` | 通过 | 无补丁空白错误 |

执行环境为 Windows、本轮已确认的 Python 3.12；测试输入是临时生成的合成文件，不连接公司资料源。完整回归后补查根目录 PowerShell 包装器的 `InputFormat` 参数，并通过上述 15 项针对性复验。

4 项 Advisor 独立盲测已完成。评审使用 `fork_turns=none`，只读取技能、必要参考及原始 fixture，未读取 `evals/cases.json` 中的期待答案。以下均为合成行为验证，不能换算为真实业务准确率。

| 合成 fixture | 结果 | 实际观察 |
|---|---|---|
| `advisor_source_candidates.md` | 通过 | 澄清费用/付款口径及期间，不把 `not_checked` 当作来源可用 |
| `advisor_current_extraction.md` | 通过 | 保留 `EXTRACTION_UPDATE_REQUIRED`，不用旧 9,600 CNY 或旧 CSV 作为当前金额，不越过仅诊断范围 |
| `advisor_complete_technical_partial_business.md` | 通过 | 仅给出 500 CNY 的去重十月发生额小计，排除 Q3 的 2,400 CNY 和付款凭证重复，不宣称全月完整 |
| `advisor_native_needs_review.md` | 通过 | 保留 `checks_status=passed`、`status=needs_review`，1,500 CNY 与 100 USD 分列，不再轮询或猜测渠道别名 |

测试中的工具结果 fixture 已是给定观测，无需真实重载工具；引用单项已有数值无需调用 DataLab，多行计算仍交给 DataLab。两份 fixture 的用户题意可进一步补完整；本次执行未因这些歧义越权，本记录不将它们认定为技能缺陷。

本轮没有验证同事电脑安装、实际业务库完整性、DF Agent 与新版 df-mcp 的生产联合运行、真实费用总额或业务改善，也没有改写已安装技能和既有资料。来源目录与证据包装是 df-mcp 的可选新能力，旧版本仍使用其已确认配置和原生结果；来源目录可列出不等于源已连接，技术检查通过不等于业务完整。


## 2026-11-23：SkillHub 完整包

新增 `--skill-package` 输出唯一根级 `SKILL.md` 及全部 19 个入口资源。插件与独立 Skill 共用源码；目录保护按实际包布局识别，设置、记忆、反馈和运行文件仍须位于已授权的包外目录。

新增两项真实归档解压测试：独立 Skill 与原插件布局均能导入脚本、使用包外合成记忆、拒绝包内状态写入，并保持包内全部文件哈希不变。连同原有回归共 134 项，按整组及失败项单独复验汇总，133 通过、1 条件跳过。SkillHub 匿名 SKILL.md 格式校验通过；未向 SkillHub 上传草稿或代用户提交审核。

本机 OneDrive 中的测试解释器带有重解析属性，PowerShell 路径保护正确拒绝；最终使用逐文件哈希一致的普通本地源码副本及本地 Python 复验。一次 Git 临时仓库初始化错误在独立复验中未复现；未改测试断言或放宽路径保护。远端完整结果以对应提交的 CI 为准。
