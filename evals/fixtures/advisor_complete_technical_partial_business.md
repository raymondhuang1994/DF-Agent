# 合成输入：活动登记和技术状态

用户已确认按 2026 年 10 月费用发生期统计，币种 CNY。当前选定范围是 `synthetic:campaign-ledger/2026`，不是全部付款目录。

这次已枚举完选定范围，`df-evidence-envelope/1` 中 `technical.request_succeeded=true`、`pagination_complete=true`、`extraction_complete=true`、`inventory_complete=true`，`business_completeness=not_established`。各原始文件均可读且提取版本当前。

| 文件和精确定位 | 文件夹 | 内容 |
|---|---|---|
| costs.xlsx / Sheet1!A2:D2，版本 synthetic-v1 | 11月付款 | 项目甲，10月服务，500 CNY |
| costs.xlsx / Sheet1!A3:D3，版本 synthetic-v1 | 10月付款 | 项目乙，Q3季度服务，2,400 CNY，未提供月度分摊 |
| costs.xlsx / Sheet1!A4:D4，版本 synthetic-v1 | 10月付款 | 项目甲，付款凭证，500 CNY，对应上面同一费用记录 |

资料负责人没有确认该登记表覆盖全部 10 月项目。没有其他业务数据。
