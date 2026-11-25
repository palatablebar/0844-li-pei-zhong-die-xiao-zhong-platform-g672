# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `claim_id` | text | 主键 |
| `member_id` | text | 业务字段 |
| `service_date` | date | 业务字段 |
| `payer` | text | 业务字段 |
| `billed_cents` | int | 业务字段 |
| `approved_cents` | int | 业务字段 |
| `deductible_cents` | int | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 抽检结构化字段

批次 payload 的 `group_payments` 按理赔组（同一 `member_id` + `service_date`）保留给付依据：

| 字段 | 类型 | 说明 |
|---|---|---|
| `group_key` | text | 理赔组键，`member_id|service_date` |
| `payers` | text[] | 组内出现的支付方（去重排序） |
| `claim_count` | int | 组内理赔笔数 |
| `payment_total` | int | 该批次内该组的给付总额（分） |
| `payments` | object[] | 各支付方逐笔的 `claim_id`、`payer` 与金额 |

抽检周期在 `group_payments` 之上计算：`highest_total`/`lowest_total` 为同组跨批次给付总额的最高与最低，`payment_gap` 为二者差额；差额大于零即触发强制入样。周期的 `selections[].evidence` 快照保存入样组在各批次的来源摘要（`source_sha256`、签发时间）与逐笔给付，名单发布后仍可核对。
