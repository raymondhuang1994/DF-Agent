# 合成输入：本机来源目录

以下为合成观测摘要，不含真实路径。当前会话没有确认资料来源；用户仅说“查上个月的活动费用”。

`df-source-catalog/1` 返回两个既有 profile：

| profile_id | provider | source | 说明 |
|---|---|---|---|
| campaign-costs | local | synthetic:campaign-costs | 活动费用登记 |
| campaign-payments | local | synthetic:campaign-payments | 活动付款登记 |

每项均有独立 `catalog_source_id` 和 `config_fingerprint`；`source_availability` 为 `not_checked`，`sources_checked=false`，`business_completeness=not_established`。没有连接或读取业务文件。旧入口文档出现过另一个默认路径，但本轮未确认它。
