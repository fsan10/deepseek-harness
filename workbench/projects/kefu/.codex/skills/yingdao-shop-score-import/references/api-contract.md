# Import API contract

The project implementation in `app/api/import/route.ts` is authoritative.

## Endpoint

```text
POST /api/import
Authorization: Bearer <IMPORT_API_KEY>
Content-Type: application/json; charset=utf-8
```

## Body

```json
{
  "requestId": "tmall-20260714-shop-name",
  "dryRun": true,
  "records": [
    {
      "reportDate": "2026-07-14",
      "platform": "天猫",
      "shopName": "configured exact shop name",
      "shopKind": "own",
      "metricName": "宝贝质量",
      "metricCategory": "体验分",
      "unit": "分",
      "value": 4.97,
      "note": "店铺分每日自动采集",
      "source": "影刀RPA"
    }
  ]
}
```

Required record fields: `reportDate`, `platform`, `shopName`, `metricName`, `value`.

## Platform capability matrix

| Platform | Accepted scopes |
|---|---|
| 抖音 | shop score, reception count, refund rate |
| 天猫 | shop score, reception count |
| 拼多多 | shop score, reception count |
| 京东 | reception count only |
| 微信小店 | reception count only |
| 小红书 | reception count only |
| 快手 | reception count only |

For `shopKind: own`, the API also requires the exact configured shop under that
scope. A platform/type or platform/shop mismatch returns HTTP 422.

## Platform metric normalization

The parser submits the platform-facing names captured from the page. For example,
Tmall sends `宝贝质量` under `体验分`. The API's `normalizeImportedMetric`
function then maps that record to the dashboard model, such as `宝贝质量分` under
`总览`. Do not rewrite this mapping inside the shared parser; keep platform display
aliases in the API/reporting configuration so historical imports and dashboard
queries use one canonical identity.

Douyin may send the current labels `我的总分`, `商品体验`, `物流体验`, and
`服务体验`, or the previous labels `我的体验分`, `商品体验得分`,
`物流体验得分`, and `服务体验得分` under `体验分`. The API normalizes either
set to `店铺体验分`, `商品体验分`, `物流体验分`, and `服务体验分` under `总览`.
Detail metrics keep their platform-facing names and their `商品体验` / `物流体验`
/ `服务体验` groups.

Reception metrics use the same rule. Platform-facing aliases such as `咨询人数`,
`咨询量`, and `接待人数` normalize to `接待量` under `运营`, with metric code
`reception_count`. The dashboard only treats that canonical metric code as reception
data.

Douyin refund data uses the canonical identity `退款率` under `退款统计`, with unit
`%` and metric code `refund_rate`. The API rejects this scope on non-Douyin
platforms.

Pinduoduo peer ranking uses `本店铺体验分在同行排名` under `总览`, unit `区间`,
and a text value such as `30%-40%`. This is the only supported non-numeric score
value. The API validates both boundaries as 0–100 and stores the complete text in
`text_value` while leaving `numeric_value` null.

## Value rules

- Score: numeric value plus unit `分`.
- 30-day valid orders: `近30天有效订单` under `总览`, with a numeric value and unit `单`.
- Reception/consultation count: numeric value plus unit `单`; the parser may submit the platform-facing name.
- Douyin refund rate: `退款率` under `退款统计`, unit `%`, value such as `2.35%`.
- Pinduoduo peer rank: a range string such as `30%-40%`, unit `区间`.
- Percentage: keep a string such as `99.94%`; the API stores `0.9994`.
- Duration: send `47.09` plus unit `小时`, or `12.3` plus unit `秒`.
- Missing/unavailable values: omit the record. Do not submit `—`, `/`, or empty strings.

## Identity and idempotency

- Shop identity is exact `(platform, shopName, shopKind)`.
- Metric identity is `(metricCategory, metricName, unit)`.
- Daily identity is `(reportDate, shop, metric)`.
- Re-importing the same daily identity updates the record instead of duplicating it.
- A spelling, suffix, case, or punctuation difference in `shopName` creates another shop unless the project explicitly defines an alias.

## Responses

Dry-run success:

```json
{"ok": true, "dryRun": true, "received": 14, "valid": 14, "deduplicated": 0}
```

Formal success:

```json
{"ok": true, "received": 14, "processed": 14, "deduplicated": 0}
```

Common failures:

- `401`: API key is missing or wrong.
- `400`: records is missing/empty.
- `413`: more than 200 records.
- `422`: record validation or unit/value parsing failed.
- `500`: database or server failure.
