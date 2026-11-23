# 合成输入：DataLab 原始结果

当前 CSV 本体可读，源定位为 `synthetic:channels.csv` 第 2–4 行，版本 `synthetic-v1`。用户已确认按渠道计算收入，跨币种分列，不做币种转换。

DataLab 命令已经完成并生成报告，原始结果：

```json
{
  "validation": {
    "checks_status": "passed",
    "status": "needs_review"
  },
  "result_tables": [
    {"channel": "direct", "currency": "CNY", "revenue": 1500},
    {"channel": "partner", "currency": "USD", "revenue": 100}
  ],
  "limitations": ["两条渠道别名可能属于同一渠道，需业务确认映射。"]
}
```

尚未收到对渠道映射的确认。
