# 质量与明确反馈

仅在“产品资料 → 评论草稿”或“资金流数据 → 指标解释”流程需要验收、继续修改或复用反馈时读取本页。质量检查和用户采用是两件事：程序检查通过不代表用户满意，用户采用也不能抹去未核实事实。

## 产品资料 → 评论草稿

以本轮资料确认产品身份、用途、日期、费率等必要事实，并保留页码或段落定位。风格例提供写法，不能提供当前产品事实。按用户数量、语言、平台与长度交付，不因为例库较大而增加条数。

交付前核对：每个可验证事实是否有当前来源；是否混入旧案例数字或虚构持有经历；承诺、比较与适用条件是否有证据；数量和明确表达偏好是否满足。事实不足时省去该断言或说明缺口，不用“已通过”覆盖局限。公共合成样例适合演示写法，不能证明真实产品优势。

## 资金流数据 → 指标解释

先沿用已确认的期间、币种、单位、产品范围和申赎符号。输入不足以区分申购、赎回和净流入时，明确缺口；不能凭记忆给缺失字段指定口径。通常净流入 = 申购 − 赎回，但以本项目已确认定义为准。跨币种不直接相加；缺失值不默认为零；重复记录与撤单处理必须有依据。

按产品汇总后复算总额和分项勾稽，并保留源表范围、过滤条件、版本及原工具状态。解释需区分金额变化、份额变化和资产价格变化，不能仅凭净流入推断投资者获利或市场因果。最终先给用户所需指标，再说明解释与覆盖缺口。

## 什么值得记下来

用户明确说“采用”、给出具体修改或拒绝并说明原因后，按已批准的个人/项目范围记录选定反馈。已有保存授权足够时直接记录；没有持久化范围时不默认收集对话。沉默、任务结束、助手自评或自动检查不能填作用户采用。记录简短的用户反馈、修改原因、产物与来源引用/哈希，不复制整段聊天或整份文件。

`accepted` 表示该次版本被明确采用；`revised` 表示用户要求修改，是否采用修改后的版本应另有反馈；`rejected` 表示明确拒绝。`criteria` 记录已观察到的检查，不虚构未执行的检查。`revision_minutes` 只有实际测量或用户提供时才填。反馈统计的分母是所选明确反馈，不能称作所有任务的采用率，也不能证明记忆造成质量提升。

## 本地反馈 CLI

调用 `scripts/feedback.py`，Python 3.11+，无额外包。状态目录和候选导出均放在插件及发布仓库外；使用已绑定的解释器和本轮批准的状态目录。命令示意中的 `python` 替换为实际已验证的解释器。

```powershell
python scripts/feedback.py --store '<反馈目录>' init
python scripts/feedback.py --store '<反馈目录>' record --input '<选定反馈.json>' --explicit-feedback
python scripts/feedback.py --store '<反馈目录>' summary --scope project --owner '<本人标识>' --project '<项目标识>'
python scripts/feedback.py --store '<反馈目录>' list --scope personal --owner '<本人标识>'
python scripts/feedback.py --store '<反馈目录>' suggest --scope project --owner '<本人标识>' --project '<项目标识>' --id 'feedback-001' --key 'flow-definition' --output '<全新候选.json>'
python scripts/feedback.py --store '<反馈目录>' delete --scope project --owner '<本人标识>' --project '<项目标识>' --id 'feedback-001' --confirm
```

`--explicit-feedback` 声明已有明确的用户反馈，不是由程序证明授权。范围标签用于准确检索，并非登录认证或操作系统隔离。本人和项目标识的首尾空白会统一去除，与记忆模块保持相同范围；记录按实际时间先后排序，支持不同时区。`status` 只返回状态和版本，不返回其他人的记录。

记录 JSON 必须包含以下字段；示例为合成资料，不代表已发生真实业务反馈。`sha256` 是实际产物/来源的完整哈希，未知时不能填假值；缺少产物哈希时先计算已批准文件的哈希，再记录。脚本只保存这些引用，不打开引用文件。

```json
{
  "id": "feedback-001",
  "scope": "project",
  "owner": "synthetic-person",
  "project": "synthetic-project",
  "workflow": "fund_flows",
  "task_id": "task-01",
  "run_id": "run-01",
  "outcome": "revised",
  "user_feedback": "把净额和交易总额分开。",
  "reason": "上稿混淆净流入与交易总额。",
  "correction": "本项目将申购、赎回和净流入分列，净流入等于申购减赎回。",
  "observed_at": "2026-11-16T01:00:00Z",
  "artifact_refs": [{"uri": "synthetic:report", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "locator": "table 1"}],
  "source_refs": [{"uri": "synthetic:input", "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "locator": "rows 2-8"}],
  "criteria": [{"name": "calculation", "status": "failed", "evidence": "上稿把交易总额标为净流入。"}],
  "revision_minutes": 4
}
```

`workflow` 仅支持 `product_comments`、`fund_flows`。`scope` 为 `personal` 时不得填写 `project`，为 `project` 时必须填写。`id` 是 1–50 位 ASCII 字母、数字、点、下划线或连字符，首位为字母或数字。`source_refs` 可为空，但应在检查和交付中明确无来源的限制。`criteria` 是 `name/status/evidence` 数组；状态仅为 `passed/failed/not_checked`。

可选的 `selected_excerpt` 保存用户明确采用的短例，`correction` 保存明确修改；两者限 4,000 字符，不用于保存全文。`suggest` 只从明确修改，或 `accepted` 记录中的选定短例生成候选。它输出兼容 [记忆流程](memory.md) 的 JSON，带来源、原反馈哈希和 `feedback_ids`，不导入、不发布、不扩大范围。事实类候选应在后续审核时设置正确类型和失效时间，旧示例中的数字不可直接复用为当前事实。

反馈记录采用唯一 ID；重跑或后续采用使用新 ID，不覆盖历史反馈。保存通过独占锁文件和原子替换保护；正常写进程结束会释放锁。崩溃可能留下锁文件：查看所选反馈目录中 `.feedback.lock` 记录的进程 ID，确认该写进程已不存在后，只清理这个已确认失效的锁再重试；不自动删除未知或仍有效的锁。删除会从当前反馈文件移除内容并保留不可复用 ID，返回关联记忆 ID；候选导出、已发布记忆、源产物和外部备份需分别处理，不能声称已全部删除。

## 判断价值需要真实对照

试点记录实际修改时间、明确反馈、事实错误和覆盖缺口。比较记忆开启/关闭时使用同一模型、技能和资料，预先固定判断标准，用后续未见任务评价；不能把期待答案写进记忆。先报告合成技术验收和样本量，再报告真实业务改善；没有真实试点就保持后者未验证。
